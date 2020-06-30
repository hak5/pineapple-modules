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
_DEPENDENCIES = ['php7-mod-curl', 'php7-mod-json', 'php7-cgi', 'php7', 'lighttpd-mod-cgi', 'lighttpd']
_MODULE_PATH = '/pineapple/ui/modules/evilportal'
_DATA_PATH = f'{_MODULE_PATH}/data'
_INCLUDE_PATH = f'{_MODULE_PATH}/includes'
_PORTAL_PATH = f'/root/portals'
_CLIENTS_FILE = f'/tmp/EVILPORTAL_CLIENTS.txt'
# CONSTANTS


class PackageJob(OpkgJob):

    def _configure_lighttpd(self):
        with open('/etc/lighttpd/conf.d/30-cgi.conf', 'w') as f:
            f.write(
                '''
server.modules += ( "mod_cgi" )
cgi.assign = ( ".pl"  => "/usr/bin/perl",
               ".cgi" => "/usr/bin/perl",
               ".rb"  => "/usr/bin/ruby",
               ".erb" => "/usr/bin/eruby",
               ".py"  => "/usr/bin/python",
               ".php" => "/usr/bin/php-cgi" )
                '''
            )
        os.system('/etc/init.d/lighttpd stop')
        os.system('/etc/init.d/lighttpd start')

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
    if not _check_webserver_running():
        return True

    return os.system('/etc/init.d/lighttpd stop') == 0


def _start_webserver() -> bool:
    if _check_webserver_running():
        return True

    return os.system('/etc/init.d/lighttpd start') == 1


def _check_webserver_running() -> bool:
    return cmd.check_for_process('lighttpd')


def _stop_evilportal() -> bool:
    if not _check_evilportal_running():
        return True

    with open(_CLIENTS_FILE) as f:
        for line in f.readlines():
            _revoke_client(line)

    os.unlink(_CLIENTS_FILE)

    os.system('iptables -t nat -D PREROUTING -i br-lan -p tcp --dport 80 -j DNAT --to-destination 172.16.42.1:80')
    os.system('iptables -D INPUT -p tcp --dport 53 -j ACCEPT')
    os.system('iptables -D INPUT -j DROP')
    os.system('iptables -t nat -D PREROUTING -i br-lan -p tcp --dport 443 -j DNAT --to-destination 172.16.42.1:80')

    return not _check_evilportal_running()


def _start_evilportal() -> bool:
    if _check_evilportal_running():
        return True

    # delete client racking file if it exists.
    if os.path.exists(_CLIENTS_FILE):
        os.unlink(_CLIENTS_FILE)

    os.system(f'cp {_DATA_PATH}/allowed.txt {_CLIENTS_FILE}')
    os.system('echo 1 > /proc/sys/net/ipv4/ip_forward')
    os.system(f'ln -s {_INCLUDE_PATH}/api /www/captiveportal')

    # iptables
    os.system('iptables -A INPUT -s 172.16.42.0/24 -j DROP')
    os.system('iptables -A OUTPUT -s 172.16.42.0/24 -j DROP')
    os.system('iptables -A INPUT -s 172.16.42.0/24 -p udp --dport 53 -j ACCEPT')

    # allow the pineapple
    os.system('iptables -A INPUT -s 172.16.42.1 -j ACCEPT')
    os.system('iptables -A OUTPUT -s 172.16.42.1 -j ACCEPT')

    # drop rules
    os.system('iptables -t nat -A PREROUTING -i br-lan -p tcp --dport 443 -j DNAT --to-destination 172.16.42.1:80')
    os.system('iptables -t nat -A PREROUTING -i br-lan -p tcp --dport 80 -j DNAT --to-destination 172.16.42.1:80')
    os.system('iptables -t nat -A POSTROUTING -j MASQUERADE')

    with open(_CLIENTS_FILE) as f:
        for line in f.readlines():
            _authorize_client(line)

    return _check_evilportal_running()


def _check_evilportal_running() -> bool:
    return cmd.grep_output('iptables -t nat -L PREROUTING', '172.16.42.1') != b''


def _enable_autostart() -> bool:
    pass


def _disable_autostart() -> bool:
    pass


def _check_autostart() -> bool:
    return cmd.grep_output('ls /etc/rc.d/', 'evilportal') != b''


def _authorize_client(ip: str) -> bool:
    pass


def _revoke_client(ip: str) -> bool:
    pass


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
        if not item.name[-3:] == '.ep' and not item.name[:1] == '.'
    ]


def _create_portal_folders():
    if not os.path.isdir(f'{_DATA_PATH}/portals'):
        os.mkdir(f'{_DATA_PATH}/portals')

    if not os.path.isdir(f'{_PORTAL_PATH}'):
        os.mkdir(f'{_PORTAL_PATH}')


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
        if False in [_stop_webserver(), _stop_evilportal()]:
            return False, 'Error stopping Evil Portal.'
        return True, 'Evil Portal stopped.'
    else:
        if False in [_start_webserver(), _start_evilportal()]:
            return False, 'Error starting Evil Portal.'

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
    new_rules = request.rules

    portal_info = _get_portal_info(f'{_PORTAL_PATH}/{portal}', portal)
    portal_type = portal_info.get('type', 'unknown')

    if portal_type != 'targeted':
        return False, 'Can not get rules for non-targeted portal.'

    portal_info['targeted_rules']['rules'] = new_rules

    with open(f'{_PORTAL_PATH}/{portal}/{portal}.ep', 'w') as f:
        json.dump(portal_info, f, indent=2)

    return True, 'Portal rules updated.'


@module.handles_action('get_portal_rules')
def get_portal_rules(request: Request) -> Tuple[bool, dict]:
    portal = request.portal

    portal_info = _get_portal_info(f'{_PORTAL_PATH}/{portal}', portal)
    portal_type = portal_info.get('type', 'unknown')
    portal_rules = portal_info.get('targeted_rules', {}).get('rules', {})

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
    os.system(f'mv {_PORTAL_PATH}/{name}/portalinfo.json {_PORTAL_PATH}/{name}/{name}.ep')
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
    if not request.install and _check_evilportal_running():
        _stop_evilportal()

    return True, {
        'job_id': manager.execute_job(PackageJob(_DEPENDENCIES, request.install))
    }


@module.handles_action('check_dependencies')
def check_dependencies(request: Request) -> Tuple[bool, bool]:
    return True, False not in [opkg.check_if_installed(package) for package in _DEPENDENCIES]


if __name__ == '__main__':
    module.start()
