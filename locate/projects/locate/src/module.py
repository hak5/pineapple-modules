#!/usr/bin/env python3

import logging

from pineapple.modules import Module, Request

import json
import urllib.request

module = Module('locate', logging.DEBUG)

API_LINK = f"https://ipwhois.app/json/"

@module.handles_action('locate_ip')
def locate_ip(request: Request):
    ip = request.user_input
    module.logger.debug(f"{ip} address is valid.")
    module.logger.debug(f"{API_LINK}{ip}")
    response = urllib.request.urlopen(f"{API_LINK}/{ip}")
    data = response.read()
    output_json = json.loads(data)
    if output_json['success'] == False:
        error_code = output_json['message']
        return error_code,False

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


if __name__ == "__main__":
    module.start()
