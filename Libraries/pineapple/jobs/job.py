from typing import TypeVar, Generic, Optional
from logging import Logger
import abc

TResult = TypeVar('TResult')


class Job(Generic[TResult]):

    def __init__(self):
        self.is_complete: bool = False
        self.result: Optional[TResult] = None
        self.error: Optional[str] = None

    @property
    def was_successful(self) -> bool:
        """
        Checks if the job complete without an error.
        If the job has not completed or if it complete with no errors return True.
        If the job completed with an error then return False.
        :return: True if the job completed without an error, otherwise False
        """
        return self.error is None and self.is_complete

    @abc.abstractmethod
    def do_work(self, logger: Logger) -> TResult:
        """
        Override this method and implement a long running job.
        This function should return whatever the result of the work is.

        :param logger: An instance of a logger that may be used to provide insight.
        :return: The result of the work.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def stop(self):
        """
        Override this method and implement a way to stop the running jub.
        :return:
        """
        raise NotImplementedError()
