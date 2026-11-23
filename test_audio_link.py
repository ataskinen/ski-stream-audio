import array
import json
import socket
import tempfile
import time
import unittest
import contextlib
import types
from unittest.mock import patch
import audio_link
from pathlib import Path
from audio_link import (HEADER, MAGIC, PAYLOAD, FRAMES, JitterBuffer, Link,
                        config, select_input, select_output)


def packet(seq, session=1, value=1):
    return HEADER.pack(MAGIC, session, seq) + bytes([value]) * PAYLOAD


class BufferTests(unittest.TestCase):
    def test_reorders_and_primes(self):
        b = JitterBuffer(2, 8)
        b.push(packet(2, value=2), 1)
        self.assertEqual(b.pop(1), bytes(PAYLOAD))
        b.push(packet(1), 1)
        self.assertEqual(b.pop(1), bytes([1])*PAYLOAD)
        self.assertEqual(b.pop(1), bytes([2])*PAYLOAD)

    def test_missing_packet_is_silence_and_late_packet_is_rejected(self):
        b = JitterBuffer(2, 8)
        b.push(packet(1), 1)
        b.push(packet(3, value=3), 1)
        b.pop(1)
        self.assertEqual(b.pop(1), bytes(PAYLOAD))
        self.assertFalse(b.push(packet(2), 1))
        self.assertEqual(b.pop(1), bytes([3])*PAYLOAD)
        self.assertFalse(b.push(packet(1), 1))

    def test_timeout_discards_buffer_and_recovers(self):
        b = JitterBuffer(2, 8)
        for n in (1, 2):
            b.push(packet(n), 1)
        self.assertEqual(b.pop(2), bytes(PAYLOAD))
        for n in (100, 101):
            b.push(packet(n, value=7), 3)
        self.assertEqual(b.pop(3), bytes([7])*PAYLOAD)

    def test_sender_restart_and_old_session(self):
        b = JitterBuffer(1, 4)
        b.push(packet(100), 1)
        b.pop(1)
        b.push(packet(0, session=2, value=2), 1)
        self.assertEqual(b.pop(1), bytes([2])*PAYLOAD)
        self.assertFalse(b.push(packet(101), 1))

    def test_backlog_is_bounded(self):
        b = JitterBuffer(2, 8)
        for n in range(1000):
            b.push(packet(n), 1)
        self.assertLessEqual(len(b.packets), 8)
        self.assertGreater(b.dropped, 0)
        self.assertGreaterEqual(b.next, 991)

    def test_malformed_and_duplicate_packets(self):
        b = JitterBuffer()
        self.assertFalse(b.push(b'garbage'))
        self.assertFalse(b.push(b'xxxx' + packet(1)[4:]))
        self.assertTrue(b.push(packet(1)))
        self.assertFalse(b.push(packet(1)))


class MappingTests(unittest.TestCase):
    def test_mono_input_duplicates_to_stereo(self):
        data = array.array('h', [123] * FRAMES).tobytes()
        self.assertEqual(select_input(data, 1, [1, 1]), array.array('h', [123] * FRAMES * 2).tobytes())

    def test_16_channel_input_and_output(self):
        data = array.array('h', list(range(16)) * FRAMES).tobytes()
        stereo = select_input(data, 16, [3, 4])
        self.assertEqual(list(array.array('h', stereo))[:4], [2, 3, 2, 3])
        out = array.array('h', select_output(stereo, 16, [1, 2]))
        self.assertEqual(list(out)[:16], [2, 3] + [0]*14)


class ConfigTests(unittest.TestCase):
    def test_examples(self):
        for p in Path(__file__).parent.glob('config/*.json'):
            config(p)

    def test_rejects_unsafe_values(self):
        base = json.loads((Path(__file__).parent/'config/pi.example.json').read_text())
        for patch in ({'peer_ip': 'example.org'}, {'listen_port': 0},
                      {'input_map': [0, 1]}, {'output_map': [1, 1]},
                      {'jitter_packets': 200, 'max_packets': 8},
                      {'retry_seconds': float('nan')}, {'unknown': True}):
            with self.subTest(patch=patch), tempfile.TemporaryDirectory() as d:
                p = Path(d)/'config.json'
                p.write_text(json.dumps(base | patch))
                with self.assertRaises(ValueError):
                    config(p)


class NetworkTests(unittest.TestCase):
    def test_duplex_peer_restart_and_wrong_source(self):
        # Ask the OS for free ports; no fixed test port collides with a running endpoint.
        reservations = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(2)]
        for s in reservations:
            s.bind(('127.0.0.1', 0))
        ports = [s.getsockname()[1] for s in reservations]
        for s in reservations:
            s.close()
        base = config(Path(__file__).parent/'config/pi.example.json')
        ca = base | dict(source_ip='127.0.0.1', source_port=ports[1], peer_ip='127.0.0.1', bind_ip='127.0.0.1', listen_port=ports[0], peer_port=ports[1], jitter_packets=1)
        cb = ca | dict(listen_port=ports[1], peer_port=ports[0], source_port=ports[0])
        a, b = Link(ca), Link(cb)
        try:
            a.start(); b.start()
            a.capture(bytes([1])*PAYLOAD); b.capture(bytes([2])*PAYLOAD)
            limit = time.monotonic()+2
            while (a.buffer.received < 1 or b.buffer.received < 1) and time.monotonic() < limit:
                time.sleep(.01)
            self.assertEqual(a.buffer.pop(), bytes([2])*PAYLOAD)
            self.assertEqual(b.buffer.pop(), bytes([1])*PAYLOAD)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as alien:
                alien.sendto(packet(99), ('127.0.0.1', ports[0]))
            time.sleep(.05)
            self.assertEqual(a.buffer.received, 1)
            b.close()
            time.sleep(.55)
            self.assertEqual(a.buffer.pop(), bytes(PAYLOAD))
            self.assertEqual(a.status()['link'], 'waiting')
            b = Link(cb); b.start()
            b.capture(bytes([3])*PAYLOAD)
            limit = time.monotonic()+2
            while a.buffer.received < 2 and time.monotonic() < limit:
                time.sleep(.01)
            self.assertEqual(a.buffer.pop(), bytes([3])*PAYLOAD)
            self.assertEqual(a.status()['link'], 'receiving')
        finally:
            a.close(); b.close()


class RecoveryTests(unittest.TestCase):
    def test_audio_device_open_failure_retries_and_closes_resources(self):
        base = config(Path(__file__).parent/'config/pi.example.json')
        base['retry_seconds'] = .1
        attempts = []
        closed = []

        class FakeLink:
            def __init__(self, c):
                self.errors = __import__('queue').Queue()
                self.last_capture = self.last_playback = time.monotonic()
            def start(self):
                pass
            def close(self):
                closed.append(True)
            def status(self):
                return {}

        def input_stream(**kwargs):
            attempts.append(True)
            if len(attempts) == 1:
                raise RuntimeError('device unplugged')
            return contextlib.nullcontext(types.SimpleNamespace(active=True))

        fake = types.SimpleNamespace(RawInputStream=input_stream,
            RawOutputStream=lambda **kwargs: contextlib.nullcontext(types.SimpleNamespace(active=True)))
        with patch.dict('sys.modules', {'sounddevice': fake}), patch.object(audio_link, 'Link', FakeLink):
            audio_link.run(base, duration=.35)
        self.assertGreaterEqual(len(attempts), 2)
        self.assertEqual(len(attempts), len(closed))


if __name__ == '__main__':
    unittest.main()
