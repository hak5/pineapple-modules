#!/usr/bin/env python3

import logging

from pineapple.modules import Module, Request
import json
import os


module = Module('MACInfo', logging.DEBUG)

OUI_FILE = '/etc/pineapple/ouis'
ONLINE_URL = 'https://macvendors.co/api/'

@module.on_start()
def on_start():
    module.logger.debug("Started")
    print("lmfao")
    os.system("mkdir -p /tmp/modules")

@module.handles_action('check_mac_online')
def check_mac_online(request: Request):
    mac = request.user_input.upper()
    module.logger.debug(mac)
    curl_out = os.system(f"curl {ONLINE_URL}/{mac}/JSON")
    output_json = json.loads(curl_out)
    module.logger.debug(type(output_json))
    for (k, v) in output_json.items():
        print("Key" + k)
        print("Value:" + str(v))
        return(k,v)

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
