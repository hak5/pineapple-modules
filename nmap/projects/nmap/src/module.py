#!/usr/bin/env python3

from typing import Tuple, List
from datetime import datetime
import logging
import pathlib
import subprocess
import os

from pineapple.modules import Module, Request
from pineapple.jobs import Job, JobManager
from pineapple.helpers.opkg_helpers import OpkgJob
import pineapple.helpers.opkg_helpers as opkg


module = Module('nmap', logging.DEBUG)
job_manager = JobManager('nmap', logging.DEBUG)

history_directory_path = '/root/.nmap'
history_directory = pathlib.Path(history_directory_path)


class ScanJob(Job[bool]):

    def __init__(self, command: List[str], output_file: str):
        super().__init__()
        self.command = command
        self.output_file = output_file

    def do_work(self, logger: logging.Logger) -> bool:
        logger.debug('Scan job started.')
        output_file = open(self.output_file, 'w')

        logger.debug(f'Calling nmap and writing output to {self.output_file}')
        subprocess.call(self.command, stdout=output_file)

        logger.debug('Scan completed.')
        return True


def _make_history_directory():
    path = pathlib.Path(history_directory)

    if not path.exists():
        path.mkdir(parents=True)


@module.handles_action('check_background_job')
def check_background_job(request: Request) -> Tuple[bool, dict]:
    job = job_manager.get_job(request.job_id)

    if not job:
        return False, 'No job found by that id'

    return True, {'is_complete': job.is_complete, 'result': job.result, 'job_error': job.error}


@module.handles_action('check_dependencies')
def check_dependencies(request: Request) -> Tuple[bool, bool]:
    return True, opkg.check_if_installed('nmap', module.logger)


@module.handles_action('manage_dependencies')
def manage_dependencies(request: Request) -> Tuple[bool, dict]:
    _make_history_directory()
    return True, {'job_id': job_manager.execute_job(OpkgJob('nmap', request.install))}


@module.handles_action('start_scan')
def start_scan(request: Request) -> Tuple[bool, dict]:
    _make_history_directory()
    command = request.command.split(' ')

    filename = f"{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}"
    output_file = f'{history_directory_path}/{filename}'
    job_id = job_manager.execute_job(ScanJob(command, output_file))

    return True, {'job_id': job_id, 'output_file': filename}


@module.handles_action('stop_scan')
def stop_scan(request: Request) -> Tuple[bool, bool]:
    os.system('killall -9 nmap')
    return True, True


@module.handles_action('list_scan_history')
def list_scan_history(request: Request) -> Tuple[bool, List[str]]:
    _make_history_directory()

    return True, [item.name for item in history_directory.iterdir() if item.is_file()]


@module.handles_action('get_scan_output')
def get_scan_output(request: Request) -> Tuple[bool, str]:
    output_path = f'{history_directory_path}/{request.output_file}'
    if not os.path.exists(output_path):
        return False, 'Could not find scan output.'

    with open(output_path, 'r') as f:
        return True, f.read()


@module.handles_action('delete_result')
def delete_result(request: Request) -> Tuple[bool, bool]:
    output_path = pathlib.Path(f'{history_directory_path}/{request.output_file}')
    if output_path.exists() and output_path.is_file():
        output_path.unlink()

    return True, True


@module.handles_action('clear_scans')
def clear_scans(request: Request) -> Tuple[bool, bool]:
    for item in history_directory.iterdir():
        if item.is_file():
            item.unlink()

    return True, True


if __name__ == '__main__':
    module.start()
