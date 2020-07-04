#!/usr/bin/env python3

from logging import Logger
import logging
import subprocess
from typing import Tuple, Any
import os

from pineapple.modules import Module, Request
from pineapple.jobs import Job, JobManager
import pineapple.helpers.command_helpers as cmd

module = Module('Sniffer', logging.DEBUG)
job_manager = JobManager('Sniffer', logging.DEBUG, module=module)


class SnifferDaemonJob(Job[bool]):

    def __init__(self, interface: str = 'br-lan'):
        super().__init__()
        self.interface = interface

    def do_work(self, logger: Logger) -> bool:
        error_file = '/tmp/sniffererrors.log'
        subprocess.call(['sniffer', self.interface], stderr=open(error_file, 'w'))
        return True


def _check_websocket_job() -> bool:
    try:
        from libsniffer.websocket_publisher import WebsocketPublisher
    except ImportError as e:
        return False, 'Unable to import WebsocketPublisher.'

    for jid, runner in job_manager.jobs.items():
        if isinstance(runner.job, WebsocketPublisher):
            if runner.job.is_complete:
                job_manager.remove_job(jid)
                return False
            else:
                return True

    return False


def _stop_websocket_server() -> bool:
    try:
        from libsniffer.websocket_publisher import WebsocketPublisher
    except ImportError as e:
        return False, 'Unable to import WebsocketPublisher.'

    for jid, runner in job_manager.jobs.items():
        if isinstance(runner.job, WebsocketPublisher):
            runner.job.running = False

    return not _check_websocket_job()


@module.handles_action('status')
def status(request: Request) -> Tuple[bool, dict]:
    return True, False not in [
        cmd.check_for_process('sniffer'),
        _check_websocket_job()
    ]


@module.handles_action('toggle')
def toggle(request: Request) -> Tuple[bool, str]:
    try:
        from libsniffer.websocket_publisher import WebsocketPublisher
    except ImportError as e:
        return False, 'Unable to import WebsocketPublisher.'

    if request.enable:
        if not cmd.check_for_process('sniffer'):
            job_manager.execute_job(SnifferDaemonJob())
        if not _check_websocket_job():
            job_manager.execute_job(WebsocketPublisher())

        return True, 'started'
    else:
        if False in [os.system('killall -9 sniffer') == 0, _stop_websocket_server()]:
            return False, 'Unable to stop sniffer service'
        else:
            return True, 'Sniffer service stopped'


@module.handles_action('setup')
def setup(request: Request) -> Tuple[bool, str]:
    if os.path.exists('/usr/lib/pineapple/libsniffer'):
        return True, 'libsniffer exists'
    else:
        os.symlink('/pineapple/ui/modules/Sniffer/assets/libsniffer', '/usr/lib/pineapple/libsniffer')
        return True, 'Symlink created.'


if __name__ == '__main__':
    module.start()
