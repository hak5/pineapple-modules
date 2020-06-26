from typing import Dict, Optional, List, Callable
from uuid import uuid4

from pineapple.jobs.job import Job
from pineapple.jobs.job_runner import JobRunner
from pineapple.logger import *


class JobManager:

    def __init__(self, name: str, log_level: int = logging.ERROR):
        self.name = name
        self.logger = get_logger(name, log_level)
        self.jobs: Dict[str, JobRunner] = {}

    def get_job(self, job_id: str, remove_if_complete: bool = True) -> Optional[Job]:
        """
        Attempt to get a job by its id. If the job_id doesn't exist then None is returned.
        If `remove_if_complete` is True the job will be deleted from memory only if it is completed.
        This is the default behavior to prevent JobManager from tacking up unnecessary memory.

        :param job_id: The id of the job to find.
        :param remove_if_complete: True to delete the job from memory after its complete. (Default: True)
        :return: an instance of Job if found, else None
        """
        job_runner = self.jobs.get(job_id)

        if not job_runner:
            self.logger.debug(f'No job found matching id {job_id}.')
            return None

        job = job_runner.job

        if remove_if_complete and job.is_complete:
            self.logger.debug(f'Removing completed job: {job_id}.')
            self.remove_job(job_id)

        return job

    def prune_completed_jobs(self):
        """
        Removes all completed jobs from memory.
        """
        self.logger.debug('Pruning jobs...')

        running_jobs: Dict[str, JobRunner] = {}
        current_jobs = len(self.jobs)

        for job_id, job in self.jobs:
            if job.is_complete:
                self.remove_job(job_id)

        self.logger.debug(f'Pruned {current_jobs - len(running_jobs)} jobs.')

    def remove_job(self, job_id: str):
        """
        Remove a job from memory based on its id.
        This will remove the job regardless of its completion status.
        :param job_id: The id of the job to delete.
        :return:
        """
        del self.jobs[job_id]
        self.logger.debug(f'Removed job {job_id}.')

    def execute_job(self, job: Job, callbacks: List[Callable[[Job], None]] = None) -> str:
        """
        Assign an id to a job and execute it in a background thread.
        The id will be returned and the job can be tracked by calling `get_job` and providing it the id.
        :param job: an instance of Job to start running.
        :param callbacks: An optional list of functions that take `job` as a parameter to be called when completed.
                          These will be called regardless if `job` raises an exception or not.
        :return: The id of the running job.
        """
        job_id = str(uuid4())
        self.logger.debug(f'Assign job the id: {job_id}')

        job_runner = JobRunner(job, self.logger, callbacks)
        self.jobs[job_id] = job_runner

        self.logger.debug('Starting job...')
        job_runner.setDaemon(True)
        job_runner.start()
        self.logger.debug('Job started!')

        return job_id
