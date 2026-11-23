#!/usr/bin/env python3
"""Exercise two CLI endpoints and recovery without opening audio devices."""
import json
import pathlib
import socket
import subprocess
import sys
import tempfile
import time

root = pathlib.Path(__file__).resolve().parents[1]


def wait_for(path, needle, offset=0, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = path.read_text() if path.exists() else ''
        if needle in text[offset:]:
            return len(text)
        time.sleep(.05)
    raise RuntimeError(f'Did not see {needle} in {path.name}:\n{text}')


def stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise RuntimeError('Endpoint failed to stop gracefully')


def main():
    processes, handles = [], []
    with tempfile.TemporaryDirectory(prefix='ski-audio-test-') as directory:
        d = pathlib.Path(directory)
        sockets = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(2)]
        try:
            for sock in sockets:
                sock.bind(('127.0.0.1', 0))
            ports = [sock.getsockname()[1] for sock in sockets]
        finally:
            for sock in sockets:
                sock.close()
        for i in range(2):
            cfg = json.loads((root/'config/pi.example.json').read_text())
            cfg.update(peer_ip='127.0.0.1', bind_ip='127.0.0.1', listen_port=ports[i],
                       peer_port=ports[1-i], status_seconds=.2)
            (d/f'{i}.json').write_text(json.dumps(cfg))

        def start(i):
            log = open(d/f'{i}.log', 'a')
            handles.append(log)
            p = subprocess.Popen([sys.executable, str(root/'audio_link.py'),
                                  '--config', str(d/f'{i}.json'), '--test'],
                                 stdout=log, stderr=log)
            processes.append(p)
            return p

        try:
            a, b = start(0), start(1)
            for i in range(2):
                wait_for(d/f'{i}.log', '"link": "receiving"')
            marker = len((d/'0.log').read_text())
            stop(b)
            wait_for(d/'0.log', '"link": "waiting"', marker)
            marker = len((d/'0.log').read_text())
            b = start(1)
            wait_for(d/'0.log', '"link": "receiving"', marker)
            if a.poll() is not None or b.poll() is not None:
                raise RuntimeError('An endpoint exited unexpectedly')
            print('PASS: two-way CLI UDP audio, peer outage, recovery and continued operation')
        finally:
            for p in processes:
                stop(p)
            for h in handles:
                h.close()


if __name__ == '__main__':
    main()
