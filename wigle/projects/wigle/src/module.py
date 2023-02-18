#!/usr/bin/env python3

import os
import json
import urllib.request
import urllib.parse
import logging
from pineapple.modules import Module, Request
import pineapple.helpers.notification_helpers as notifier

module = Module('wigle', logging.DEBUG)

@module.handles_action('search')
def search_db(request):
    try:
        with open("modules/wigle/wigle.key", "r") as file:
            auth_token = file.read()

        req = urllib.request.Request("https://api.wigle.net/api/v2/network/search?onlymine=false&freenet=false&paynet=false&resultsPerPage=1&country=" + urllib.parse.quote(request.user_cc.upper()) + "&city=" + urllib.parse.quote(request.user_city.title()) + "&ssid=" + urllib.parse.quote(request.user_ssid) + "&netid=" + urllib.parse.quote(request.user_mac), headers={"authorization": "Basic " + auth_token})
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
        resp_dict = json.loads(data)

        if resp_dict.get("success") == True:
            result = resp_dict.get("results")[0]
            return {"SSID":str(result.get("ssid")),"Channel":str(result.get("channel")),"Encryption":str(result.get("encryption")).upper(),"MAC":str(result.get("netid")).upper(),"DHCP":str(result.get("dhcp")),"Country":str(result.get("country")),"City":str(result.get("city")),"Road":str(result.get("road")),"Latitude":str(result.get("trilat")),"Longitude":str(result.get("trilong")),"total":resp_dict.get("totalResults"),"Message":"Total results: " + str(resp_dict.get("totalResults")),"Link":"https://wigle.net/search?country=" + request.user_cc.upper() + "&ssid=" + request.user_ssid + "&netid=" + request.user_mac}
        else:
            return {"Message":str(resp_dict.get("message")).upper()}
    except Exception as e:
        if str(e) == "list index out of range":
            return {"Message":"Total results: " + str(resp_dict.get("totalResults"))}
        else:
            return {"Message":"Error: " + str(e)}

@module.handles_action('check')
def check_api_token(request):
    try:
        if os.path.getsize("modules/wigle/wigle.key") == 0:
            return "Key not specified"
        else:
            return "Key specified"
    except Exception as e:
        return "Key not specified: " + str(e)

@module.handles_action('save')
def save_api_token(request):
    try:
        with open("modules/wigle/wigle.key", "w") as file:
            file.write(request.user_key)
        return "Key saved"
    except Exception as e:
        return "Key not saved: " + str(e)


if __name__ == '__main__':
    module.start()