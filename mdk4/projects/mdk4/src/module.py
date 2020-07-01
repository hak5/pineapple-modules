#!/usr/bin/env python3

import logging
import pathlib
import os

from typing import List, Tuple

from pineapple.modules import Module, Request
from pineapple.helpers import network_helpers as net


# CONSTANTS
_HISTORY_DIRECTORY_PATH = '/root/.mdk4'
_HISTORY_DIRECTORY = pathlib.Path(_HISTORY_DIRECTORY_PATH)
# CONSTANTS

module = Module('mdk4', logging.DEBUG)


def _make_history_directory():
    if not _HISTORY_DIRECTORY.exists():
        _HISTORY_DIRECTORY.mkdir(parents=True)


@module.handles_action('load_history')
def load_history(request: Request) -> Tuple[bool, List[str]]:
    return True, [item.name for item in _HISTORY_DIRECTORY.iterdir() if item.is_file()]


@module.handles_action('load_output')
def load_output(request: Request) -> Tuple[bool, str]:
    output_path = f'{_HISTORY_DIRECTORY_PATH}/{request.output_file}'
    if not os.path.exists(output_path):
        return False, 'Could not find scan output.'

    with open(output_path, 'r') as f:
        return True, f.read()


@module.handles_action('delete_result')
def delete_result(request: Request) -> Tuple[bool, bool]:
    output_path = pathlib.Path(f'{_HISTORY_DIRECTORY_PATH}/{request.output_file}')
    if output_path.exists() and output_path.is_file():
        output_path.unlink()

    return True, True


@module.handles_action('clear_history')
def clear_history(request: Request) -> Tuple[bool, bool]:
    for item in _HISTORY_DIRECTORY.iterdir():
        if item.is_file():
            item.unlink()

    return True, True


@module.handles_action('startup')
def startup(request: Request) -> Tuple[bool, dict]:
    return True, {
        'has_dependencies': True,
        'interfaces': net.get_interfaces(),
        'last_job': ''
    }


if __name__ == '__main__':
    _make_history_directory()
    module.start()
