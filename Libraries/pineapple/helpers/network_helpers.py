from typing import Optional, List
from logging import Logger
import urllib.request
import os


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


def get_interfaces() -> List[str]:
    """
    :return: A list of network interfaces available on the device.
    """
    return os.listdir('/sys/class/net/')
