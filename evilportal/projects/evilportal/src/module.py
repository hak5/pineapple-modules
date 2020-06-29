#!/usr/bin/env python3
import json
from typing import Dict, Tuple, List
import logging
import pathlib
import os

from pineapple.modules import Module, Request
from pineapple.jobs import JobManager
from pineapple.helpers.opkg_helpers import OpkgJob
import pineapple.helpers.command_helpers as cmd
import pineapple.helpers.opkg_helpers as opkg


module = Module('evilportal', logging.DEBUG)
manager = JobManager('evilportal', log_level=logging.DEBUG, module=module)

# CONSTANTS
_DEPENDENCIES = ['php7', 'php7-cgi', 'lighttpd', 'lighttpd-mod-cgi']
_MODULE_PATH = '/pineapple/ui/modules/evilportal'
_DATA_PATH = f'{_MODULE_PATH}/data'
_INCLUDE_PATH = f'{_MODULE_PATH}/includes'
_PORTAL_PATH = f'/root/portals'
# CONSTANTS


class PackageJob(OpkgJob):

    def _configure_lighttpd(self):
        pass

    def do_work(self, logger: logging.Logger) -> bool:
        return_value = super().do_work(logger)

        if return_value and self.install:
            self._configure_lighttpd()

        return return_value


def _deactivate_portal(name: str) -> bool:
    # return false if the portal is not active

    if not os.path.exists(f'/www/{name}.ep'):
        module.logger.error(f'NO EP FILE FOUND: /www/{name}.ep')
        return False

    # return false if the portal doesn't exist
    if not os.path.exists(f'{_PORTAL_PATH}/{name}'):
        module.logger.error(f'COULD NOT FIND PORTAL: {_PORTAL_PATH}/{name}')
        return False

    # remove all associate portal file symbolic links
    for item in pathlib.Path(f'{_PORTAL_PATH}/{name}').iterdir():
        os.unlink(f'/www/{item.name}')

    # restore any files evil portal backed up
    for item in pathlib.Path(f'/www').iterdir():
        if item.name[-10:] == '.ep_backup':
            item.rename(item.name[:-10])

    return True


def _activate_portal(name: str) -> bool:
    # check if there is a currently active portal and deactive it.
    for item in pathlib.Path('/www').iterdir():
        if item.name[-3:] == '.ep':
            if not _deactivate_portal(item.name[:-3]):
                return False

    try:
        os.symlink(f'{_INCLUDE_PATH}/api', '/www/captiveportal')
    except FileExistsError:
        module.logger.warning('Portal API already exists under /www/captiveportal. This is probably not an issue.')

    for item in pathlib.Path(f'{_PORTAL_PATH}/{name}').iterdir():
        if os.path.exists(f'/www/{item.name}'):
            os.rename(f'/www/{item.name}', f'/www/{item.name}.ep_backup')
        os.symlink(str(item), f'/www/{item.name}')

    return True


def _check_portal_activate(name: str) -> bool:
    return os.path.exists(f'/www/{name}.ep')


def _disable_webserver_autostart() -> bool:
    return os.system('/etc/init.d/lighttpd disable') == 0


def _autostart_webserver() -> bool:
    return os.system('/etc/init.d/lighttpd enable') == 0


def _check_webserver_autostart() -> bool:
    return cmd.grep_output('ls /etc/rc.d/', 'lighttpd') != b''


def _stop_webserver() -> bool:
    return os.system('/etc/init.d/lighttpd stop') == 0


def _start_webserver() -> bool:
    return os.system('/etc/init.d/lighttpd start') == 1


def _check_webserver_running() -> bool:
    return cmd.check_for_process('lighttpd')


def _stop_evilportal() -> bool:
    pass


def _start_evilportal() -> bool:
    pass


def _check_evilportal_running() -> bool:
    return cmd.grep_output('iptables -t nat -L PREROUTING', '172.16.42.1') != b''


def _enable_autostart() -> bool:
    pass


def _disable_autostart() -> bool:
    pass


def _check_autostart() -> bool:
    return cmd.grep_output('ls /etc/rc.d/', 'evilportal') != b''


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


def _get_portal_info(portal_path, portal_name) -> dict:
    if not os.path.exists(f'{portal_path}/{portal_name}.ep'):
        return {}

    with open(f'{portal_path}/{portal_name}.ep', 'r') as f:
        return json.load(f)


def _file_is_deletable(name: str) -> bool:
    if name[-3:] == '.ep':
        return False
    else:
        return name not in ['MyPortal.php', 'default.php', 'helper.php', 'index.php']


def _get_file_content(file_path: str) -> str:
    path = pathlib.Path(file_path)

    if not path.exists() or not path.is_file():
        raise FileNotFoundError()

    with open(str(path), 'r') as f:
        return f.read()


def _get_directory_content(dir_path: str) -> List[dict]:
    directory = pathlib.Path(dir_path)

    if not directory.exists():
        raise FileNotFoundError()
    elif not directory.is_dir():
        raise NotADirectoryError()

    return [
        {
            'name': item.name,
            'path': str(item),
            'size': item.lstat().st_size,
            'permissions': oct(item.lstat().st_mode)[-3:],
            'directory': item.is_dir(),
            'deletable': _file_is_deletable(item.name)
        }
        for item in sorted(directory.iterdir(), key=lambda i: not i.is_dir())
    ]


def _create_portal_folders():
    if not os.path.isdir(f'{_DATA_PATH}/portals'):
        os.mkdir(f'{_DATA_PATH}/portals')

    if not os.path.isdir(f'{_PORTAL_PATH}'):
        os.mkdir(f'{_PORTAL_PATH}')


@module.handles_action('authorize_client')
def authorize_client(request: Request) -> Tuple[bool, str]:
    pass


@module.handles_action('remove_client_from_list')
def remove_client_from_list(request: Request) -> Tuple[bool, str]:
    pass


@module.handles_action('add_client_to_list')
def add_client_to_list(request: Request) -> Tuple[bool, str]:
    pass


@module.handles_action('status')
def status(request: Request) -> Tuple[bool, dict]:
    return True, {
        'running': _check_evilportal_running() and _check_webserver_running(),
        "start_on_boot": _check_autostart()
    }


@module.handles_action('toggle_autostart')
def toggle_autostart(request: Request) -> Tuple[bool, str]:
    if _check_autostart():
        _disable_autostart()
        return True, 'Autostart disabled.'
    else:
        _enable_autostart()
        return True, 'Autostart enabled'


@module.handles_action('toggle_evilportal')
def toggle_evilportal(request: Request) -> Tuple[bool, str]:
    if _check_evilportal_running():
        _stop_webserver()
        _stop_evilportal()
        return True, 'Evil Portal stopped.'
    else:
        _start_webserver()
        _start_evilportal()
        return True, 'Evil Portal started.'


@module.handles_action('toggle_portal')
def toggle_portal(request: Request) -> Tuple[bool, str]:
    if not _check_portal_activate(request.portal):
        if _activate_portal(request.portal):
            return True, 'Portal has been activated.'
        else:
            return False, 'Error activating portal.'
    else:
        if _deactivate_portal(request.portal):
            return True, 'Portal has been deactivated.'
        else:
            return False, 'Error deactivating portal.'


@module.handles_action('delete')
def delete(request: Request) -> Tuple[bool, str]:
    module.logger.debug(f'DELETING ITEM AT LOCATION: {request.file_path}')
    path = pathlib.Path(request.file_path)

    if not path.exists():
        return False, 'File does not exist.'

    if path.is_dir():
        _delete_directory_tree(path)
        path.rmdir()
    else:
        path.unlink()

    return True, 'File deleted.'


@module.handles_action('save_portal_rules')
def save_portal_rules(request: Request) -> Tuple[bool, str]:
    portal = request.portal
    new_rules = json.loads(request.rules)

    portal_info = _get_portal_info(f'{_PORTAL_PATH}/{portal}', portal)
    portal_type = portal_info.get('type', 'unknown')

    if portal_type != 'targeted':
        return False, 'Can not get rules for non-targeted portal.'

    portal_info['targeted_rules'] = new_rules

    with open(f'{_PORTAL_PATH}/{portal}/{portal}.ep', 'w') as f:
        json.dump(portal_info, f)

    return True, 'Portal rules updated.'


@module.handles_action('get_portal_rules')
def get_portal_rules(request: Request) -> Tuple[bool, dict]:
    portal = request.portal

    portal_info = _get_portal_info(f'{_PORTAL_PATH}/{portal}', portal)
    portal_type = portal_info.get('type', 'unknown')
    portal_rules = portal_info.get('targeted_rules', {})

    if portal_type != 'targeted':
        return False, 'Can not get rules for non-targeted portal.'

    return True, portal_rules


@module.handles_action('new_portal')
def new_portal(request: Request) -> Tuple[bool, str]:
    type_to_skeleton = {'basic': 'skeleton', 'targeted': 'targeted_skeleton'}
    name = request.name
    portal_type = request.type
    skeleton = type_to_skeleton.get(portal_type, 'skeleton')

    os.mkdir(f'{_PORTAL_PATH}/{name}')
    os.system(f'cp {_INCLUDE_PATH}/{skeleton}/* {_PORTAL_PATH}/{name}')
    os.system(f'cp {_INCLUDE_PATH}/{skeleton}/.* {_PORTAL_PATH}/{name}')
    os.system(f'mv {_PORTAL_PATH}/{name}/portal.info {_PORTAL_PATH}/{name}/{name}.ep')
    os.system(f'chmod +x {_PORTAL_PATH}/{name}/.enable')
    os.system(f'chmod +x {_PORTAL_PATH}/{name}/.disable')

    portal_info = _get_portal_info(f'{_PORTAL_PATH}/{name}', f'{name}')
    portal_info['name'] = name
    portal_info['type'] = portal_type

    with open(f'{_PORTAL_PATH}/{name}/{name}.ep', 'w') as f:
        json.dump(portal_info, f, indent=2)

    if portal_type == 'targeted':
        os.system(f"sed -i 's/\"portal_name_here\"/\"{name}\"/g' {_PORTAL_PATH}{name}/index.php")

    return True, 'Portal created successfully.'


@module.handles_action('save_file')
def save_file(request: Request) -> Tuple[bool, str]:
    with open(request.path, 'w') as f:
        f.write(request.content)

    return True, 'File saved.'


@module.handles_action('load_file')
def load_file(request: Request) -> Tuple[bool, str]:
    try:
        return True, _get_file_content(request.path)
    except Exception as e:
        module.logger.error(f'Exception occurred while reading file: {e}')
        return False, str(e)


@module.handles_action('load_directory')
def load_directory(request: Request) -> Tuple[bool, List[dict]]:
    return True, _get_directory_content(request.path)


@module.handles_action('list_portals')
def list_portals(request: Request) -> Tuple[bool, List[dict]]:
    module.logger.debug('Creating portal folder')
    _create_portal_folders()

    module.logger.debug('Listing directories')
    directories = [item for item in _get_directory_content(_PORTAL_PATH) if item.get('directory', False)]

    module.logger.debug('Building list')
    return True, [
        {
            'title': item['name'],
            'portal_type': _get_portal_info(item['path'], item['name']).get('type', 'basic'),
            'size': item['size'],
            'location': item['path'],
            'active': _check_portal_activate(item['name'])
        }
        for item in directories
    ]


@module.handles_action('manage_dependencies')
def manage_dependencies(request: Request) -> Tuple[bool, Dict[str, str]]:
    return True, {
        'job_id': manager.execute_job(PackageJob(_DEPENDENCIES, request.install))
    }


@module.handles_action('check_dependencies')
def check_dependencies(request: Request) -> Tuple[bool, bool]:
    return True, False not in [opkg.check_if_installed(package) for package in _DEPENDENCIES]


if __name__ == '__main__':
    module.start()
