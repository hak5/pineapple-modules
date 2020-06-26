#!/usr/bin/env python3

import logging
from typing import Dict, Tuple

from pineapple.modules import Module, Request
from pineapple.jobs import JobManager
from pineapple.helpers.opkg_helpers import OpkgJob
import pineapple.helpers.opkg_helpers as opkg


module = Module('evilportal', logging.DEBUG)
manager = JobManager('evilportal', log_level=logging.DEBUG, module=module)

_DEPENDENCIES = ['php7', 'php7-cgi', 'lighttpd', 'lighttpd-mod-cgi']


class PackageJob(OpkgJob):

    def _configure_lighttpd(self):
        pass

    def do_work(self, logger: logging.Logger) -> bool:
        return_value = super().do_work(logger)

        if return_value and self.install:
            self._configure_lighttpd()

        return return_value


@module.handles_action('manage_dependencies')
def manage_dependencies(request: Request) -> Tuple[bool, Dict[str, str]]:
    return True, {
        'job_id': manager.execute_job(PackageJob(_DEPENDENCIES, request.install))
    }


@module.handles_action('check_dependencies')
def check_dependencies(request: Request) -> Tuple[bool, bool]:
    return True, False not in [opkg.check_if_installed(package) for package in _DEPENDENCIES]


if __name__ == '__main__':
    module.start()
