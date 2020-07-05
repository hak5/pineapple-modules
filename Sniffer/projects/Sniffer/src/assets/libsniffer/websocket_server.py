from logging import Logger
from socketserver import ThreadingTCPServer, BaseRequestHandler
from typing import Tuple, Callable, List


class WebsocketServer(ThreadingTCPServer):

    def __init__(self, server_address: Tuple[str, int], logger: Logger, RequestHandlerClass: Callable[..., BaseRequestHandler]):
        from libsniffer.websocket_handler import WebsocketHandler
        super().__init__(server_address, RequestHandlerClass)
        self.logger = logger
        self.websockets: List[WebsocketHandler] = []
        self.running: bool = True

    def send_all(self, message: str):
        self.logger.debug(f'Sending message to {len(self.websockets)} clients: {message}')
        for websocket in self.websockets:
            try:
                websocket.send_message(message.encode('utf-8'))
            except Exception as e:
                self.logger.error(f'Unable to send message to websocket: {e}')
                self.websockets.remove(websocket)
