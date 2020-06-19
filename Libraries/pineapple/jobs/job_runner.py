from threading import Thread
from logging import Logger

from pineapple.jobs.job import Job


class JobRunner(Thread):

    def __init__(self, job: Job, logger: Logger):
        """
        :param job: An instance of Job to run on a background thread.
        :param logger: An instance of Logger to provide insight.
        """
        super().__init__()
        self.logger = logger
        self.job = job
        self.running: bool = False

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
        self.running = False
