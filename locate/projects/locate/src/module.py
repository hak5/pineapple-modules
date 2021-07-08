#!/usr/bin/env python3

import logging

from pineapple.modules import Module, Request

import json
import urllib.request
import re

module = Module('locate', logging.DEBUG)

API_LINK = f"https://ipapi.co/"
regex = "(([0-9]|[1-9][0-9]|1[0-9][0-9]|"\
        "2[0-4][0-9]|25[0-5])\\.){3}"\
        "([0-9]|[1-9][0-9]|1[0-9][0-9]|"\
        "2[0-4][0-9]|25[0-5])"

@module.on_start()
def on_start():
    global regex_ip
    regex_ip = re.compile(regex)

@module.handles_action('locate_ip')
def locate_ip(request: Request):
    ip = request.user_input
    if (re.search(regex_ip,ip)):
        module.logger.debug(f"{ip} address is valid.")
        module.logger.debug(f"{API_LINK}{ip}/json")
        response = urllib.request.urlopen(f"{API_LINK}/{ip}/json")
        data = response.read()
        output_json = json.loads(data)
        module.logger.debug(output_json)
        lookup_ip = output_json['ip']
        city = output_json['city']
        region = output_json['region']
        country = output_json['country']
        country_capital = output_json['country_capital']
        timezone = output_json['timezone']
        languages = output_json['languages']
        calling_code = output_json['country_calling_code']
        longitude = output_json['longitude']
        latitude = output_json['latitude']
        postal_code = output_json['postal']
        cordinates = f"{latitude} / {longitude}"
        org = output_json['org']

        return {'lookup_ip':lookup_ip,'city':city,'region':region,
                'country':country,'country_capital':country_capital,
                'timezone':timezone, 'languages':languages,
                'calling_code':calling_code,'cordinates':cordinates,'org':org,'postal':postal_code}
    else:
        module.logger.debug("Not a valid IP address!")
        return "Not a valid IP address!", False

if __name__ == "__main__":
    module.start()
