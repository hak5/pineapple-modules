#!/usr/bin/env python3

import logging
import os
import pathlib
import subprocess
from datetime import datetime
from logging import Logger
from typing import List, Tuple, Optional

from pineapple.modules import Module, Request
from pineapple.helpers.opkg_helpers import OpkgJob
from pineapple.helpers import opkg_helpers as opkg
from pineapple.helpers import network_helpers as net
from pineapple.jobs import JobManager, Job

module = Module('tcpdump', logging.DEBUG)
job_manager = JobManager('tcpdump', logging.DEBUG)

PCAP_DIRECTORY_PATH = '/root/.tcpdump'
PCAP_DIRECTORY = pathlib.Path(PCAP_DIRECTORY_PATH)


class PcapJob(Job[bool]):

    def __init__(self, command: List[str], file_name: str):
        super().__init__()
        self.file_name = file_name
        self.command = command
        self.pcap_file = f'{PCAP_DIRECTORY_PATH}/{file_name}'

    def do_work(self, logger: Logger) -> bool:
        logger.debug('tcpdump job started.')
        output_file = open(self.pcap_file, 'w')

        logger.debug(f'Calling nmap and writing output to {self.pcap_file}')
        subprocess.call(self.command, stdout=output_file)

        logger.debug('Scan completed.')
        return True


def _make_history_directory():
    path = pathlib.Path(PCAP_DIRECTORY_PATH)

    if not path.exists():
        path.mkdir(parents=True)


def _get_last_background_job() -> dict:
    last_job_id: Optional[str] = None
    last_job_type: Optional[str] = None
    last_job_info: Optional[str] = None

    if len(job_manager.jobs) > 0:
        last_job_id = list(job_manager.jobs.keys())[-1]
        last_job = job_manager.get_job(last_job_id, remove_if_complete=False)
        if type(last_job) is PcapJob:
            last_job_type = 'pcap'
            last_job_info = last_job.file_name
        elif type(last_job) is OpkgJob:
            last_job_type = 'opkg'
        else:
            last_job_type = 'unknown'

    return {
        'job_id': last_job_id,
        'job_type': last_job_type,
        'job_info': last_job_info
    }


@module.handles_action('check_background_job')
def check_background_job(request: Request) -> Tuple[bool, dict]:
    job = job_manager.get_job(request.job_id)

    if not job:
        return False, 'No job found by that id'

    return True, {'is_complete': job.is_complete, 'result': job.result, 'job_error': job.error}


@module.handles_action('check_dependencies')
def check_dependencies(request: Request) -> Tuple[bool, bool]:
    return True, opkg.check_if_installed('tcpdump', module.logger)


@module.handles_action('manage_dependencies')
def manage_dependencies(request: Request) -> Tuple[bool, dict]:
    _make_history_directory()
    return True, {'job_id': job_manager.execute_job(OpkgJob('tcpdump', request.install))}


@module.handles_action('start_capture')
def start_capture(request: Request) -> Tuple[bool, dict]:
    _make_history_directory()
    command = request.command.split(' ')

    filename = f"{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}"
    output_file = f'{PCAP_DIRECTORY_PATH}/{filename}'
    job_id = job_manager.execute_job(PcapJob(command, output_file))

    return True, {'job_id': job_id, 'output_file': filename}


@module.handles_action('stop_capture')
def stop_capture(request: Request):
    os.system('killall -9 tcpdump')
    return True, True


@module.handles_action('list_capture_history')
def list_capture_history(request: Request) -> Tuple[bool, List[str]]:
    _make_history_directory()

    return True, [item.name for item in PCAP_DIRECTORY.iterdir() if item.is_file()]


@module.handles_action('get_capture_output')
def get_capture_output(request: Request) -> Tuple[bool, str]:
    output_path = f'{PCAP_DIRECTORY_PATH}/{request.output_file}'
    if not os.path.exists(output_path):
        return False, 'Could not find scan output.'

    with open(output_path, 'r') as f:
        return True, f.read()


@module.handles_action('delete_capture')
def delete_capture(request: Request) -> Tuple[bool, bool]:
    output_path = pathlib.Path(f'{PCAP_DIRECTORY_PATH}/{request.output_file}')
    if output_path.exists() and output_path.is_file():
        output_path.unlink()

    return True, True


@module.handles_action('delete_all')
def delete_all(request: Request) -> Tuple[bool, bool]:
    for item in PCAP_DIRECTORY.iterdir():
        if item.is_file():
            item.unlink()

    return True, True


@module.handles_action('startup')
def startup(request: Request) -> Tuple[bool, dict]:
    return True, {
        'has_dependencies': opkg.check_if_installed('tcpdump', module.logger),
        'interfaces': net.get_interfaces(),
        'last_job': _get_last_background_job()
    }


if __name__ == '__main__':
    module.start()
