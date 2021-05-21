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
    os.system("mkdir -p /tmp/modules")

@module.handles_action('check_mac_online')
def check_mac_online(request: Request):
    mac = request.user_input.upper()
    strip_mac = mac.replace(' ','')
    if '-' in strip_mac:
        strip_mac = mac.replace('-',':')
    module.logger.debug(strip_mac)
    response = urllib.request.urlopen(f'{ONLINE_URL}/{strip_mac}/JSON')
    data = response.read()
    output_json = json.loads(data)
    jsonData = output_json["result"]
    company = jsonData.get('company')
    mac_prefix = jsonData.get('mac_prefix')
    maccountry = jsonData.get('country')
    if maccountry == None:
        maccountry = "Country not found"
    address = jsonData.get('address')
    start_hex = jsonData.get('start_hex')
    end_hex = jsonData.get('end_hex')
    mactype = jsonData.get('type')

    return{'company':company,'address':address,'maccountry':maccountry,'mac_prefix':mac_prefix,'start_hex':start_hex,'end_hex':end_hex,'mactype':mactype}

@module.handles_action('check_mac')
def check_mac(request: Request):
    module.logger.debug("Opening file")
    with open(OUI_FILE) as f:
        OUIS = json.load(f)
        mac = request.user_input.upper()
        module.logger.debug("User inputted: " + mac)
        strip_mac = mac.replace(' ','')
        if ':' in strip_mac:
            strip_mac = mac.replace(':','')
        elif '-' in strip_mac:
            strip_mac = mac.replace('-','')
        module.logger.debug(strip_mac[:6])
        new_mac = strip_mac[:6]
        company = OUIS.get(new_mac)
        return{'company':company}

if __name__ == '__main__':
    module.start()
