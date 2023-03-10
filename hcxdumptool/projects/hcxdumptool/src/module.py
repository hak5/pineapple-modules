#!/usr/bin/env python3

import logging
import os
import pathlib
import subprocess
from datetime import datetime
from logging import Logger
from typing import List, Optional, Union, Tuple

from pineapple.modules import Module, Request
from pineapple.helpers.opkg_helpers import OpkgJob
from pineapple.helpers import opkg_helpers as opkg
import pineapple.helpers.notification_helpers as notifier
from pineapple.helpers import network_helpers as net
from pineapple.jobs import JobManager, Job


module = Module('hcxdumptool', logging.DEBUG)
job_manager = JobManager(name='hcxdumptool', module=module, log_level=logging.DEBUG)

PCAP_DIRECTORY_PATH = '/root/.hcxdumptool'
PCAP_DIRECTORY = pathlib.Path(PCAP_DIRECTORY_PATH)


class PcapJob(Job[bool]):

    def __init__(self, command: List[str], file_name: str):
        super().__init__()
        self.file_name = file_name
        self.command = command
        self.pcap_file = f'{PCAP_DIRECTORY_PATH}/{file_name}'
        self.proc = None

    def do_work(self, logger: Logger) -> bool:
        logger.debug('hcxdumptool job started.')
        output_file = open('/tmp/hcxdumptool.log', 'w')
        stderr_file = open('/tmp/hcxdumptool-err.log', 'w')

        logger.debug(f'Calling hcxdumptool and writing output to {self.pcap_file}')
        self.command += ['-o', self.pcap_file]
        subprocess.call(self.command, stdout=output_file, stderr=stderr_file)

        logger.debug('Scan completed.')

        return True

    def stop(self):
        os.system('killall -9 hcxdumptool')


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


def _notify_dependencies_finished(job: OpkgJob):
    if not job.was_successful:
        module.send_notification(job.error, notifier.ERROR)
    elif job.install:
        module.send_notification('hcxdumptool finished installing.', notifier.INFO)


@module.on_start()
def make_history_directory():
    path = pathlib.Path(PCAP_DIRECTORY_PATH)

    if not path.exists():
        path.mkdir(parents=True)


@module.on_shutdown()
def stop_hcxdumptool(signal: int = None):
    if len(list(filter(lambda job_runner: job_runner.running is True, job_manager.jobs.values()))) > 0:
        module.logger.debug('Stopping hcxdumptool.')
        os.system('killall -9 hcxdumptool')


@module.handles_action('check_dependencies')
def check_dependencies(request: Request):
    return opkg.check_if_installed('hcxdumptool', module.logger)


@module.handles_action('manage_dependencies')
def manage_dependencies(request: Request):
    return {'job_id': job_manager.execute_job(OpkgJob('hcxdumptool', request.install), callbacks=[_notify_dependencies_finished])}


@module.handles_action('start_capture')
def start_capture(request: Request):
    command = request.command.split(' ')

    filename = f"{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}.pcap"

    job_id = job_manager.execute_job(PcapJob(command, filename))
    return {'job_id': job_id, 'output_file': filename}


@module.handles_action('stop_capture')
def stop_capture(request: Request):
    stop_hcxdumptool()
    return True


@module.handles_action('list_capture_history')
def list_capture_history(request: Request):
    return [item.name for item in PCAP_DIRECTORY.iterdir() if item.is_file()]


@module.handles_action('get_capture_output')
def get_capture_output(request: Request):
    output_path = f'{PCAP_DIRECTORY_PATH}/{request.output_file}'
    if not os.path.exists(output_path):
        return 'Could not find scan output.', False

    with open(output_path, 'r') as f:
        return f.read()


@module.handles_action('get_log_content')
def get_log_content(request: Request):
    if not os.path.exists('/tmp/hcxdumptool.log'):
        return 'Could not find log output: /tmp/hcxdumptool.log', False

    with open('/tmp/hcxdumptool.log', 'r') as f:
        return f.read()


@module.handles_action('delete_capture')
def delete_capture(request: Request):
    output_path = pathlib.Path(f'{PCAP_DIRECTORY_PATH}/{request.output_file}')
    if output_path.exists() and output_path.is_file():
        output_path.unlink()

    return True


@module.handles_action('delete_all')
def delete_all(request: Request):
    for item in PCAP_DIRECTORY.iterdir():
        if item.is_file():
            item.unlink()

    return True


@module.handles_action('startup')
def startup(request: Request):
    return {
        'has_dependencies': opkg.check_if_installed('hcxdumptool', module.logger),
        'interfaces': net.get_interfaces(),
        'last_job': _get_last_background_job()
    }


if __name__ == '__main__':
    module.start()
