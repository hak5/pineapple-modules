#!/usr/bin/env python3

import pathlib
import logging
import subprocess

import pineapple.helpers.opkg_helpers as opkg
import pineapple.helpers.notification_helpers as notifier

from datetime import datetime
from pineapple.jobs import Job, JobManager
from pineapple.modules import Module, Request
from pineapple.helpers.opkg_helpers import OpkgJob

# CONSTANTS

_LOGGING = logging.DEBUG

_OPKG_INSTALL_PYTHON3_PIP = 'python3-pip'

_PIP3_COMMAND = '/usr/bin/pip3'
_PIP3_INSTALL_ARGUMENT = 'install'
_PIP3_PACKAGE_ARGUMENT = 'speedtest-cli'

_SPEED_TEST_CLI_COMMAND = '/usr/bin/speedtest-cli'
_SPEED_TEST_CLI_ARGUMENT = '--no-pre-allocate'
_SPEED_TEST_CLI_COMMAND_PATHLIB = pathlib.Path(_SPEED_TEST_CLI_COMMAND)

_SPEED_TEST_CLI_OUTPUT_DIRECTORY = '/tmp/speedtest-cli'
_SPEED_TEST_CLI_OUTPUT_DIRECTORY_PATHLIB = pathlib.Path(_SPEED_TEST_CLI_OUTPUT_DIRECTORY)

_SPEED_TEST_CLI_OUTPUT_FILENAME = f"{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}.txt"
_SPEED_TEST_CLI_OUTPUT_PATH = f"{_SPEED_TEST_CLI_OUTPUT_DIRECTORY}/{_SPEED_TEST_CLI_OUTPUT_FILENAME}"

# OBJECTS

module = Module('speedtest', _LOGGING)

job_manager = JobManager(
    name='speedtest', 
    module=module, 
    log_level=_LOGGING
)

# CLASSES

class SpeedTestCliInstallJob(Job[bool]):

    def __init__(self, command: str, install_argument: str, package_argument: str):
        super().__init__()
        self.command = command
        self.install_argument = install_argument
        self.package_argument = package_argument

    def do_work(self, logger: logging.Logger) -> bool:
        subprocess.call([self.command, self.install_argument, self.package_argument])
        return True

class SpeedTestJob(Job[bool]):

    def __init__(self, command: str, argument: str, output_path: str):
        super().__init__()
        self.command = command
        self.argument = argument
        self.output_path = output_path

    def do_work(self, logger: logging.Logger) -> bool:
        output = open(self.output_path, 'w')
        subprocess.call([self.command, self.argument], stdout=output, stderr=output)
        return True

# EVENTS

@module.on_start()
def create_output_directory():
    if not _SPEED_TEST_CLI_OUTPUT_DIRECTORY_PATHLIB.exists():
        _SPEED_TEST_CLI_OUTPUT_DIRECTORY_PATHLIB.mkdir(parents=True)
        module.logger.debug('[+] speedtest-module : Output directory created')

@module.on_shutdown()
def delete_output_directory():
    for item in _SPEED_TEST_CLI_OUTPUT_DIRECTORY_PATHLIB.iterdir():
        if item.is_file():
            item.unlink()
    module.logger.debug('[+] speedtest-module : Output directory cleared')

# EXTRAS

def follow_with_the_installation_of_speedtest_cli(job: OpkgJob):
    if job.install and job.was_successful:
        module.logger.debug('[+] speedtest-module : python3-pip installed')
        job_manager.execute_job(SpeedTestCliInstallJob(_PIP3_COMMAND, _PIP3_INSTALL_ARGUMENT, _PIP3_PACKAGE_ARGUMENT), callbacks=[ notify_dependencies_installed ])


# NOTIFICATIONS

def notify_dependencies_installed(job: SpeedTestCliInstallJob):
    if not job.was_successful:
        module.send_notification(job.error, notifier.ERROR)
    else:
        module.send_notification('python3-pip and speedtest-cli installed', notifier.INFO)

def notify_speedtest_completed(job: SpeedTestJob):
    if not job.was_successful:
        module.send_notification(job.error, notifier.ERROR)
    else:
        module.send_notification('SpeedTest completed', notifier.INFO)


# HANDLES

@module.handles_action('check_dependencies')
def check_dependencies(request: Request):
    module.logger.debug('[+] speedtest-module : Check required dependencies')
    python3_pip_installed = opkg.check_if_installed(_OPKG_INSTALL_PYTHON3_PIP, module.logger)
    speedtest_cli_installed = _SPEED_TEST_CLI_COMMAND_PATHLIB.exists()
    return {
        'dependency_python3_pip': python3_pip_installed,
        'dependency_speedtest_cli': speedtest_cli_installed
    }

@module.handles_action('install_dependencies')
def install_dependencies(request: Request):
    module.logger.debug('[+] speedtest-module : Install required dependencies')
    job_id = job_manager.execute_job(OpkgJob(_OPKG_INSTALL_PYTHON3_PIP, True), callbacks=[ follow_with_the_installation_of_speedtest_cli ])
    return {
        'job_id': job_id
    }

# Duplicate code :(
@module.handles_action('poll_dependencies')
def poll_dependencies(request: Request):
    job_id = request.job_id
    is_complete = False
    if len(job_manager.jobs) >= 1:
        for job, runner in job_manager.jobs.items():
            if job == job_id and runner.job.is_complete:
                is_complete = True
                break
    return {
        'is_complete': is_complete
    }

@module.handles_action('start_speedtest')
def start_speedtest(request: Request):
    job_id = job_manager.execute_job(SpeedTestJob(_SPEED_TEST_CLI_COMMAND, _SPEED_TEST_CLI_ARGUMENT, _SPEED_TEST_CLI_OUTPUT_PATH), callbacks=[ notify_speedtest_completed ])
    return {
        'job_id': job_id,
        'output_file': _SPEED_TEST_CLI_OUTPUT_PATH
    }

@module.handles_action('poll_speedtest')
def poll_speedtest(request: Request):
    job_id = request.job_id
    is_complete = False
    if len(job_manager.jobs) >= 1:
        for job, runner in job_manager.jobs.items():
            if job == job_id and runner.job.is_complete:
                is_complete = True
                break
    return {
        'is_complete': is_complete
    }


@module.handles_action('output_speedtest')
def output_speedtest(request: Request):
    output_file = request.output_file;
    with open(output_file, 'r') as reader:
        return {
            'speedtest_output': reader.read()
        }

if __name__ == '__main__':
    module.start()