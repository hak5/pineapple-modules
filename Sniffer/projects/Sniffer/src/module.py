#!/usr/bin/env python3

import logging
from typing import Tuple
import os

from pineapple.modules import Module, Request
from pineapple.jobs import JobManager
import pineapple.helpers.command_helpers as cmd

module = Module('Sniffer', logging.DEBUG)
job_manager = JobManager('Sniffer', logging.DEBUG, module=module)


def _check_sniffer_job() -> bool:
    try:
        from libsniffer.sniffer_job import SnifferJob
    except ImportError as e:
        return False, 'Unable to import SnifferJob.'

    for jid, runner in job_manager.jobs.items():
        if isinstance(runner.job, SnifferJob):
            module.logger.debug(f'FOUND SNIFFER JOB: {jid}')
            if runner.job.is_complete:
                module.logger.debug(f'SNIFFER JOB IS COMPLETED!')
                job_manager.remove_job(jid)
                return False
            else:
                module.logger.debug(f'SNIFFER JOB IS STILL RUNNING!')
                return True

    return False


def _stop_sniffer_job() -> bool:
    try:
        from libsniffer.sniffer_job import SnifferJob
    except ImportError as e:
        return False, 'Unable to import SnifferJob.'

    for jid, runner in job_manager.jobs.items():
        if isinstance(runner.job, SnifferJob):
            runner.job.stop()

    return not _check_sniffer_job()


@module.handles_action('status')
def status(request: Request) -> Tuple[bool, bool]:
    return True, _check_sniffer_job()


@module.handles_action('toggle')
def toggle(request: Request) -> Tuple[bool, str]:
    try:
        from libsniffer.sniffer_job import SnifferJob
    except ImportError as e:
        return False, 'Unable to import WebsocketPublisher.'

    if request.enable:
        if not _check_sniffer_job():
            job_manager.execute_job(SnifferJob())
        return True, 'started'
    else:
        if not _stop_sniffer_job():
            return True, 'Sniffer stopped'


@module.handles_action('setup')
def setup(request: Request) -> Tuple[bool, str]:
    if os.path.exists('/usr/lib/pineapple/libsniffer'):
        return True, 'libsniffer exists'
    else:
        os.symlink('/pineapple/ui/modules/Sniffer/assets/libsniffer', '/usr/lib/pineapple/libsniffer')
        return True, 'Symlink created.'


if __name__ == '__main__':
    module.start()
