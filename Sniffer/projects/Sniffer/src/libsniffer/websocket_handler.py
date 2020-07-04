import socketserver
import struct
import time
from base64 import b64encode
from email.message import Message
from hashlib import sha1
from io import StringIO
from typing import Any


class WebsocketHandler(socketserver.StreamRequestHandler):
    magic = 'd9911cf4-d812-44f5-9f19-cb1f170e6b44'

    def setup(self):
        import libsniffer
        print('SETUP CALLED!')
        if isinstance(self.server, libsniffer.websocket_server.WebsocketServer):
            print('APPENDING SELF!')
            self.server.websockets.append(self)
        else:
            print('SERVER ISNT THE THING')

    def handle(self):
        handshake_done = False
        while True:
            if not handshake_done:
                handshake_done = self.handshake()
            else:
                time.sleep(5)

    def send_message(self, message: bytes):
        print(f'RECEIVED MESSAGE OF TYPE: {type(message)}')
        print('0')
        self.request.send(chr(129).encode('utf-8'))
        print('1')
        length = len(message)
        print('2')
        if length <= 125:
            print('3')
            self.request.send(b'~')
            print('4')
        elif 126 <= length <= 65535:
            print('5')
            self.request.send(b'~')
            print('6')
            self.request.send(struct.pack(">H", length))
            print('7')
        else:
            print('8')
            self.request.send(b'\x7f')
            print('9')
            self.request.send(struct.pack(">Q", length))
            print('10')

        print('11')
        self.request.send(message)

    def handshake(self) -> bool:
        data = self.request.recv(1024).strip()
        headers = Message(data.split(b'\r\n', 1)[1])

        if headers.get("Upgrade", None) != "websocket":
            return False

        key = headers['Sec-WebSocket-Key']
        digest = b64encode(sha1(key + self.magic).hexdigest().decode('hex'))
        response = 'HTTP/1.1 101 Switching Protocols\r\n'
        response += 'Upgrade: websocket\r\n'
        response += 'Connection: Upgrade\r\n'
        response += 'Sec-WebSocket-Accept: %s\r\n\r\n' % digest
        return self.request.send(response)
