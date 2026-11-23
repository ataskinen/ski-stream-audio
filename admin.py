#!/usr/bin/env python3
"""Authenticated local-network control panel for Ski Stream Audio."""
import argparse
import base64
from collections import deque
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
from audio_link import validate_config

ROOT = Path(__file__).resolve().parent


class Controller:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory/'config.json'
        if not self.path.exists():
            self.save_file(validate_config(dict(peer_ip='127.0.0.1', listen_port=5001,
                peer_port=5000, mode='receive', output_device='default', receive_gain=.1)))
        self.settings = validate_config(json.loads(self.path.read_text()))
        self.lock = threading.RLock()
        self.process = None
        self.log = deque(maxlen=60)
        self.metrics = {}
        self.last_status = 0
        self.last_error = ''
        self.last_error_time = 0
        self.testing = False
        self.desired = bool(self.settings['autostart'])
        self.shutdown = threading.Event()
        self.thread = threading.Thread(target=self.supervise, daemon=True)
        self.thread.start()

    def save_file(self, settings):
        temp = self.directory/'config.json.tmp'
        temp.write_text(json.dumps(settings, indent=2)+'\n')
        os.chmod(temp, 0o600)
        temp.replace(self.path)

    def read_logs(self, proc):
        for line in proc.stdout:
            with self.lock:
                if proc is not self.process:
                    continue
                self.log.append(line.strip())
                if 'ERROR' in line:
                    self.last_error = line.strip()
                    self.last_error_time = time.time()
                if 'STATUS ' in line:
                    try:
                        self.metrics = json.loads(line.split('STATUS ', 1)[1])
                        self.last_status = time.time()
                    except ValueError:
                        pass

    def launch(self, tone=False):
        self.metrics = {}
        self.last_status = 0
        self.last_error = ''
        args = [sys.executable, '-u', str(ROOT/'audio_link.py'), '--config', str(self.path)]
        if tone:
            args += ['--tone-output', '--duration', '3']
        self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, cwd=ROOT)
        threading.Thread(target=self.read_logs, args=(self.process,), daemon=True).start()

    def stop_process(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.process = None
        self.metrics = {}
        self.last_status = 0

    def supervise(self):
        while not self.shutdown.wait(1):
            with self.lock:
                if self.testing and self.process and self.process.poll() is not None:
                    self.testing = False
                    self.process = None
                if self.desired and not self.testing and (self.process is None or self.process.poll() is not None):
                    self.launch()

    def action(self, name, body):
        with self.lock:
            if name == 'config':
                settings = validate_config(body)
                settings['status_seconds'] = 1
                self.save_file(settings)
                self.settings = settings
                self.testing = False
                self.stop_process()
                if self.desired:
                    self.launch()
            elif name == 'start':
                self.desired = True
                self.testing = False
                self.stop_process()
                self.launch()
            elif name == 'stop':
                self.desired = False
                self.testing = False
                self.stop_process()
            elif name == 'tone':
                if self.settings['mode'] == 'send':
                    raise ValueError('Select receive or duplex mode and an output device first')
                # Local tone is temporary; resume the previous running state afterwards.
                self.stop_process()
                self.testing = True
                self.launch(tone=True)
            else:
                raise ValueError('Unknown action')

    def status(self):
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            fresh = running and time.time()-self.last_status < 4
            return dict(running=running, desired=self.desired, testing=self.testing,
                        metrics=self.metrics if fresh else {},
                        last_error=self.last_error, last_error_time=self.last_error_time,
                        log=list(self.log), status_age=None if not self.last_status else round(time.time()-self.last_status, 1))

    def close(self):
        self.shutdown.set()
        with self.lock:
            self.desired = False
            self.stop_process()
        self.thread.join(timeout=2)


def devices():
    # Fresh process refreshes PortAudio's device inventory after USB hot-plug.
    result = subprocess.run([sys.executable, str(ROOT/'audio_link.py'), '--devices-json'],
                            capture_output=True, text=True, timeout=12)
    if result.returncode:
        raise ValueError(result.stderr[-1000:] or 'Unable to list audio devices')
    return json.loads(result.stdout)


def make_handler(controller, password):
    expected = 'Basic ' + base64.b64encode(('admin:'+password).encode()).decode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Never log credentials or query strings.

        def send(self, code, data, content_type='application/json'):
            payload = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def authenticate(self):
            if not hmac.compare_digest(self.headers.get('Authorization', ''), expected):
                self.send_response(401)
                self.send_header('WWW-Authenticate', 'Basic realm="Ski Stream Audio"')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return False
            return True

        def do_GET(self):
            if not self.authenticate():
                return
            path = urlsplit(self.path).path
            try:
                if path == '/api/config':
                    return self.send(200, controller.settings)
                if path == '/api/status':
                    return self.send(200, controller.status())
                if path == '/api/devices':
                    return self.send(200, devices())
                assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                          '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
                if path in assets:
                    filename, kind = assets[path]
                    return self.send(200, (ROOT/'web'/filename).read_bytes(), kind)
                self.send(404, {'error': 'Not found'})
            except Exception as exc:
                self.send(500, {'error': str(exc)})

        def do_POST(self):
            if not self.authenticate():
                return
            # JSON + a custom header prevents cross-origin simple form submissions.
            origin = self.headers.get('Origin')
            if (self.headers.get('X-Ski-Audio') != '1' or
                self.headers.get('Content-Type') != 'application/json' or
                (origin and urlsplit(origin).netloc != self.headers.get('Host'))):
                return self.send(403, {'error': 'Same-origin JSON requests required'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16384:
                    raise ValueError('Request size must be 1–16384 bytes')
                body = json.loads(self.rfile.read(length))
                path = urlsplit(self.path).path
                if not path.startswith('/api/'):
                    return self.send(404, {'error': 'Not found'})
                controller.action(path[5:], body)
                self.send(200, {'ok': True})
            except (ValueError, TypeError) as exc:
                self.send(400, {'error': str(exc)})
            except Exception as exc:
                self.send(500, {'error': str(exc)})
    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir', default='local')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8080)
    args = p.parse_args()
    directory = Path(args.data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    password_file = directory/'admin-password'
    if not password_file.exists():
        with open(password_file, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as f:
            f.write(secrets.token_urlsafe(18)+'\n')
    password = password_file.read_text().strip()
    if len(password) < 12:
        raise SystemExit('Admin password must have at least 12 characters')
    controller = Controller(directory)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(controller, password))
    server.daemon_threads = True
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    print(f'Control panel: http://{args.host}:{args.port}; user admin; password in {password_file}', flush=True)
    try:
        server.serve_forever()
    finally:
        controller.close()
        server.server_close()


if __name__ == '__main__':
    main()
