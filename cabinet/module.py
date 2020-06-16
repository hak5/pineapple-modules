from typing import Tuple, Dict, Callable, List
from dataclasses import dataclass
import logging
import pathlib
import os

from pineapple.modules import Module, Request


module = Module('cabinet', logging.DEBUG)

def _get_directory_contents(directory: pathlib.Path) -> List[dict]:
    return [ 
        { 
            'name': item.name,
            'path': str(item),
            'size': item.lstat().st_size,
            'permissions': oct(item.lstat().st_mode)[-3:],
            'is_directory': item.is_dir() 
        }
        for item in sorted(directory.iterdir(), key=lambda i: not i.is_dir())
    ]


def _delete_directory_tree(directory: pathlib.Path) -> bool:
    if not directory.is_dir():
        return False

    for item in directory.iterdir():
        module.logger.debug(f'DELETING ITEM: {str(item)}')
        if item.is_dir():
            _delete_directory_tree(item)
            item.rmdir()
        else:
            item.unlink()

    return True


@module.handles_action('list_directory')
def list_directory(request: Request) -> Tuple[bool, dict]:
    get_parent: bool = request.get_parent
    directory: pathlib.Path = pathlib.Path(request.directory) if not get_parent else pathlib.Path(request.directory).parent

    if not directory:
        return False, 'Directory not found.'

    if not os.path.isdir(directory):
        return False, 'Directory not found.'

    return True, {'working_directory': str(directory), 'contents': _get_directory_contents(directory)}


@module.handles_action('delete_item')
def delete_item(request: Request) -> Tuple[bool, str]:
    path = pathlib.Path(request.file_to_delete)

    module.logger.debug(f'DELETING: {request.file_to_delete}')

    if not path.exists():
        return False, 'File or directory does not exist.'

    if not path.is_absolute():
        return False, 'Absolute path expected.'

    if path.is_dir():
        success = _delete_directory_tree(path)
        if success:
            path.rmdir()
        else:
            return False, 'An error occurred deleting the directory.'
    else:
        path.unlink()

    return True, f'{path} has been deleted.'


@module.handles_action('write_file')
def write_file(request: Request) -> Tuple[bool, str]:
    path = pathlib.Path(request.file)
    content = request.content

    with open(str(path), 'w') as f:
        f.write(content)

    return True, 'File saved.'


@module.handles_action('read_file')
def read_file(request: Request) -> Tuple[bool, str]:
    path = pathlib.Path(request.file)

    if not path.exists() or not path.is_file():
        return False, 'Unable to open file.'

    with open(str(path), 'r') as f:
        return True, f.read()


@module.handles_action('create_directory')
def create_directory(request: Request) -> Tuple[bool, str]:
    path = pathlib.Path(f'{request.path}/{request.name}')

    module.logger.debug(f'CREATE FOLDER {request.name} IN PATH {request.path}. SHOULD BE {str(path)}')
    try:
        path.mkdir()
        return True, "Directory created."
    except FileExistsError:
        return False, "A file by that name already exists."


if __name__ == '__main__':
    module.start()
