#!/usr/bin/env python3

import logging

from pineapple.modules import Module, Request

import json
import urllib.request
import re

module = Module('locate', logging.DEBUG)

API_LINK = f"https://ipwhois.app/json/"
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
        module.logger.debug(f"{API_LINK}{ip}")
        response = urllib.request.urlopen(f"{API_LINK}/{ip}")
        data = response.read()
        output_json = json.loads(data)
        module.logger.debug(output_json)
        lookup_ip = output_json['ip']
        city = output_json['city']
        region = output_json['region']
        country = output_json['country']
        country_capital = output_json['country_capital']
        timezone = output_json['timezone_name']
        country_flag = output_json['country_flag']
        country_phone = output_json['country_phone']
        longitude = output_json['longitude']
        latitude = output_json['latitude']
        coordinates = f"{latitude} / {longitude}"
        country_neighbours = output_json['country_neighbours']
        org = output_json['org']

        return {'lookup_ip':lookup_ip,'city':city,'region':region,
                'country':country,'country_capital':country_capital,
                'timezone':timezone, 'country_flag':country_flag,
                'country_phone':country_phone,'coordinates':coordinates,'org':org,'country_neighbours':country_neighbours}
    else:
        module.logger.debug("Not a valid IP address!")
        return "Not a valid IP address!", False

if __name__ == "__main__":
    module.start()
