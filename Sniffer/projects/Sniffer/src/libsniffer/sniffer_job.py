import os
import subprocess
from logging import Logger
from typing import Optional
from threading import Thread

from pineapple.jobs import Job

from libsniffer.pakcet_listener import PacketListener
from libsniffer.websocket_handler import WebsocketHandler
from libsniffer.websocket_server import WebsocketServer


class SnifferJob(Job[bool]):

    def __init__(self, socket_path: str = '/tmp/tsniffer.sock', interface: str = 'br-lan'):
        super().__init__()
        self.socket_path = socket_path
        self.interface = interface
        self.running: bool = False
        self.websocket_server: Optional[WebsocketServer] = None
        self.packet_listener = Optional[PacketListener] = None

    def _start_daemon(self):
        error_file = '/tmp/sniffererrors.log'
        subprocess.call(['sniffer', self.interface], stderr=open(error_file, 'w'))

    def do_work(self, logger: Logger) -> bool:
        self.running = True

        daemon_thread = Thread(target=self._start_daemon, daemon=True)

        WebsocketServer.allow_reuse_address = True
        self.websocket_server = WebsocketServer(('', 9999), logger, WebsocketHandler)
        self.websocket_server.running = self.running

        self.packet_listener = PacketListener(self.socket_path, self.websocket_server, logger)
        self.packet_listener.setDaemon(True)

        try:
            daemon_thread.start()
            self.packet_listener.start()
            self.websocket_server.serve_forever()
            self.packet_listener.join()
        except KeyboardInterrupt:
            self.stop()

        return True

    def stop(self):
        self.running = False

        if self.websocket_server:
            self.websocket_server.running = False
            self.websocket_server.server_close()
            self.websocket_server.shutdown()

        if self.packet_listener:
            self.packet_listener.stop()

        os.system('killall -9 sniffer')
