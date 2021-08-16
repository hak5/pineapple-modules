from logging import Logger
from typing import Optional, Tuple, List, Union
import subprocess
import os


def uci_set(key: str, value) -> bool:
    """
    Set a UCI property to value
    :param key: The UCI key to target
    :param value: The value to set the UCI key to
    :return: True if successful, false if not.
    """

    argument = f"{key}='{value}'"
    out = subprocess.run(["uci", "set", argument])

    if out.returncode != 0:
        return False

    out = subprocess.run(["uci", "commit"])
    if out.returncode != 0:
        return False

    return True


def uci_get(key: str) -> str:
    """
    Get a UCI value from it's key
    :param key: The UCI key to target
    :return: str
    """

    out = subprocess.check_output(["uci", "get", key]).decode("utf-8")
    return out
