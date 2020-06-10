from typing import Callable, List
from threading import Thread
from logging import Logger

from pineapple.jobs.job import Job


class JobRunner(Thread):

    def __init__(self, job: Job, logger: Logger, callbacks: List[Callable[[Job], None]] = None):
        """
        :param job: An instance of Job to run on a background thread.
        :param logger: An instance of Logger to provide insight.
        :param callbacks: An optional list of functions that take `job` as a parameter to be called when completed.
                          These will be called regardless if `job` raises an exception or not.
        """
        super().__init__()
        self.logger = logger
        self.job: Job = job
        self.running: bool = False
        self._callbacks: List[Callable[[Job], None]] = callbacks if callbacks else list()

    def run(self):
        """
        Call the `do_work` method on `self.job` and assign the results to `self.job.result`.
        If an exception is raised by the `do_work` method, catch it and set `self.job.error` equal to it.
        After `do_work` finishes set `self.job.is_complete` equal to True.
        """
        self.running = True
        try:
            self.job.result = self.job.do_work(self.logger)
        except Exception as e:
            self.logger.error(f'Running job encountered a {type(e)} error: {e}')
            self.job.error = str(e)

        self.job.is_complete = True

        try:
            if isinstance(self._callbacks, list) and len(self._callbacks) > 0:
                for callback in self._callbacks:
                    callback(self.job)
        except Exception as e:
            self.logger.error(f'Callback failed with a {type(e)} error: {e}')

        self.running = False

    def stop(self):
        """
        Call the `stop` method on `self.job` if the job is running.
        :return:
        """
        if self.running:
            self.job.stop()
