from typing import Dict, Optional, List, Callable, Tuple, Union
from uuid import uuid4

from pineapple.modules.module import Module
from pineapple.modules.request import Request
from pineapple.jobs.job import Job
from pineapple.jobs.job_runner import JobRunner
from pineapple.logger import *


class JobManager:

    def __init__(self, name: str, log_level: int = logging.ERROR, module: Optional[Module] = None):
        """
        :param name: The name of the job manager.
        :param log_level: Optional level for logging. Default is ERROR
        :param module: Optional instance of Module. If given some action and shutdown handlers will be registered.
                       Checkout `_setup_with_module` for more details.
        """
        self.name = name
        self.logger = get_logger(name, log_level)
        self.jobs: Dict[str, JobRunner] = {}
        self._setup_with_module(module)

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

    def stop_job(self, job: Optional[Job] = None, job_id: Optional[str] = None):
        """
        Call the `stop` method on a job.
        Either an instance of the Job to stop or id of the job is expected.
        The job will not automatically be removed from memory on completion.

        :param job: An instance of Job
        :param job_id: The id of te job to stop
        """
        if not job and not job_id:
            raise Exception('A job or job_id is expected.')

        if not job:
            job = self.get_job(job_id, remove_if_complete=False)

        if isinstance(job, Job):
            job.stop()

    def _setup_with_module(self, module: Optional[Module]):
        """
        If module is not None and is an instance of Module then register the following action handlers:
            action: `poll_job` | handler: `self.poll_job`

        And register _on_module_shutdown as a shutdown handler.

        :param module: an instance of Module
        """
        if not module or not isinstance(module, Module):
            return

        module.register_action_handler('poll_job', self._poll_job)
        module.register_shutdown_handler(self._on_module_shutdown)

    def _on_module_shutdown(self, signal: int):
        """
        A shutdown handler to be registered is `self.module` is not None.
        This will stop all currently running jobs.

        :param signal: The signal given
        """
        for job_id, runner in self.jobs.items():
            self.stop_job(job_id=job_id)

    def _poll_job(self, request: Request) -> Union[dict, Tuple[str, bool]]:
        """
        A module action handler to be used for checking the status of a background job.
        The request object must contain string `job_id` which is used to lookup the running job.
        Optionally, the request can contain boolean `remove_if_complete`. If this is True then the job will
        be deleted from memory if it is completed. If this value is False then the job will remain until manually deleted.
        This default value is True.

        :param request: An instance of Request
        """
        job_id = request.__dict__.get('job_id')
        remove_if_complete = request.__dict__.get('remove_if_complete', True)

        if not job_id:
            return 'job_id was not found in request.', False

        job = self.get_job(job_id, remove_if_complete)

        if not job:
            return 'No job found by that id.', False

        return {'is_complete': job.is_complete, 'result': job.result, 'job_error': job.error}
