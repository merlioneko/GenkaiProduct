import json
from urllib.parse import urlsplit
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkProxy, QNetworkReply
from .models import strict_json


def base_url(value):
    value = value.strip().rstrip('/')
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('接続先は認証情報を含まないhttp(s) URLにしてください')
    return value if parts.path.endswith('/v1') else value + '/v1'


class Gateway(QObject):
    succeeded = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.manager.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self.pending = {}

    def send(self, token, settings, payload=None):
        if self.pending:
            raise ValueError('通信が進行中です')
        url = base_url(settings['base_url']) + ('/models' if payload is None else '/chat/completions')
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
        if settings.get('api_key'):
            request.setRawHeader(b'Authorization', ('Bearer ' + settings['api_key']).encode())
        reply = self.manager.get(request) if payload is None else self.manager.post(
            request, json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        timer = QTimer(self)
        timer.setSingleShot(True)
        self.pending[token] = (reply, timer)
        reply.finished.connect(lambda: self.finish(token, reply))
        timer.timeout.connect(lambda: self.timeout(token))
        timer.start(int(settings['timeout']) * 1000)

    def finish(self, token, reply):
        item = self.pending.pop(token, None)
        if item is None:
            reply.deleteLater()
            return
        item[1].stop()
        item[1].deleteLater()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        raw = bytes(reply.readAll()).decode('utf-8', errors='replace')
        error = reply.errorString()
        network_error = reply.error()
        reply.deleteLater()
        if status != 200 or network_error != QNetworkReply.NetworkError.NoError:
            self.failed.emit(token, f'HTTP {status or "接続失敗"}: {error}\n{raw[:2000]}')
            return
        try:
            data = strict_json(raw)
        except (ValueError, TypeError) as exc:
            self.failed.emit(token, f'API応答がJSONではありません: {exc}')
            return
        self.succeeded.emit(token, data)

    def cancel(self):
        items = list(self.pending.values())
        self.pending.clear()
        for reply, timer in items:
            timer.stop()
            timer.deleteLater()
            reply.abort()

    def timeout(self, token):
        if token in self.pending:
            self.cancel()
            self.failed.emit(token, '要求の期限を超えました。接続設定の期限を増やして再試行できます。')
