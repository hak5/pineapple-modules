import socket

from pineapple.helpers import json_to_bytes


INFO = 0
WARN = 1
ERROR = 2
OTHER = 3
SUCCESS = 4


def send_notification(message: str, module_name: str, level: int = INFO) -> bool:
    """
    Send a notification over the WiFi Pineapples notification socket

    :param message: Notification message
    :param module_name: The name of the module the notification is from.
    :param level: Notification level
    :return: bool
    """

    notify_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    notify_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    notify_socket_path = '/tmp/notifications.sock'

    module_notification = {'level': level, 'message': message, 'module_name': module_name}
    socket_message = json_to_bytes(module_notification)
    status = True

    try:
        notify_socket.connect(notify_socket_path)
    except ValueError:
        return False

    try:
        notify_socket.sendall(socket_message)
    except ValueError:
        status = False

    notify_socket.close()

    return status
