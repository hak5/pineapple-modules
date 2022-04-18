#!/usr/bin/env python3

from typing import Dict, Tuple, List, Union, Optional
import json
import subprocess
import logging
import pathlib
import tarfile
import os

from pineapple.modules import Module, Request
from pineapple.jobs import JobManager
from pineapple.helpers.opkg_helpers import OpkgJob
import pineapple.helpers.command_helpers as cmd
import pineapple.helpers.opkg_helpers as opkg


module = Module('evilportal', logging.DEBUG)
manager = JobManager('evilportal', log_level=logging.DEBUG, module=module)

# CONSTANTS
_DEPENDENCIES = ['php7-mod-curl', 'php7-mod-json', 'php7-fpm', 'php7-mod-sqlite3', 'php7', 'nginx']
_MODULE_PATH = '/pineapple/ui/modules/evilportal'
_ASSETS_PATH = f'{_MODULE_PATH}/assets'
_PORTAL_PATH = f'/root/portals'
_CLIENTS_FILE = f'/tmp/EVILPORTAL_CLIENTS.txt'
# CONSTANTS


def _post_install(job: OpkgJob):
    if not job.install:
        return
    elif not job.was_successful:
        module.logger.debug('Installation job did not finish successfully so post install is returning.')
        return

    os.system(f'cp {_ASSETS_PATH}/configs/php.ini /etc/php.ini')
    os.system(f'cp {_ASSETS_PATH}/configs/php7-fpm /etc/init.d/php7-fpm')
    os.system(f'cp {_ASSETS_PATH}/configs/nginx.conf /etc/nginx/nginx.conf')
    os.system(f'cp {_ASSETS_PATH}/configs/php7-fpm.conf /etc/php7-fpm.conf')
    os.system(f'cp {_ASSETS_PATH}/configs/www.conf /etc/php7-fpm.d/www.conf')

    os.system('/etc/init.d/php7-fpm stop')
    os.system('/etc/init.d/nginx stop')
    os.system(f'cp {_ASSETS_PATH}/evilportal.sh /etc/init.d/evilportal')
    os.system('chmod +x /etc/init.d/evilportal')

    os.system('uci set nginx.global.uci_enable=false')
    os.system('uci commit')


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
        if os.path.exists(f'/www/{item.name}'):
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
        os.symlink(f'{_ASSETS_PATH}/api', '/www/captiveportal')
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
    return os.system('/etc/init.d/nginx disable') == 0 and os.system('/etc/init.d/php7-fpm disable') == 0


def _autostart_webserver() -> bool:
    return os.system('/etc/init.d/nginx enable') == 0 and os.system('/etc/init.d/php7-fpm enable') == 0


def _check_webserver_autostart() -> bool:
    return cmd.grep_output('ls /etc/rc.d/', 'nginx') != b'' and cmd.grep_output('ls /etc/rc.d/', 'php7-fpm')


def _stop_webserver() -> bool:
    if not _check_webserver_running():
        return True

    return os.system('/etc/init.d/nginx stop') == 0 and os.system('/etc/init.d/php7-fpm stop') == 0


def _start_webserver() -> bool:
    if _check_webserver_running():
        return True

    nginx = subprocess.run(['/etc/init.d/nginx', 'start'], capture_output=True)
    module.logger.debug(f'NGINX START STDOUT: {nginx.stdout}')
    module.logger.debug(f'NGINX START SERROUT: {nginx.stderr}')

    return os.system('/etc/init.d/php7-fpm start') == 1


def _check_webserver_running() -> bool:
    return cmd.check_for_process('nginx') and cmd.check_for_process('php-fpm')


def _stop_evilportal() -> bool:
    if not _check_evilportal_running():
        return True

    if os.path.exists(_CLIENTS_FILE):
        with open(_CLIENTS_FILE, 'r') as f:
            for line in f.readlines():
                _revoke_client(line)

        os.unlink(_CLIENTS_FILE)

    # os.system('iptables -t nat -D PREROUTING -i br-lan -p tcp --dport 80 -j DNAT --to-destination 172.16.42.1:80')
    # os.system('iptables -D INPUT -p tcp --dport 53 -j ACCEPT')
    # os.system('iptables -D INPUT -j DROP')
    # os.system('iptables -t nat -D PREROUTING -i br-lan -p tcp --dport 443 -j DNAT --to-destination 172.16.42.1:80')

    os.system('/etc/init.d/evilportal stop')

    return not _check_evilportal_running()


def _start_evilportal() -> bool:
    if _check_evilportal_running():
        return True

    # delete client racking file if it exists.
    if os.path.exists(_CLIENTS_FILE):
        os.unlink(_CLIENTS_FILE)

    os.system('/etc/init.d/evilportal start')

    if os.path.exists(f'{_ASSETS_PATH}/permanentclients.txt'):
        with open(f'{_ASSETS_PATH}/permanentclients.txt') as f:
            for line in f.readlines():
                _authorize_client(line)

    return _check_evilportal_running()


def _check_evilportal_running() -> bool:
    return cmd.grep_output('iptables -t nat -L PREROUTING', '172.16.42.1') != b''


def _enable_autostart() -> bool:
    return os.system('/etc/init.d/evilportal enable') == 0


def _disable_autostart() -> bool:
    return os.system('/etc/init.d/evilportal disable') == 0


def _check_autostart() -> bool:
    return cmd.grep_output('ls /etc/rc.d/', 'evilportal') != b''


def _remove_client_from_file(client_ip: str, client_file: str):
    os.system(f'sed -i "s/{client_ip}//g" {client_file}')
    os.system(f'sed -i "/^$/d" {client_file}')


def _write_client_to_file(client_ip: str, client_file: str):
    with open(client_file, 'a') as f:
        f.write(f'{client_ip}\n')


def _authorize_client(ip: str):
    os.system(f'iptables -t nat -I PREROUTING -s {ip} -j ACCEPT')
    _write_client_to_file(ip, _CLIENTS_FILE)


def _revoke_client(ip: str):
    os.system(f'iptables -t nat -D PREROUTING -s {ip}')
    os.system(f'iptables -t nat -D PREROUTING -s {ip} -j ACCEPT')
    _remove_client_from_file(ip, _CLIENTS_FILE)


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


@module.on_start()
def create_portal_folders():
    if os.path.isfile(f'{_ASSETS_PATH}/evilportal.sh'):
        os.system(f'cp {_ASSETS_PATH}/evilportal.sh /etc/init.d/evilportal')
        os.chmod('/etc/init.d/evilportal', 755)

    if not os.path.isdir(f'{_ASSETS_PATH}/portals'):
        os.mkdir(f'{_ASSETS_PATH}/portals')

    if not os.path.isdir(f'{_PORTAL_PATH}'):
        os.mkdir(f'{_PORTAL_PATH}')


@module.handles_action('update_client_list')
def update_client_list(request: Request) -> Tuple[bool, str]:
    if request.list == 'allowedClients':
        if request.add:
            _authorize_client(request.client)
        else:
            _revoke_client(request.client)

    elif request.list == 'permanentClients':
        if request.add:
            _write_client_to_file(request.client, f'{_ASSETS_PATH}/permanentclients.txt')
        else:
            _remove_client_from_file(request.client, f'{_ASSETS_PATH}/permanentclients.txt')

    return 'List updated.'


@module.handles_action('status')
def status(request: Request):
    return {
        'running': _check_evilportal_running() and _check_webserver_running(),
        'webserver': _check_webserver_running(),
        "start_on_boot": _check_autostart()
    }


@module.handles_action('toggle_autostart')
def toggle_autostart(request: Request):
    if _check_autostart():
        _disable_autostart()
        return 'Autostart disabled.'
    else:
        _enable_autostart()
        return 'Autostart enabled'


@module.handles_action('toggle_webserver')
def toggle_webserver(request: Request):
    if _check_webserver_running():
        _stop_webserver()
    else:
        _start_webserver()

    return _check_webserver_running()


@module.handles_action('toggle_evilportal')
def toggle_evilportal(request: Request):
    if _check_evilportal_running():
        module.logger.debug('Stopping Evil Portal')
        if not _stop_evilportal():
            return 'Error stopping Evil Portal.', False
        return 'Evil Portal stopped.'
    else:
        module.logger.debug('Starting Evil Portal')
        if not _start_evilportal():
            return 'Error starting Evil Portal.', False

        return 'Evil Portal started.'


@module.handles_action('toggle_portal')
def toggle_portal(request: Request):
    if not _check_portal_activate(request.portal):
        if _activate_portal(request.portal):
            return 'Portal has been activated.'
        else:
            return 'Error activating portal.', False
    else:
        if _deactivate_portal(request.portal):
            return 'Portal has been deactivated.'
        else:
            return 'Error deactivating portal.', False


@module.handles_action('delete')
def delete(request: Request):
    module.logger.debug(f'DELETING ITEM AT LOCATION: {request.file_path}')
    path = pathlib.Path(request.file_path)

    if not path.exists():
        return 'File does not exist.', False

    if path.is_dir():
        _delete_directory_tree(path)
        path.rmdir()
    else:
        path.unlink()

    return 'File deleted.'


@module.handles_action('save_portal_rules')
def save_portal_rules(request: Request):
    portal = request.portal
    new_rules = request.rules

    portal_info = _get_portal_info(f'{_PORTAL_PATH}/{portal}', portal)
    portal_type = portal_info.get('type', 'unknown')

    if portal_type != 'targeted':
        return 'Can not get rules for non-targeted portal.', False

    portal_info['targeted_rules']['rules'] = new_rules

    with open(f'{_PORTAL_PATH}/{portal}/{portal}.ep', 'w') as f:
        json.dump(portal_info, f, indent=2)

    return 'Portal rules updated.'


@module.handles_action('get_portal_rules')
def get_portal_rules(request: Request):
    portal = request.portal

    portal_info = _get_portal_info(f'{_PORTAL_PATH}/{portal}', portal)
    portal_type = portal_info.get('type', 'unknown')
    portal_rules = portal_info.get('targeted_rules', {}).get('rules', {})

    if portal_type != 'targeted':
        return 'Can not get rules for non-targeted portal.', False

    return portal_rules


@module.handles_action('new_portal')
def new_portal(request: Request):
    type_to_skeleton = {'basic': 'skeleton', 'targeted': 'targeted_skeleton'}
    name = request.name.title().replace(' ', '')
    portal_type = request.type
    skeleton = type_to_skeleton.get(portal_type, 'skeleton')

    os.mkdir(f'{_PORTAL_PATH}/{name}')
    os.system(f'cp {_ASSETS_PATH}/{skeleton}/* {_PORTAL_PATH}/{name}')
    os.system(f'cp {_ASSETS_PATH}/{skeleton}/.* {_PORTAL_PATH}/{name}')
    os.system(f'mv {_PORTAL_PATH}/{name}/portalinfo.json {_PORTAL_PATH}/{name}/{name}.ep')
    os.system(f'chmod +x {_PORTAL_PATH}/{name}/.enable')
    os.system(f'chmod +x {_PORTAL_PATH}/{name}/.disable')

    portal_info = _get_portal_info(f'{_PORTAL_PATH}/{name}', f'{name}')
    portal_info['name'] = name
    portal_info['type'] = portal_type

    with open(f'{_PORTAL_PATH}/{name}/{name}.ep', 'w') as f:
        json.dump(portal_info, f, indent=2)

    if portal_type == 'targeted':
        os.system(f"sed -i 's/\"portal_name_here\"/\"{name}\"/g' {_PORTAL_PATH}/{name}/index.php")

    return 'Portal created successfully.'


@module.handles_action('archive_portal')
def archive_portal(request: Request):
    name = request.portal
    portal_path = pathlib.Path(f'{_PORTAL_PATH}/{name}')

    if not portal_path.is_dir():
        return 'A portal with the given name does not exist.', False

    with tarfile.open(f'/tmp/{name}.tar.gz', 'w:gz') as tar:
        tar.add(str(portal_path), portal_path.name)

    return f'/tmp/{name}.tar.gz'


@module.handles_action('save_file')
def save_file(request: Request):
    with open(request.path, 'w') as f:
        f.write(request.content)

    return 'File saved.'


@module.handles_action('load_file')
def load_file(request: Request):
    try:
        return _get_file_content(request.path)
    except Exception as e:
        module.logger.error(f'Exception occurred while reading file: {e}')
        return str(e), False


@module.handles_action('load_directory')
def load_directory(request: Request):
    return _get_directory_content(request.path)


@module.handles_action('list_portals')
def list_portals(request: Request):
    module.logger.debug('Creating portal folder')
    create_portal_folders()

    module.logger.debug('Listing directories')
    directories = [item for item in _get_directory_content(_PORTAL_PATH) if item.get('directory', False)]

    module.logger.debug('Building list')
    return [
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
def manage_dependencies(request: Request):
    if not request.install and _check_evilportal_running():
        _stop_evilportal()

    return {
        'job_id': manager.execute_job(OpkgJob(_DEPENDENCIES, request.install), [_post_install])
    }


@module.handles_action('check_dependencies')
def check_dependencies(request: Request):
    opkg_job_id: Optional[str] = None

    if len(manager.jobs) >= 1:
        for job_id, runner in manager.jobs.items():
            if isinstance(runner.job, OpkgJob) and not runner.job.is_complete:
                opkg_job_id = job_id
                break

    return {
        'installed': False not in [opkg.check_if_installed(package) for package in _DEPENDENCIES],
        'installing': opkg_job_id is not None,
        'job_id': opkg_job_id
    }


if __name__ == '__main__':
    module.start()
