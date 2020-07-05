import socketserver
import struct
import time
from base64 import b64encode
from email.message import Message
from email.parser import BytesParser
from hashlib import sha1
from codecs import decode
from io import StringIO
from typing import Any

from libsniffer.websocket_server import WebsocketServer


class WebsocketHandler(socketserver.StreamRequestHandler):
    magic = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

    def setup(self):
        socketserver.StreamRequestHandler.setup(self)

        if isinstance(self.server, WebsocketServer):
            self.server.websockets.append(self)

    def handle(self):
        handshake_done = False
        while self.server.running:
            if not handshake_done:
                handshake_done = self.handshake()
            else:
                time.sleep(5)

    def send_message(self, message: bytes):
        self.request.send(bytes([129]))
        length = len(message)
        if length <= 125:
            self.request.send(bytes([length]))
        elif 126 <= length <= 65535:
            self.request.send(bytes([126]))
            self.request.send(struct.pack('>H', length))
        else:
            self.request.send(bytes([127]))
            self.request.send(struct.pack('>Q', length))
        self.request.send(message)

    def build_response(self, key: str) -> str:
        digest = b64encode(decode(sha1((key + self.magic).encode('utf-8')).hexdigest().encode('utf-8'), 'hex'))
        response = 'HTTP/1.1 101 Switching Protocols\r\n'
        response += 'Upgrade: websocket\r\n'
        response += 'Connection: Upgrade\r\n'
        response += f'Sec-Websocket-Accept: {digest.decode("ascii")}\r\n\r\n'
        return response

    def handshake(self):
        data = self.request.recv(1024).strip()
        headers = BytesParser().parsebytes(data.split(b'\r\n', 1)[1])

        if headers.get('Upgrade', None) != 'websocket':
            return

        key = headers['Sec-Websocket-Key']
        response = self.build_response(key)
        return self.request.send(response.encode('ascii'))
