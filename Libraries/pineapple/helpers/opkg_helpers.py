from logging import Logger
from typing import Optional, Tuple
import subprocess

from pineapple.helpers.helpers import check_for_internet
from pineapple.jobs.job import Job, TResult


def update_repository(logger: Optional[Logger] = None) -> Tuple[bool, str]:
    """
    Update the opkg package repository.
    :param logger: An optional instance of logger to log output from opkg as debug.
    :return: True if the update was successful, False if it was not.
    """
    if not check_for_internet(logger=logger):
        return False, 'Could not connect to internet'

    out = subprocess.run(['opkg', 'update'])

    if logger:
        logger.debug(out.stdout)

    # return out.returncode == 0  # opkg can't currently resolve the hak5 repo so it always fails.
    return True, 'Success'


def check_if_installed(package: str, logger: Optional[Logger] = None) -> bool:
    """
    Check if a package is already installed via opkg.
    :param package: The name of the package to search for.
    :param logger: An optional instance of logger to log output from opkg as debug.
    :return: True if the package is installed, False if it is not.
    """
    out = subprocess.run(['opkg', 'status', package], capture_output=True)

    if logger:
        logger.debug(out.stdout)

    return out.stdout != b'' and out.returncode == 0


def install_dependency(package: str, logger: Optional[Logger] = None) -> [bool, str]:
    """
    Install a package via opkg if its not currently installed.
    :param package: The name of the package to install.
    :param logger: An optional instance of logger to log output from opkg as debug.
    :return: True if the package installed successfully, False if it did not.
    """
    if check_if_installed(package, logger):
        return True, 'Package is already installed'

    update_successful, msg = update_repository(logger)
    if not update_successful:
        return False, msg

    out = subprocess.run(['opkg', 'install', package], capture_output=True)

    if logger:
        logger.debug(out.stdout)

    is_installed = check_if_installed(package, logger)
    message = 'Package installed successfully' if is_installed else 'Unable to install package.'
    return is_installed, message


def uninstall_dependency(package: str, logger: Optional[Logger] = None) -> [bool, str]:
    """
    Uninstall a package via opkg if its currently installed.
    :param package: The name of the package to uninstall.
    :param logger: An optional instance of logger to log output from opkg as debug.
    :return: True if the package uninstalled successfully, False if it did not.
    """
    if not check_if_installed(package, logger):
        return True, 'Package is not installed'

    out = subprocess.run(['opkg', 'remove', package], capture_output=True)

    if logger:
        logger.debug(out.stdout)

    is_installed = check_if_installed(package, logger)
    message = 'Package uninstalled successfully' if not is_installed else 'Unable to uninstall package'
    return not is_installed, message


class OpkgJob(Job[bool]):
    """
    A job to be used with the background JobManager that installs or uninstalls dependencies.
    """

    def __init__(self, package: str, install: bool):
        """
        :param package: The name of the package to install
        :param install: True if installing the package, False if uninstalling.
        """
        super().__init__()
        self.package = package
        self.install = install

    def do_work(self, logger: Logger) -> bool:
        """
        If `self.install` is True:
            Call `install_dependency` and pass the package and logger to it.
            If the result of `install_dependency` is False then set `self.error` equal to the message from the call.
            return the True if `install_dependency` returned True, otherwise return False.

        If `self.install` is False:
            Call `uninstall_dependency` and pass the package and logger to it.
            If the result of `uninstall_dependency` is False then set `self.error` equal to the message from the call.
            return the True if `uninstall_dependency` returned True, otherwise return False

        :param logger: An instance of a logger to provide insight.
        :return: True if call there were no errors, otherwise False.
        """
        if self.install:
            success, msg = install_dependency(package=self.package, logger=logger)
            if not success:
                self.error = msg
            return success
        else:
            success, msg = uninstall_dependency(package=self.package, logger=logger)
            if not success:
                self.error = msg
            return success
