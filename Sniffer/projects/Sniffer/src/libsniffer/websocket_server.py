from socketserver import ThreadingTCPServer, BaseRequestHandler, TCPServer
from typing import List, Tuple, Callable

from libsniffer.websocket_handler import WebsocketHandler


class WebsocketServer(TCPServer):

    def __init__(self, server_address: Tuple[str, int], RequestHandlerClass: Callable[..., BaseRequestHandler]):
        self.websockets: List[WebsocketHandler] = []
        super().__init__(server_address, RequestHandlerClass)

    def send_all(self, message: str):
        message_bytes = message.encode('utf-8')
        print(f'SENDING MESSAGE: {type(message_bytes)} | {message_bytes}')
        for websocket in self.websockets:
            websocket.send_message(message_bytes)
