import socket
import json

class Notifications:

    def __init__(self):
        self._notify_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._notify_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._notify_socket_path = '/tmp/notifications.sock'

    def _json_to_bytes(self, message) -> bytes:
        """
        json deserialize a message and then decode it.
        Use this to convert your json message to bytes before publishing it over the socket
        :param message: A json serializable list or a dict
        :return: bytes
        """
        if not (type(message) is list or type(message) is dict):
            self.logger.error(f'Expected a list or dict but got {type(message)} instead.')
            raise TypeError(f'Expected a list or dict but got {type(message)} instead.')

        d = json.dumps(message)
        return d.encode('utf-8')

    def notify(self, level: int, message: str, module_name: str) -> bool:
        """
        Send a notification over the WiFi Pineapples notification socket

        :param level: Notification level
        :param message: Notification message
        :return: bool
        """

        module_notification = {'level': level, 'message': message, 'module_name': module_name}
        socket_message = self._json_to_bytes(module_notification)
        status = True

        try:
            self._notify_socket.connect(self._notify_socket_path)
        except ValueError:
            self.logger.error('Could not connect to notifications socket!')
            return False

        try:
            self._notify_socket.sendall(socket_message)
        except ValueError:
            self.logger.error('Could not send notification!')
            status = False

        self._notify_socket.close()

        return status
