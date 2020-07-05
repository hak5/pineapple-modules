import os
import subprocess
from logging import Logger
from typing import Optional
from threading import Thread

from libsniffer.packet_listener import PacketListener
from libsniffer.websocket_handler import WebsocketHandler
from libsniffer.websocket_server import WebsocketServer

from pineapple.jobs import Job


class SnifferJob(Job[bool]):

    def __init__(self, socket_path: str = '/tmp/tsniffer.sock', interface: str = 'br-lan'):
        super().__init__()
        self.socket_path = socket_path
        self.interface = interface
        self.running: bool = False
        self.websocket_server: Optional[WebsocketServer] = None
        self.packet_listener: Optional[PacketListener] = None

    def _start_daemon(self):
        error_file = '/tmp/sniffererrors.log'
        subprocess.call(['sniffer', self.interface], stderr=open(error_file, 'w'))

    def do_work(self, logger: Logger) -> bool:
        logger.debug('Starting sniffer')
        self.running = True

        daemon_thread = Thread(target=self._start_daemon, daemon=True)

        WebsocketServer.allow_reuse_address = True
        self.websocket_server = WebsocketServer(('', 9999), logger, WebsocketHandler)
        self.websocket_server.running = self.running

        self.packet_listener = PacketListener(self.socket_path, self.websocket_server, logger)
        self.packet_listener.setDaemon(True)

        try:
            logger.debug('Starting sniffer daemon')
            daemon_thread.start()
            logger.debug('Starting packet listener')
            self.packet_listener.start()
            logger.debug('Starting websocket server')
            self.websocket_server.serve_forever()
            self.stop()
        except Exception as e:
            logger.error(f'Sniffer job encountered an error: {e}')
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
