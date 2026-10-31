import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from character_maker.gateway import Gateway, base_url

APP = QApplication.instance() or QApplication([])


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/slow/'):
            time.sleep(.25)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        try:
            self.wfile.write(b'{"data":[{"id":"local-test"}]}')
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def log_message(self, *args):
        pass


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.gateway = Gateway()
        self.events = []
        self.gateway.succeeded.connect(lambda token, data: self.events.append(('ok', token, data)))
        self.gateway.failed.connect(lambda token, error: self.events.append(('error', token, error)))
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def wait(self, ms=500):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def test_url_validation_and_normalization(self):
        self.assertEqual(base_url(self.url), self.url + '/v1')
        self.assertEqual(base_url(self.url + '/v1/'), self.url + '/v1')
        for invalid in ('file:///tmp', 'http://user:secret@localhost', 'http://localhost?token=key'):
            with self.assertRaises(ValueError):
                base_url(invalid)

    def test_async_get_models(self):
        self.gateway.send('a', {'base_url': self.url, 'timeout': 2})
        self.wait()
        self.assertEqual(self.events[0], ('ok', 'a', {'data': [{'id': 'local-test'}]}))
        self.assertFalse(self.gateway.pending)

    def test_cancel_late_response_cannot_clear_new_request(self):
        self.gateway.send('old', {'base_url': self.url + '/slow', 'timeout': 2})
        self.gateway.cancel()
        self.gateway.send('new', {'base_url': self.url, 'timeout': 2})
        self.wait()
        self.assertEqual([event[:2] for event in self.events], [('ok', 'new')])
        self.assertFalse(self.gateway.pending)

    def test_timeout_only_one_terminal_event(self):
        self.gateway.send('timeout', {'base_url': self.url + '/slow', 'timeout': 0})
        self.wait()
        self.assertEqual([event[:2] for event in self.events], [('error', 'timeout')])
        self.assertFalse(self.gateway.pending)
