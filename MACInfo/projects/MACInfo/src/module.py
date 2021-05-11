#!/usr/bin/env python3

import logging

from pineapple.modules import Module, Request
import json
import os


module = Module('MACInfo', logging.DEBUG)

OUI_FILE = '/etc/pineapple/ouis'

@module.on_start()
def on_start():
    module.logger.debug("Started")
    print("lmfao")
    os.system("mkdir -p /tmp/modules")

@module.handles_action('check_mac')
def check_mac(request: Request):
    module.logger.debug("Opening file")
    with open(OUI_FILE) as f:
        OUIS = json.load(f)
        mac = request.user_input.upper()
        module.logger.debug("User inputted: " + mac)

        strip_mac = mac.replace(':','')
        module.logger.debug(strip_mac[:6])
        new_mac = strip_mac[:6]
        for (k, v) in OUIS.items():
            if new_mac in k:
                module.logger.debug(strip_mac + " " + v)
                return(v)

if __name__ == '__main__':
    module.start()
