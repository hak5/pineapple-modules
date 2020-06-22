from logging import Logger
from typing import Optional
import urllib.request
import json


def json_to_bytes(message) -> bytes:
    """
    json deserialize a message and then decode it.
    Use this to convert your json message to bytes before publishing it over the socket.
    :param message: A json serializable list or a dict.
    :return: bytes
    """
    if not (type(message) is list or type(message) is dict):
        raise TypeError(f'Expected a list or dict but got {type(message)} instead.')

    d = json.dumps(message)

    return d.encode('utf-8')


def check_for_internet(url: str = 'http://www.example.com', timout: int = 1, logger: Optional[Logger] = None) -> bool:
    """
    Attempt to connect to a given url. If a connection was established then assume there is an internet connection.
    If the connection fails to establish or times out then assume there is not internet.
    :param url: The url to attempt to connect to. Default is http://www.example.com.
    :param timout: The amount of time in seconds to wait before giving up. Default is 1.
    :param logger: An optional instance of Logger use to log any exceptions while trying to establish a connection.
    :return: True if there is an internet connection, false if there is not
    """
    try:
        urllib.request.urlopen(url, timeout=timout)
        return True
    except Exception as e:
        if logger:
            logger.error(e)
        return False
