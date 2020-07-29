#!/usr/bin/env python3

import logging
import os
import subprocess
from logging import Logger
from time import sleep

from pineapple.jobs.job import TResult
from pineapple.modules import Module, Request
from pineapple.jobs import JobManager, Job

module = Module('httpeek', logging.DEBUG)
job_manager = JobManager('httpeek', logging.DEBUG, module=module)


class SnifferJob(Job[bool]):

    def __init__(self):
        super().__init__()
        self.proc = None

    def do_work(self, logger: Logger) -> TResult:
        logger.debug('Starting sniffer handler...')
        self.proc = subprocess.Popen(['python3', 'sniffer_handler.py'], cwd='/pineapple/modules/httpeek/assets/')

        while True:
            sleep(0.5)
            value = self.proc.poll()
            if value is not None:
                logger.debug(f'Proc returned value {value}')
                break

        logger.debug('SnifferJob completed.')
        return True

    def stop(self):
        os.system('killall -9 sniffer')
        self.proc.kill()


def _check_sniffer_job() -> bool:
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


@module.on_shutdown()
def _stop_sniffer_job(signal: int = None) -> bool:
    for jid, runner in job_manager.jobs.items():
        if isinstance(runner.job, SnifferJob):
            runner.job.stop()

    return not _check_sniffer_job()


@module.handles_action('status')
def status(request: Request):
    return _check_sniffer_job()


@module.handles_action('toggle')
def toggle(request: Request):
    if request.enable:
        if not _check_sniffer_job():
            job_manager.execute_job(SnifferJob())
        return 'started'
    else:
        if not _stop_sniffer_job():
            return 'HTTPeek stopped'


if __name__ == '__main__':
    module.start()
