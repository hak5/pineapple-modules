#!/usr/bin/env python3

from pineapple.modules import Module, Request
import json
import subprocess
import logging

module = Module('mtr', logging.DEBUG)


@module.handles_action("startmtr")
def startmtr(request: Request):
    user_input = request.user_input
    module.logger.debug(user_input)
    result = subprocess.check_output(["mtr", "-j", user_input], encoding='UTF-8')
    string = json.loads(result)
    hubs = string["report"]["hubs"]
    return {'hubs':hubs}

if __name__ == "__main__":
    module.start()
