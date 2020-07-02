#!/usr/bin/env python3
from logging import Logger
import logging
import subprocess
from typing import Tuple

from pineapple.modules import Module, Request
from pineapple.jobs import Job, JobManager


module = Module('sniffer', logging.DEBUG)
job_manager = JobManager('sniffer', logging.DEBUG)


class SnifferJob(Job[bool]):

    def __init__(self, interface: str = 'br-lan'):
        super().__init__()
        self.interface = interface

    def do_work(self, logger: Logger) -> bool:
        error_file = '/tmp/sniffererrors.log'
        subprocess.call(['sniffer', self.interface], stderr=open(error_file, 'w'))
        return True


def check_running():
    pass


@module.handles_action('start')
def start(request: Request) -> Tuple[bool, str]:
    job_manager.execute_job(SnifferJob())


if __name__ == '__main__':
    module.start()
