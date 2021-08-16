import os
import socket
import json
import logging
import signal
from typing import Tuple, Any, Callable, Optional, Dict, Union, List

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

        # A list of functions to called when module is started.
        self._startup_handlers: List[Callable[[], None]] = []

        # A list of functions to be called when module is stopped.
        self._shutdown_handlers: List[Callable[[int], None]] = []

        # A dictionary mapping an action to a function.
        self._action_handlers: Dict[str, Callable[[Request], Union[Any, Tuple[bool, Any]]]] = {}

        # Set to False to stop the module loop
        self._running: bool = False

        # Create a storage folder for the module by default
        self._storage_folder_path = f'/root/.{name}/'
        if not os.path.exists(self._storage_folder_path):
            os.mkdir(self._storage_folder_path)

        # API requests will be received over this socket
        self._module_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._module_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._module_socket_path = f'/tmp/modules/{name}.sock'  # apth to the socket
        self._buffer_size = 10485760

        # If the socket already exists attempt to delete it.
        try:
            os.unlink(self._module_socket_path)
        except OSError:
            if os.path.exists(self._module_socket_path):
                self.logger.error('Could not remove existing socket!')
                raise FileExistsError('Could not remove existing socket!')

        # If a SIGINT is received preform a clean shutdown by calling `shutdown()`
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)

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
        handler: Callable[[Request], Union[Any, Tuple[Any, bool]]] = self._action_handlers.get(request.action)

        if not handler:
            self._publish(json_to_bytes({'error': f'No action handler registered for action {request.action}'}))
            self.logger.error(f'No action handler registered for action {request.action}')
            return

        try:
            self.logger.debug(f'Calling handler for action {request.action} and passing {request.__dict__}')
            result = handler(request)
        except Exception as e:
            self.logger.error(f'Handler raised exception: {e}')
            self._publish(json_to_bytes({'error': f'Handler raised exception: {e}'}))
            return

        if isinstance(result, tuple):
            if len(result) > 2:
                self.logger.error(f'Action handler `{request.action}` returned to many values.')
                self._publish(json_to_bytes({'error': f'Action handler `{request.action}` returned to many values.'}))
                return

            if not isinstance(result[1], bool):
                self.logger.error(f'{request.action}: second value expected to be a bool but got {type(result[1])} instead.')
                self._publish(json_to_bytes({
                    'error': f'{request.action}: second value expected to be a bool but got {type(result[1])} instead.'
                }))
                return

            data, success = result
        else:
            success = True
            data = result

        if success:
            response_dict = {'payload': data}
        else:
            response_dict = {'error': data}

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

        self.logger.debug(f'Calling {len(self._shutdown_handlers)} shutdown handlers.')
        try:
            for handler in self._shutdown_handlers:
                handler(sig)
        except Exception as e:
            self.logger.warning(f'Shutdown handler raised an exception: {str(e)}')

        try:
            os.unlink(f'/tmp/modules/{self.name}.sock')
            os.unlink(f'/tmp/modules/{self.name}.pid')
        except Exception as e:
            self.logger.warning(f'Error deleting socket or pid file: {str(e)}')

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

        self.logger.debug(f'Calling {len(self._startup_handlers)} startup handlers.')
        for handler in self._startup_handlers:
            try:
                handler()
            except Exception as e:
                self.logger.warning(f'Startup handler raised an exception: {str(e)}')

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

    def register_action_handler(self, action: str, handler: Callable[[Request], Union[Any, Tuple[Any, bool]]]):
        """
        Manually register an function `handler` to handle an action `action`.
        This function will be called anytime a request with the matching action is received.
        The action handler must take a positional argument of type `Request`. This must be the first argument.

        Usage Example:
            module = Module('example')

            def save_file(request: Request) -> Union[Any, Tuple[Any, bool]]:
                ...

            module.register_action_handler(save_file)

        :param action: The request action to handle
        :param handler: A function that takes `Request` that gets called when the matching `action` is received.
        """
        self._action_handlers[action] = handler

    def handles_action(self, action: str):
        """
        A decorator that registers a function as an handler for a given action `action` in a request.
        The decorated function is expected take an instance of `Request` as its first argument and can return either
        Any or a tuple with two values - Any, bool - in that order.

        If the function does not return a tuple, The response is assumed to be successful and the returned value
        will be json serialized and placed into the 'payload' of the response body.

        Example Function:
            @handles_action('save_file')
            def save_file(request: Request) -> str:
                ...
                return 'Filed saved successfully!'

        Example Response:
            { "payload": "File saved successfully!" }

        If a tuple is returned, the first value in the tuple will the data sent back to the user. The second value
        must be a boolean that indicates whether the function was successful (True) or not (False). If this
        value is True, the data in the first index will be sent back in the response payload.

        Example Function:
            @handles_action('save_file')
            def save_file(request: Request) -> Tuple[str, bool]:
                ...
                return 'Filed saved successfully!', True

        Example Response:
            { "payload": "File saved successfully!" }

        However, if this value is False, The data in the first index will be sent back as an error.

        Example Function:
            @handles_action('save_file')
            def save_file(request: Request) -> Tuple[str, bool]:
                ...
                return 'There was an issue saving the file.', False

        Example Response:
            { "error": There was an issue saving the file." }

        :param action: The request action to handle
        """
        def wrapper(func: Callable[[Request], Union[Any, Tuple[Any, bool]]]):
            self.register_action_handler(action, func)
            return func
        return wrapper

    def register_shutdown_handler(self, handler: Callable[[Optional[int]], None]):
        """
        Manually register a function `handler` to be called on the module shutdown lifecycle event.
        This handler function must take an integer as a parameter which may be the kill signal sent to the application.
        Depending on how the module is shutdown, the signal value may be None.

        Example:
            module = Module('example')

            def stop_all_tasks(signal: int):
                ...

            module.register_shutdown_handler(stop_all_tasks)

        :param handler: A function to be called on shutdown lifecycle event.
        """
        self._shutdown_handlers.append(handler)

    def on_shutdown(self):
        """
        A decorator that registers a function as a shutdown handler to be called on the shutdown lifecycle event.
        In the example below, the function `stop_all_tasks` will be called when the module process is terminated.

        Example:
            @module.on_shutdown()
            def stop_all_tasks(signal: int):
                ...
        """
        def wrapper(func: Callable[[int], None]):
            self.register_shutdown_handler(func)
            return func
        return wrapper

    def register_startup_handler(self, handler: Callable[[], None]):
        """
        Manually register a function `handler` to be called on the module start lifecycle event.
        This handler function most not take any arguments.

        Example:
            module = Module('example')

            def copy_configs():
                ...

            module.register_startup_handler(copy_configs)

        :param handler:
        :return:
        """
        self._startup_handlers.append(handler)

    def on_start(self):
        """
        A decorator that registers a function as a startup handler to be called on the start lifecycle event.
        In the example below, the function `copy_configs` will be called when the modules `start` method is called.

        Example:
            @module.on_start()
            def copy_configs():
                ...
        :return:
        """
        def wrapper(func: Callable[[], None]):
            self.register_startup_handler(func)
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
