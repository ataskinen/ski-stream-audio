#!/usr/bin/env python3
"""Stereo PCM audio link. No audio devices are opened in --test mode."""
import argparse
import array
import contextlib
import ipaddress
import json
import logging
import math
import queue
import secrets
import signal
import socket
import struct
import sys
import threading
import time
from pathlib import Path

RATE = 48000
FRAMES = 240  # 5 ms, 960 payload bytes: below a standard Ethernet MTU
CHANNELS = 2
PERIOD = FRAMES / RATE
PAYLOAD = FRAMES * CHANNELS * 2
HEADER = struct.Struct('!4sQQ')
MAGIC = b'SSA1'
STOP = threading.Event()


def config(path):
    return validate_config(json.loads(Path(path).read_text()))


def validate_config(c):
    if not isinstance(c, dict):
        raise ValueError('Configuration must be a JSON object')
    required = {'peer_ip', 'listen_port', 'peer_port'}
    allowed = required | {'bind_ip', 'input_channels', 'output_channels', 'input_map',
                          'output_map', 'jitter_packets', 'max_packets', 'timeout_seconds',
                          'retry_seconds', 'status_seconds', 'mode', 'input_device', 'output_device',
                          'send_gain', 'receive_gain', 'send_mute', 'receive_mute',
                          'source_ip', 'source_port', 'autostart', 'device_latency_seconds'}
    if required - c.keys() or c.keys() - allowed:
        raise ValueError(f'Missing keys: {required-c.keys()}; unknown keys: {c.keys()-allowed}')
    defaults = dict(device_latency_seconds=0.05, mode='duplex', input_device='', output_device='',
                    send_gain=1.0, receive_gain=0.25, send_mute=False, receive_mute=False, autostart=False,
                    source_ip=c['peer_ip'], source_port=c['peer_port'], bind_ip='0.0.0.0', input_channels=2, output_channels=2,
                    input_map=[1, 2], output_map=[1, 2], jitter_packets=8,
                    max_packets=32, timeout_seconds=0.5, retry_seconds=2, status_seconds=5)
    c = defaults | c
    if type(c['device_latency_seconds']) not in (float, int) or not math.isfinite(c['device_latency_seconds']) or not .01 <= c['device_latency_seconds'] <= 1:
        raise ValueError('device_latency_seconds must be between 0.01 and 1')
    if c['mode'] not in ('send', 'receive', 'duplex'):
        raise ValueError('mode must be send, receive or duplex')
    for key in ('send_mute', 'receive_mute', 'autostart'):
        if type(c[key]) is not bool:
            raise ValueError(f'{key} must be boolean')
    for key in ('send_gain', 'receive_gain'):
        if type(c[key]) not in (int, float) or not math.isfinite(c[key]) or not 0 <= c[key] <= 2:
            raise ValueError(f'{key} must be between 0 and 2')
    for key in ('peer_ip', 'bind_ip', 'source_ip'):
        ipaddress.IPv4Address(c[key])
    for key in ('listen_port', 'peer_port', 'source_port'):
        if type(c[key]) is not int or not 1024 <= c[key] <= 65535:
            raise ValueError(f'{key} must be an integer from 1024 to 65535')
    for key in ('input_channels', 'output_channels'):
        if type(c[key]) is not int or not 1 <= c[key] <= 32:
            raise ValueError(f'{key} must be an integer from 1 to 32')
    for key, channels in [('input_map', c['input_channels']), ('output_map', c['output_channels'])]:
        if not isinstance(c[key], list) or len(c[key]) != 2 or any(type(v) is not int or not 1 <= v <= channels for v in c[key]):
            raise ValueError(f'{key} must contain two valid 1-based channel numbers')
    if c['output_map'][0] == c['output_map'][1]:
        raise ValueError('output_map must use two different channels')
    for key in ('jitter_packets', 'max_packets'):
        if type(c[key]) is not int or not 1 <= c[key] <= 200:
            raise ValueError(f'{key} must be an integer from 1 to 200')
    if c['max_packets'] < 2 * c['jitter_packets']:
        raise ValueError('max_packets must be at least twice jitter_packets')
    for key in ('timeout_seconds', 'retry_seconds', 'status_seconds'):
        if isinstance(c[key], bool) or not isinstance(c[key], (int, float)) or not math.isfinite(c[key]) or not 0.1 <= c[key] <= 60:
            raise ValueError(f'{key} must be between 0.1 and 60 seconds')
    if c['timeout_seconds'] <= c['jitter_packets'] * PERIOD:
        raise ValueError('timeout_seconds must exceed the jitter buffer duration')
    for key in ('input_device', 'output_device'):
        if key == 'input_device' and c['mode'] == 'receive' or key == 'output_device' and c['mode'] == 'send':
            continue
        if not isinstance(c[key], (str, int)) or isinstance(c[key], bool) or c[key] == '':
            raise ValueError(f'{key} must be an explicit device name or index')
    return c


def select_input(data, channels, mapping):
    if channels == 2 and mapping == [1, 2]:
        return data
    samples = array.array('h', data)
    return array.array('h', (samples[f * channels + ch - 1]
                            for f in range(FRAMES) for ch in mapping)).tobytes()


def select_output(data, channels, mapping):
    if channels == 2 and mapping == [1, 2]:
        return data
    source = array.array('h', data)
    target = array.array('h', [0]) * (FRAMES * channels)
    for f in range(FRAMES):
        for lane, ch in enumerate(mapping):
            target[f * channels + ch - 1] = source[f * 2 + lane]
    return target.tobytes()


def apply_gain(data, gain, muted=False):
    # audioop is a C implementation; Python sample loops overload a throttled Pi 3.
    # On Python 3.13+, requirements installs the maintained audioop-lts extension.
    import audioop
    if muted or gain == 0:
        return bytes(len(data)), 0.0
    if data == bytes(len(data)):
        return data, 0.0
    scaled = data if gain == 1 else audioop.mul(data, 2, gain)
    return scaled, audioop.max(scaled, 2) / 32768


class JitterBuffer:
    """Small bounded reorder buffer. Missing blocks become silence, never old audio."""
    def __init__(self, target=8, maximum=32, timeout=0.5):
        self.target, self.maximum, self.timeout = target, maximum, timeout
        self.lock = threading.Lock()
        self.packets = {}
        self.session = None
        self.retired = []
        self.next = None
        self.consumed = -1
        self.playing = False
        self.last = None
        self.received = self.missing = self.dropped = self.resets = 0

    def push(self, packet, now=None):
        now = time.monotonic() if now is None else now
        if len(packet) != HEADER.size + PAYLOAD:
            return False
        magic, session, seq = HEADER.unpack_from(packet)
        if magic != MAGIC:
            return False
        with self.lock:
            if session in self.retired:
                return False
            if self.session != session:
                if self.session is not None:
                    self.retired = (self.retired + [self.session])[-16:]
                self.session = session
                self.consumed = -1
                self.packets.clear()
                self.next, self.playing = None, False
                self.resets += 1
            if self.last is not None and now - self.last > self.timeout:
                self.packets.clear()
                self.next, self.playing = None, False
            if seq <= self.consumed or (self.next is not None and self.playing and seq < self.next):
                self.dropped += 1
                return False
            if seq in self.packets:
                return False
            self.last = now
            self.received += 1
            self.packets[seq] = packet[HEADER.size:]
            if self.next is None or not self.playing:
                self.next = min(self.packets)
            if max(self.packets) - self.next >= self.maximum or len(self.packets) > self.maximum:
                self.next = max(self.packets) - self.target + 1
                self.consumed = self.next - 1
                old = [n for n in self.packets if n < self.next]
                for n in old:
                    del self.packets[n]
                self.dropped += len(old)
                self.playing = False
                self.resets += 1
            return True

    def pop(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.last is None or now - self.last > self.timeout:
                self.packets.clear()
                self.next, self.playing = None, False
                return bytes(PAYLOAD)
            if not self.playing:
                if len(self.packets) < self.target:
                    return bytes(PAYLOAD)
                self.playing = True
            data = self.packets.pop(self.next, None)
            self.consumed = self.next
            self.next += 1
            if data is None:
                self.missing += 1
            if not self.packets:
                self.playing = False
                self.next = None
            return data if data is not None else bytes(PAYLOAD)

    def status(self):
        with self.lock:
            age = None if self.last is None else time.monotonic() - self.last
            return dict(link='receiving' if age is not None and age < self.timeout else 'waiting',
                        received=self.received, missing=self.missing, dropped=self.dropped,
                        buffered=len(self.packets), resets=self.resets)


class Link:
    def __init__(self, c):
        self.c = c
        self.buffer = JitterBuffer(c['jitter_packets'], c['max_packets'], c['timeout_seconds'])
        self.outgoing = queue.Queue(maxsize=c['max_packets'])
        self.stop = threading.Event()
        self.errors = queue.Queue()
        self.session, self.sequence = secrets.randbits(64), 0
        self.sent = self.send_errors = self.capture_drops = self.audio_warnings = 0
        self.last_capture = self.last_playback = time.monotonic()
        self.send_peak = self.receive_peak = 0.0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((c['bind_ip'], c['listen_port']))
            self.sock.settimeout(0.2)
        except Exception:
            self.sock.close()
            raise
        self.threads = []

    def capture(self, data):
        packet = HEADER.pack(MAGIC, self.session, self.sequence) + data
        self.sequence += 1
        try:
            self.outgoing.put_nowait(packet)
        except queue.Full:
            self.capture_drops += 1
            try:
                self.outgoing.get_nowait()
            except queue.Empty:
                pass
            try:
                self.outgoing.put_nowait(packet)
            except queue.Full:
                pass

    def send(self):
        while not self.stop.is_set():
            try:
                packet = self.outgoing.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.sock.sendto(packet, (self.c['peer_ip'], self.c['peer_port']))
                self.sent += 1
            except OSError:
                self.send_errors += 1

    def receive(self):
        while not self.stop.is_set():
            try:
                packet, address = self.sock.recvfrom(2048)
                if address == (self.c['source_ip'], self.c['source_port']):
                    self.buffer.push(packet)
            except socket.timeout:
                pass
            except OSError as exc:
                if not self.stop.is_set():
                    self.errors.put(exc)
                return

    def start(self):
        functions = []
        if self.c['mode'] in ('send', 'duplex'):
            functions.append(self.send)
        if self.c['mode'] in ('receive', 'duplex'):
            functions.append(self.receive)
        for fn in functions:
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            self.threads.append(t)

    def close(self):
        self.stop.set()
        for t in self.threads:
            t.join(timeout=1)
        self.sock.close()

    def status(self):
        return self.buffer.status() | dict(sent=self.sent, send_errors=self.send_errors,
                    capture_drops=self.capture_drops, audio_warnings=self.audio_warnings,
                    send_peak=self.send_peak, receive_peak=self.receive_peak, mode=self.c['mode'])


def run(c, test=False, duration=None, tone_output=False):
    if sys.byteorder != 'little':
        raise RuntimeError('This version requires a little-endian host')
    deadline = None if duration is None else time.monotonic() + duration
    sending = c['mode'] in ('send', 'duplex') and not tone_output
    receiving = c['mode'] in ('receive', 'duplex') or tone_output
    tone_send = sending and (test or c['input_device'] == 'Test tone')
    sd = None
    if not test and ((sending and not tone_send) or receiving):
        import sounddevice as sd
    tone = array.array('h', (int(1000 * math.sin(2 * math.pi * 1000 * f / RATE))
                           for f in range(FRAMES) for _ in range(2))).tobytes()
    while not STOP.is_set() and (deadline is None or time.monotonic() < deadline):
        link = None
        try:
            link = Link(c)
            with contextlib.ExitStack() as stack:
                inp = out = None
                def capture(data, frames, timing, status):
                    link.last_capture = time.monotonic()
                    if status:
                        link.audio_warnings += 1
                    if frames == FRAMES:
                        pcm = select_input(bytes(data), c['input_channels'], c['input_map'])
                        pcm, link.send_peak = apply_gain(pcm, c['send_gain'], c['send_mute'])
                        link.capture(pcm)

                def playback(output, frames, timing, status):
                    link.last_playback = time.monotonic()
                    if status:
                        link.audio_warnings += 1
                    if frames != FRAMES:
                        output[:] = bytes(len(output))
                        return
                    pcm = tone if tone_output else link.buffer.pop()
                    pcm, link.receive_peak = apply_gain(pcm, c['receive_gain'], c['receive_mute'])
                    output[:] = select_output(pcm, c['output_channels'], c['output_map'])

                if not test:
                    if sending and not tone_send:
                        inp = stack.enter_context(sd.RawInputStream(device=c['input_device'], samplerate=RATE,
                            blocksize=FRAMES, channels=c['input_channels'], dtype='int16', latency=c['device_latency_seconds'], callback=capture))
                    if receiving:
                        out = stack.enter_context(sd.RawOutputStream(device=c['output_device'], samplerate=RATE,
                            blocksize=FRAMES, channels=c['output_channels'], dtype='int16', latency=c['device_latency_seconds'], callback=playback))
                if not tone_output:
                    link.start()
                logging.info('Endpoint ready: mode=%s; %s:%s -> %s:%s', c['mode'],
                    c['bind_ip'], c['listen_port'], c['peer_ip'], c['peer_port'])
                next_status = time.monotonic()
                tick = time.monotonic()
                while not STOP.is_set() and (deadline is None or time.monotonic() < deadline):
                    if not link.errors.empty():
                        raise link.errors.get()
                    if tone_send:
                        pcm, link.send_peak = apply_gain(tone, c['send_gain'], c['send_mute'])
                        link.capture(pcm)
                    if test and receiving:
                        _, link.receive_peak = apply_gain(link.buffer.pop(), c['receive_gain'], c['receive_mute'])
                    for stream, last in ((inp, link.last_capture), (out, link.last_playback)):
                        if stream is not None and (not stream.active or time.monotonic() - last > 3):
                            raise RuntimeError('Audio device stopped or no callbacks for three seconds')
                    now = time.monotonic()
                    if now >= next_status:
                        logging.info('STATUS %s', json.dumps(link.status(), sort_keys=True))
                        next_status = now + c['status_seconds']
                    tick = max(tick + (PERIOD if tone_send or test else 0.2), now)
                    STOP.wait(max(0, tick - time.monotonic()))
        except Exception as exc:
            logging.error('Endpoint failed: %s; retrying in %ss', exc, c['retry_seconds'])
        finally:
            if link is not None:
                link.close()
        if not STOP.is_set() and (deadline is None or time.monotonic() < deadline):
            STOP.wait(c['retry_seconds'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config.json')
    parser.add_argument('--devices-json', action='store_true')
    parser.add_argument('--tone-output', action='store_true')
    parser.add_argument('--list-devices', action='store_true')
    parser.add_argument('--check', action='store_true', help='Validate config without opening devices')
    parser.add_argument('--test', action='store_true', help='Send a quiet 1 kHz tone, discard received audio; no devices')
    parser.add_argument('--duration', type=float, help='Stop after this many seconds')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.list_devices or args.devices_json:
        import sounddevice as sd
        if args.devices_json:
            print(json.dumps([dict(d, index=i) for i, d in enumerate(sd.query_devices())]))
        else:
            print(sd.query_devices())
        return
    c = config(args.config)
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        parser.error('--duration must be positive and finite')
    if args.check:
        print(json.dumps(c, indent=2))
        return
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: STOP.set())
    if args.tone_output and args.duration is None:
        parser.error("--tone-output requires --duration")
    run(c, args.test, args.duration, args.tone_output)


if __name__ == '__main__':
    main()
