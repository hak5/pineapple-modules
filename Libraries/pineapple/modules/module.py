import os
import socket
import json
import logging
import signal
from typing import Tuple, Any, Callable, Optional, Dict

from pineapple.logger import get_logger
from pineapple.modules.request import Request
from pineapple.helpers import json_to_bytes
import pineapple.helpers.notification_helpers as notifier


class Module:

    def __init__(self, name: str, log_level: int = logging.WARNING):
        """
        :param name: The name of the module. Example `cabinet`
        :param log_level: The level of logging you wish to show. Default WARNING
        """
        self.logger = get_logger(name, log_level)  # logger for feedback.
        self.name = name  # the name of the module

        self.logger.debug(f'Initializing module {name}.')

        self._action_handlers: Dict[str, Callable[[Request], Tuple[bool, Any]]] = {}
        self._running: bool = False  # set to False to stop the module loop

        self._module_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)  # api requests will be received over this socket
        self._module_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._module_socket_path = f'/tmp/{name}.sock'  # apth to the socket
        self._buffer_size = 10485760

        # if the socket already exists attempt to delete it.
        try:
            os.unlink(self._module_socket_path)
        except OSError:
            if os.path.exists(self._module_socket_path):
                self.logger.error('Could not remove existing socket!')
                raise FileExistsError('Could not remove existing socket!')

        # If a SIGINT is received preform a clean shutdown by calling `shutdown()`
        signal.signal(signal.SIGINT, self.shutdown)

    def _receive(self) -> Optional[dict]:
        """
        Receive data over a socket and attempt to json deserialize it.
        If the deserialization fails, None will be returned
        :return: A dictionary containing the data received over the socket or None if json deserialization fails.
        """
        connection, _ = self._module_socket.accept()
        data = connection.recv(self._buffer_size)
        decoded_data = data.decode('utf-8')

        try:
            return json.loads(decoded_data)
        except ValueError:
            self.logger.warning('Non-JSON Received')

        return None

    def _publish(self, message: bytes):
        """
        Publish a message `message` to over `_module_socket`.
        Call this method to respond to a request.
        :param message: Bytes of a message that should be sent
        :return: None
        """
        self.logger.debug('Accepting on module socket')
        connection, _ = self._module_socket.accept()

        try:
            self.logger.debug(f'Sending response {str(message, "utf-8")}')
            connection.sendall(message)
        except ValueError:
            self.logger.error('Could not send response!')

    def _handle_request(self, request: Request):
        """
        Attempt to find an handle for the requests actions and call it.
        If there is no action registered for the request `request`, an error will be sent back over `module_socket`.

        If there is a handler registered the following will happen:
        * the action handler will be called
        * if the action handler returns an error, an error will be sent back over `module_socket`
        * if the action handler returns success, the data will be sent back over `module_socket`
        :param request: The request instance to handle
        :return: None
        """
        handler: Callable[[Request], Tuple[bool, Any]] = self._action_handlers.get(request.action)
        if not handler:
            self._publish(json_to_bytes({'error': f'No action handler registered for action {request.action}'}))
            self.logger.error(f'No action handler registered for action {request.action}')
            return

        try:
            result = handler(request)
        except Exception as e:
            self.logger.error(f'Handler raised exception: {e}')
            self._publish(json_to_bytes({'error': f'Handler raised exception: {e}'}))
            return

        if type(result) is not tuple:
            self.logger.error(f'Expected tuple but received {type(result)} instead.')
            self._publish(json_to_bytes({'error': f'Expected tuple but received {type(result)} instead.'}))
            return

        success, data = result
        response_dict = {}

        if success:
            response_dict['payload'] = data
        else:
            response_dict['error'] = data

        message_bytes = json_to_bytes(response_dict)

        # if the message is to big to be sent over the socket - return an error instead.
        if len(message_bytes) > self._buffer_size:
            self.logger.error(f'Response of {len(message_bytes)} bytes exceeds limit of {self._buffer_size}')
            message_bytes = json_to_bytes({
                'error': 'Response of {len(message_bytes)} bytes exceeds limit of {self._buffer_size}'
            })

        self._publish(message_bytes)

    def shutdown(self, sig=None, frame=None):
        """
        Attempt to clean shutdown the module.
        If your module has anything it needs to close or otherwise cleanup upon shutdown, please override this
        and do what you need to here. Be sure you call `super.shutdown()` in your new implementation.

        This method may also be called to handle signals such as SIGINT. If it was called as a signal handler the
        signal `sig` and frame `frame` will be passed into this method.
        :param sig: Optional signal that triggered a signal handler
        :param frame: Optional frame
        :return: None
        """
        self.logger.info(f'Shutting down module. Signal: {sig}')
        self._running = False
        self._module_socket.close()

    def start(self):
        """
        Main loop for the module which will run as long as `_running` is True.
        This will listen for data coming over `_module_socket` and deserialize it to a `Request` object.
        That object is then passed to `handle_request` for further processing.

        If an exception is thrown, this loop will stop working and attempt to do a clean shutdown of the module by
        calling `shutdown`.
        :return: None
        """
        self.logger.info('Starting module...')

        self.logger.debug(f'Binding to socket {self._module_socket_path}')
        self._module_socket.bind(self._module_socket_path)
        self._module_socket.listen(1)
        self.logger.debug('Listening on socket!')

        self._running = True
        while self._running:
            try:
                request_dict: Optional[dict] = self._receive()
                if not request_dict:
                    self.logger.debug("Received non-json data over the socket.")
                    continue

                self.logger.debug('Processing request.')
                request = Request()
                request.__dict__ = request_dict
                self._handle_request(request)
            except OSError as os_error:
                self.logger.warning(f'An os error occurred: {os_error}')
            except Exception as e:
                self.logger.critical(f'A fatal `{type(e)}` exception was thrown: {e}')
                self.shutdown()

    def handles_action(self, action: str):
        """
        A decorator that registers a function as an handler for a given action `action` in a request.
        The decorated function is expected take an instance of `Request` as its first argument
        and to return a Tuple with two values - bool, Any - in that order.

        The returned boolean value indicates whether or not the function completed successfully.
        The next value is whatever data you want returned in the response.
        This can be anything as long as it's json serializable.

        Usage Example:
            @handles_action("save_file")
            def save_file(request: Request) -> Tuple[bool, Any]:
                ...

        :param action: The request action to handle
        """
        def wrapper(func: Callable[[Any], Tuple[bool, Any]]):
            self._action_handlers[action] = func
            return func
        return wrapper

    def send_notification(self, message: str, level: int) -> bool:
        """
        Send a notification over the WiFi Pineapples notification socket

        :param message: Notification message
        :param level: Notification level
        :return: bool
        """
        return notifier.send_notification(message, self.name, level)
