import json
import os
from logging import Logger
from email.parser import BytesParser
import socket
import socketserver
from threading import Thread

from pineapple.jobs import Job

from libsniffer.websocket_handler import WebsocketHandler
from libsniffer.websocket_server import WebsocketServer


class WebsocketPublisher(Job[bool]):

    def __init__(self, socket_path: str = '/tmp/tsniffer.sock'):
        super().__init__()
        self.websockets = []
        self.socket_path = socket_path
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.running = False
        # self.websockets: List[WebsocketHandler] = [WebsocketHandler()]

        try:
            os.unlink(self.socket_path)
        except OSError:
            pass

    def _parse_data(self, data: bytes) -> dict:
        """
        Prase some data before publishing over websocket
        :param data:
        :return:
        """
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
                data_dict['post'] = post_data[1]

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

    def _start_webserver(self, server: WebsocketServer, logger: Logger):
        logger.debug('STARTING WEBSOCKET WEB SERVER')
        server.serve_forever()

    def do_work(self, logger: Logger) -> bool:
        self.running = True

        logger.debug(f'BINDING TO SOCKET: {self.socket_path}')
        self.socket.bind(self.socket_path)
        logger.debug('LISTENING')
        self.socket.listen(1)

        WebsocketServer.allow_reuse_address = True
        server = WebsocketServer(('', 9999), WebsocketHandler)
        websocket_thread = Thread(target=self._start_webserver, args=(server, logger, ), daemon=True)
        websocket_thread.start()

        logger.debug('ACCEPTING CONNECTIONS')
        while self.running:
            connection, client_address = self.socket.accept()
            logger.debug('RECEIVED CONNECTION!')

            try:
                data = self._handle_connection(connection)
                logger.debug(f'GOT DATA: {data}')
            except Exception as e:
                logger.error(f'EXCEPTION: {e}')
                continue

            logger.debug(f'PUBLISHING DATA TO {len(self.websockets)} WEBSOCKETS: {data}')
            server.send_all(data)

        server.shutdown()
        server.server_close()
        websocket_thread.join()
        return True
