#!/usr/bin/env python3

from typing import Optional
from pineapple.modules import Module, Request
import json
import subprocess
import logging
from pineapple.jobs import Job,JobManager
import pathlib
from pineapple.helpers.opkg_helpers import OpkgJob
import pineapple.helpers.notification_helpers as notifier
import pineapple.helpers.opkg_helpers as opkg

module = Module('mtr', logging.DEBUG)
job_manager = JobManager(name="mtr",module=module,log_level=logging.DEBUG)

root_folder = "/root/.mtr"
json_file = f"{root_folder}/report.json"

class MTRJob(Job[bool]):
    def __init__(self,user_input: str):
        super().__init__()
        self.user_input = user_input
    def do_work(self,logger: logging.Logger) -> bool:
        logger.debug("MTR job started.")
        module.logger.debug(self.user_input)
        result = subprocess.check_output(["mtr", "-j", self.user_input], encoding='UTF-8')
        json_data = json.loads(result)
        with open(json_file,"w") as f:
            json.dump(json_data,f)
            module.logger.debug("Data written to file.")
        module.logger.debug("MTR has finished.")
        return True

    def stop(self):
        subprocess.call(["killall","-9","mtr"])

@module.on_start()
def make_root_directory():
    path = pathlib.Path(root_folder)

    if not path.exists():
        module.logger.debug('Creating mtr directory.')
        path.mkdir(parents=True)

@module.handles_action("startmtr")
def startmtr(request: Request):
    user_input = request.user_input
    job_id = job_manager.execute_job(MTRJob(user_input))
    return {'job_id':job_id}

@module.handles_action("load_output")
def load_output(request: Request):
    with open(json_file,"r") as f:
        file = json.load(f)
        file2 = file["report"]["hubs"]
        for k in file2:
            k['LossPerc'] = k.pop('Loss%')
        return file

def _notify_dependencies_finished(job: OpkgJob):
    if not job.was_successful:
        module.send_notification(job.error, notifier.ERROR)
    elif job.install:
        module.send_notification('MTR finished installing.', notifier.INFO)

@module.handles_action('rebind_last_job')
def rebind_last_job(request: Request):
    module.logger.debug('GETTING LAST BACKGROUND JOB')
    last_job_id: Optional[str] = None
    last_job_type: Optional[str] = None
    job_info: Optional[str] = None

    if len(job_manager.jobs) >= 1:
        last_job_id = list(job_manager.jobs.keys())[-1]
        if type(job_manager.jobs[last_job_id].job) is OpkgJob:
            last_job_type = 'opkg'
        else:
            last_job_type = 'unknown'

    module.logger.debug(
        'BACKGROUND: ' + json.dumps(({'job_id': last_job_id, 'job_type': last_job_type, 'job_info': job_info})))
    return {'job_id': last_job_id, 'job_type': last_job_type, 'job_info': job_info}

@module.handles_action('check_dependencies')
def check_dependencies(request: Request):
    return opkg.check_if_installed('mtr-json', module.logger)

@module.handles_action('manage_dependencies')
def manage_dependencies(request: Request):
    return {
        'job_id': job_manager.execute_job(OpkgJob('mtr-json', request.install), callbacks=[_notify_dependencies_finished])
    }


if __name__ == "__main__":
    module.start()
