import base64
import contextlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import admin
import audio_link as audio


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.controller = admin.Controller(self.tmp.name)
        self.server = admin.ThreadingHTTPServer(('127.0.0.1', 0), admin.make_handler(self.controller, 'test-password-only'))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.auth = {'Authorization': 'Basic '+base64.b64encode(b'admin:test-password-only').decode()}

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        self.controller.close(); self.thread.join(); self.tmp.cleanup()

    def request(self, method, path, payload=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        c.request(method, path, body=json.dumps(payload) if payload is not None else None, headers=headers or {})
        response = c.getresponse()
        body = response.read()
        status = response.status
        c.close()
        return status, body

    def test_auth_required(self):
        for path in ('/', '/api/config', '/api/status', '/api/devices'):
            self.assertEqual(self.request('GET', path)[0], 401)
        self.assertEqual(self.request('POST', '/api/start', {})[0], 401)
        self.assertEqual(self.request('GET', '/', headers=self.auth)[0], 200)

    def test_csrf_blocked_and_config_persists(self):
        c = self.controller.settings | {'receive_gain': .15, 'mode': 'receive', 'output_device':'test output'}
        headers = self.auth | {'Content-Type':'application/json','X-Ski-Audio':'1'}
        self.assertEqual(self.request('POST','/api/config',c,self.auth)[0],403)
        self.assertEqual(self.request('POST','/api/config',c,headers|{'Origin':'http://evil.example'})[0],403)
        self.assertEqual(self.request('POST','/api/config',c,headers)[0],200)
        self.assertEqual(json.loads((Path(self.tmp.name)/'config.json').read_text())['receive_gain'],.15)
        self.assertEqual(self.request('POST','/api/config',c|{'listen_port':1},headers)[0],400)
        self.assertEqual(self.controller.settings['listen_port'],5001)
        self.assertEqual(self.request('POST','/api/config',[],headers)[0],400)

    def test_inactive_status_does_not_reuse_old_meters(self):
        self.controller.metrics={'receive_peak':.9}
        self.assertEqual(self.controller.status()['metrics'],{})


class ModeTests(unittest.TestCase):
    def test_receive_requires_no_input_device(self):
        c = audio.validate_config(dict(peer_ip='127.0.0.1',listen_port=6001,peer_port=6000,
            mode='receive',output_device='headphones',input_device=''))
        self.assertEqual(c['input_device'],'')

    def test_send_requires_no_output_device(self):
        c = audio.validate_config(dict(peer_ip='127.0.0.1',listen_port=6000,peer_port=6001,
            mode='send',input_device='Test tone',output_device=''))
        self.assertEqual(c['output_device'],'')

    def test_gain_mute_clipping(self):
        import array
        pcm=array.array('h',[30000,-30000]*audio.FRAMES).tobytes()
        result, peak=audio.apply_gain(pcm,2)
        self.assertEqual(list(array.array('h',result))[:2],[32767,-32768])
        self.assertEqual(peak,1)
        self.assertEqual(audio.apply_gain(pcm,1,True),(bytes(len(pcm)),0))

    def test_receive_opens_only_output(self):
        c = audio.validate_config(dict(peer_ip='127.0.0.1',listen_port=6001,peer_port=6000,
            mode='receive',output_device='headphones'))
        output=[]
        class FakeLink:
            def __init__(self,c):
                import queue, time
                self.errors=queue.Queue()
                self.last_capture=self.last_playback=time.monotonic()
            def start(self): pass
            def close(self): pass
            def status(self): return {}
        def inp(**kwargs): raise AssertionError('Must not open input in receive mode')
        def out(**kwargs):
            output.append(True)
            return contextlib.nullcontext(types.SimpleNamespace(active=True))
        fake=types.SimpleNamespace(RawInputStream=inp,RawOutputStream=out)
        with patch.dict('sys.modules',{'sounddevice':fake}),patch.object(audio,'Link',FakeLink):
            audio.run(c,duration=.15)
        self.assertEqual(output,[True])



class StartupTests(unittest.TestCase):
    def test_fresh_server_creates_password_and_serves_authenticated_status(self):
        import socket, subprocess, sys, time
        with tempfile.TemporaryDirectory() as directory:
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1',0))
                port=reservation.getsockname()[1]
            proc=subprocess.Popen([sys.executable,str(Path(admin.__file__)),
                '--data-dir',directory,'--port',str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                password_file=Path(directory)/'admin-password'
                deadline=time.monotonic()+5
                while time.monotonic()<deadline and not password_file.exists() and proc.poll() is None:
                    time.sleep(.05)
                self.assertTrue(password_file.exists())
                password=password_file.read_text().strip()
                self.assertGreaterEqual(len(password),12)
                self.assertEqual(password_file.stat().st_mode & 0o777,0o600)
                response=None
                while time.monotonic()<deadline:
                    try:
                        c=http.client.HTTPConnection('127.0.0.1',port,timeout=1)
                        token=base64.b64encode(('admin:'+password).encode()).decode()
                        c.request('GET','/api/status',headers={'Authorization':'Basic '+token})
                        response=c.getresponse(); body=response.read(); c.close(); break
                    except OSError:
                        time.sleep(.05)
                self.assertIsNotNone(response)
                self.assertEqual(response.status,200)
                self.assertFalse(json.loads(body)['running'])
            finally:
                proc.terminate()
                try: proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.communicate(); raise

if __name__ == '__main__': unittest.main()
