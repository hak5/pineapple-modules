#!/usr/bin/env python3

import logging

from pineapple.modules import Module, Request
import json
import os
import urllib.request


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
    response = urllib.request.urlopen(f'{ONLINE_URL}/34:46:EC:09:F3:3B/JSON')
    data = response.read()
    output_json = json.loads(data)
    jsonData = output_json["result"]
    for (k, v) in jsonData.items():
        module.logger.debug("Key:" + k)
        module.logger.debug("Value" + str(v))
        return(v)

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
