import logging
import os
import subprocess
from logging import Logger
from typing import Optional
from threading import Thread
import signal

from libsniffer.packet_listener import PacketListener
from libsniffer.websocket_handler import WebsocketHandler
from libsniffer.websocket_server import WebsocketServer

from pineapple.logger import get_logger


class Sniffer:

    def __init__(self, socket_path: str = '/tmp/tsniffer.sock', interface: str = 'br-lan'):
        self.socket_path = socket_path
        self.interface = interface
        self.running: bool = False
        self.logger = get_logger('httpeek', logging.DEBUG)
        self.websocket_server: Optional[WebsocketServer] = None
        self.packet_listener: Optional[PacketListener] = None

    def _start_daemon(self):
        error_file = '/tmp/sniffererrors.log'
        subprocess.call(['sniffer', self.interface], stderr=open(error_file, 'w'))

    def do_work(self):
        self.logger.debug('Starting sniffer')
        self.running = True

        daemon_thread = Thread(target=self._start_daemon)

        WebsocketServer.allow_reuse_address = True
        self.websocket_server = WebsocketServer(('', 9999), self.logger, WebsocketHandler)
        self.websocket_server.running = self.running

        self.packet_listener = PacketListener(self.socket_path, self.websocket_server, self.logger)

        try:
            self.logger.debug('Starting sniffer daemon')
            daemon_thread.start()
            self.logger.debug('Starting packet listener')
            self.packet_listener.start()
            self.logger.debug('Starting websocket server')
            self.websocket_server.serve_forever()
            self.stop()
        except Exception as e:
            self.logger.error(f'Sniffer job encountered an error: {e}')
            self.stop()

    def stop(self):
        self.running = False

        if self.websocket_server:
            self.websocket_server.running = False
            self.websocket_server.shutdown()
            self.websocket_server.server_close()

        if self.packet_listener:
            self.packet_listener.stop()

        os.system('killall -9 sniffer')


sniffer = Sniffer()


def clean_shutdown(sig, frame):
    print('Attempting to stop.')
    sniffer.stop()


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, clean_shutdown)
    signal.signal(signal.SIGINT, clean_shutdown)
    sniffer.do_work()
