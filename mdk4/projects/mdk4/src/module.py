#!/usr/bin/env python3

import subprocess
import logging
import pathlib
import os
from datetime import datetime

from typing import List, Tuple, Optional, Union

from pineapple.helpers.opkg_helpers import OpkgJob
from pineapple.modules import Module, Request
from pineapple.helpers import network_helpers as net
from pineapple.helpers import opkg_helpers as opkg
import pineapple.helpers.notification_helpers as notifier
from pineapple.jobs import Job, JobManager


# CONSTANTS
_HISTORY_DIRECTORY_PATH = '/root/.mdk4'
_HISTORY_DIRECTORY = pathlib.Path(_HISTORY_DIRECTORY_PATH)
# CONSTANTS

module = Module('mdk4', logging.DEBUG)
job_manager = JobManager(name='mdk4', module=module, log_level=logging.DEBUG)


class Mdk4Job(Job[bool]):

    def __init__(self, command: List[str], file_name: str, input_interface: str, output_interface: str):
        super().__init__()
        self.file_name = file_name
        self.command = command
        self.mdk4_file = f'{_HISTORY_DIRECTORY_PATH}/{file_name}'
        self.input_interface = input_interface
        self.output_interface = output_interface
        self.monitor_input_iface = None
        self.monitor_output_iface = None


    def _stop_monitor_mode(self):
        if self.monitor_input_iface:
            os.system(f'airmon-ng stop {self.monitor_input_iface}')
        if self.monitor_output_iface:
            os.system(f'airmon-ng stop {self.monitor_output_iface}')

    def do_work(self, logger: logging.Logger) -> bool:
        logger.debug('mdk4 job started.')

        output_file = open(self.mdk4_file, 'w')

        if self.input_interface and self.input_interface != '' and self.input_interface[-3:] != 'mon':
            logger.debug(f'starting monitor mode on interface {self.input_interface}')
            if os.system(f'airmon-ng start {self.input_interface}') == 0:
                for index, substr in enumerate(self.command):
                    if substr == self.input_interface:
                        self.command[index] = f'{self.input_interface}mon'
                        self.monitor_input_iface = f'{self.input_interface}mon'
            else:
                self.error = 'Error starting monitor mode for input interface.'
                return False

        if self.output_interface and self.output_interface != '' and self.output_interface[-3:] != 'mon':
            logger.debug(f'starting monitor mode on interface {self.output_interface}')
            if os.system(f'airmon-ng start {self.output_interface}') == 0:
                for index, substr in enumerate(self.command):
                    if substr == self.output_interface:
                        self.command[index] = f'{self.output_interface}mon'
                        self.monitor_output_iface = f'{self.output_interface}mon'
            else:
                self.error = 'Error starting monitor mode for output interface.'
                return False

        logger.debug(f'Calling mdk4 and writing output to {self.mdk4_file}')
        subprocess.call(self.command, stdout=output_file, stderr=output_file)
        logger.debug('Mdk4 Completed.')

        self._stop_monitor_mode()

        return True

    def stop(self):
        os.system('killall -9 mdk4')
        self._stop_monitor_mode()


def _get_last_background_job() -> dict:
    last_job_id: Optional[str] = None
    last_job_type: Optional[str] = None
    last_job_info: Optional[str] = None

    if len(job_manager.jobs) > 0:
        last_job_id = list(job_manager.jobs.keys())[-1]
        last_job = job_manager.get_job(last_job_id, remove_if_complete=False)
        if type(last_job) is Mdk4Job:
            last_job_type = 'mdk4'
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
        module.send_notification('MDK4 finished installing.', notifier.INFO)


@module.on_start()
def _make_history_directory():
    if not _HISTORY_DIRECTORY.exists():
        _HISTORY_DIRECTORY.mkdir(parents=True)


@module.on_shutdown()
def stop_mdk4(signal: int = None) -> Union[str, Tuple[str, bool]]:
    if len(list(filter(lambda job_runner: job_runner.running is True, job_manager.jobs.values()))) > 0:
        if os.system('killall -9 mdk4') != 0:
            return 'Error stopping Mdk4.', False

    return 'Mdk4 stopped.'


@module.handles_action('start')
def start(request: Request):
    command = request.command.split(' ')

    filename = f"{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}"
    job_id = job_manager.execute_job(Mdk4Job(command, filename, request.input_iface, request.output_iface))

    return {
        'job_id': job_id,
        'output_file': filename
    }


@module.handles_action('stop')
def stop(request: Request):
    return stop_mdk4()


@module.handles_action('load_history')
def load_history(request: Request):
    return [item.name for item in _HISTORY_DIRECTORY.iterdir() if item.is_file()]


@module.handles_action('load_output')
def load_output(request: Request):
    output_path = f'{_HISTORY_DIRECTORY_PATH}/{request.output_file}'
    if not os.path.exists(output_path):
        return 'Could not find scan output.', False

    with open(output_path, 'r') as f:
        return f.read()


@module.handles_action('delete_result')
def delete_result(request: Request):
    output_path = pathlib.Path(f'{_HISTORY_DIRECTORY_PATH}/{request.output_file}')
    if output_path.exists() and output_path.is_file():
        output_path.unlink()

    return True


@module.handles_action('clear_history')
def clear_history(request: Request):
    for item in _HISTORY_DIRECTORY.iterdir():
        if item.is_file():
            item.unlink()

    return True


@module.handles_action('check_dependencies')
def check_dependencies(request: Request):
    return opkg.check_if_installed('mdk4', module.logger)


@module.handles_action('manage_dependencies')
def manage_dependencies(request: Request):
    return {
        'job_id': job_manager.execute_job(OpkgJob('mdk4', request.install), callbacks=[_notify_dependencies_finished])
    }


@module.handles_action('startup')
def startup(request: Request):
    return {
        'has_dependencies': opkg.check_if_installed('mdk4', module.logger),
        'interfaces': net.get_interfaces(),
        'last_job': _get_last_background_job()
    }


if __name__ == '__main__':
    module.start()
