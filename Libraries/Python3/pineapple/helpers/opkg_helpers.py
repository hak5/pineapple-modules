from logging import Logger
from typing import Optional, Tuple, List, Union
import subprocess
import os

from pineapple.helpers.network_helpers import check_for_internet
from pineapple.jobs.job import Job


def update_repository(logger: Optional[Logger] = None) -> Tuple[bool, str]:
    """
    Update the opkg package repository.
    :param logger: An optional instance of logger to log output from opkg as debug.
    :return: True if the update was successful, False if it was not.
    """
    if not check_for_internet(logger=logger):
        return False, 'Could not connect to internet.'

    out = subprocess.run(['opkg', 'update'])

    if logger:
        logger.debug(out.stdout)

    if out.returncode == 0:
        return True, 'Success'
    else:
        return False, f'Opkg update failed with code {out.returncode}'


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


def install_dependency(package: str, logger: Optional[Logger] = None, skip_repo_update: bool = False) -> [bool, str]:
    """
    Install a package via opkg if its not currently installed.
    :param package: The name of the package to install.
    :param logger: An optional instance of logger to log output from opkg as debug.
    :param skip_repo_update: True to skip running `opkg update`. An internet connection will still be checked for.
    :return: True if the package installed successfully, False if it did not.
    """
    if check_if_installed(package, logger):
        return True, 'Package is already installed'

    if not skip_repo_update:
        update_successful, msg = update_repository(logger)
        if not update_successful:
            return False, msg
    else:
        has_internet = check_for_internet()
        if not has_internet:
            return False, 'Could not connect to internet.'

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

    def __init__(self, package: Union[str, List[str]], install: bool):
        """
        :param package: The name of the package or list of packages to be installed/uninstalled
        :param install: True if installing the package, False if uninstalling.
        """
        super().__init__()
        self.package: Union[str, List[str]] = package
        self.install = install

    def _install_or_remove(self, pkg: str, logger: Logger, skip_repo_update: bool = False) -> bool:
        """
        If `self.install` is True:
            Call `install_dependency` and pass the package and logger to it.
            If the result of `install_dependency` is False then set `self.error` equal to the message from the call.
            return the True if `install_dependency` returned True, otherwise return False.

        If `self.install` is False:
            Call `uninstall_dependency` and pass the package and logger to it.
            If the result of `uninstall_dependency` is False then set `self.error` equal to the message from the call.
            return the True if `uninstall_dependency` returned True, otherwise return False

        :param pkg: The name of the package to install/uninstall.
        :param logger: An instance of a logger to provide insight.
        :return: True if call there were no errors, otherwise False.
        :return:
        """
        if self.install:
            success, msg = install_dependency(package=pkg, logger=logger, skip_repo_update=skip_repo_update)
            if not success:
                if not self.error:
                    self.error = msg
                else:
                    self.error += f'{msg}\n'
            return success
        else:
            success, msg = uninstall_dependency(package=pkg, logger=logger)
            if not success:
                if not self.error:
                    self.error = msg
                else:
                    self.error += f'{msg}\n'
            return success

    def do_work(self, logger: Logger) -> bool:
        """
        If `self.package` is a List:
            Attempt to install each every package in the list. If a single package fails to install then this method
            will return False.

        :param logger: An instance of a logger to provide insight.
        :return: True if call there were no errors, otherwise False.
        """
        if isinstance(self.package, list):
            update_repository(logger)
            results = [self._install_or_remove(pkg, logger, True) for pkg in self.package]
            return False not in results
        elif isinstance(self.package, str):
            return self._install_or_remove(self.package, logger)
        else:
            raise TypeError(f'Package is expected to be a list of strings or a single string. Got {type(self.package)} instead.')

    def stop(self):
        """
        Kill the opkg process if it is running.
        :return:
        """
        if not self.is_complete:
            os.system('killall -9 opkg')
