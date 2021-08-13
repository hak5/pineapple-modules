#!/usr/bin/env python3

from pineapple.modules import Module, Request
import json
import subprocess
import logging
from pineapple.jobs import Job,JobManager
import pathlib

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
        return file


if __name__ == "__main__":
    module.start()
