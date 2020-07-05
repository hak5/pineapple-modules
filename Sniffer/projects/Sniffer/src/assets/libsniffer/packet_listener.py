import json
import os
import socket
from email.parser import BytesParser
from logging import Logger
from threading import Thread

from libsniffer.websocket_server import WebsocketServer


class PacketListener(Thread):

    def __init__(self, socket_path: str, server: WebsocketServer, logger: Logger):
        super().__init__()
        self.socket_path = socket_path
        self.websocket_server = server
        self.logger = logger
        self.socket_path = socket_path
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        try:
            os.unlink(self.socket_path)
        except OSError:
            pass

    @staticmethod
    def _parse_data(data: bytes) -> dict:
        data = data.split(b'|', 2)

        data_dict = {
            'from': data[0].decode('utf-8'),
            'to': data[1].decode('utf-8')
        }

        path, headers = data[2].split(b'\r\n', 1)
        payload = BytesParser().parsebytes(headers)

        host = payload['host']
        path_part = path.split(b' ')[1].decode('utf-8')
        url = f'http://{host}{path_part}'

        if url.lower().endswith(('.png', '.ico', '.jpeg', '.jpg', '.gif', '.svg')):
            data_dict['image'] = url
        else:
            data_dict['url'] = url

        if 'cookie' in payload:
            data_dict['cookie'] = payload['cookie']

        post_data = data[2].split(b'\r\n\r\n')
        if len(post_data) == 2:
            if post_data[1].strip():
                data_dict['post'] = post_data[1].decode('utf-8')

        return data_dict

    def _handle_connection(self, connection):
        data = b''
        try:
            while True:
                buff = connection.recv(4096)
                if buff:
                    data += buff
                else:
                    break
        finally:
            connection.close()

        parsed_data = self._parse_data(data)
        return json.dumps(parsed_data)

    def stop(self):
        try:
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
        except Exception as e:
            self.logger.error(f'Error deleting socket file: {e}')

    def run(self):
        self.socket.bind(self.socket_path)
        self.socket.listen(1)

        while self.websocket_server.running:
            connection, client_address = self.socket.accept()
            self.logger.debug('RECEIVED CONNECTION!')

            try:
                data = self._handle_connection(connection)
                self.websocket_server.send_all(data)
            except Exception as e:
                self.logger.error(f'EXCEPTION: {e}')
                continue

        self.socket.close()
        print('PACKET LISTENER RETURNED')
