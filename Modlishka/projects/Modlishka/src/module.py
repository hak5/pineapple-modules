#!/usr/bin/env python

import logging
import time
import os
import signal

from pineapple.modules import Module, Request

# CONSTANTS
_MODULE_PATH = '/pineapple/ui/modules/Modlishka'
_ASSETS_PATH = f'{_MODULE_PATH}/assets'
_MODLISHKA_BIN = f'{_ASSETS_PATH}/proxy_mipsle'
_MODLISHKA_LOG = '/tmp/modlishka.log'
_CONFIG_FILE = f'{_ASSETS_PATH}/config.json'
_DNS_CONFIG_FILE = '/etc/dnsmasq.conf'
_PID_FILE = '/tmp/modlishka_pid'
module = Module('Modlishka', logging.DEBUG)

@module.handles_action('is_running')
def is_running(request: Request):
    return os.path.isfile(_PID_FILE)

@module.handles_action('get_config')
def get_config(request: Request):
    with open(_CONFIG_FILE, "r") as fp:
        return fp.read()
    return ''

@module.handles_action('set_config')
def set_config(request: Request):
    with open(_CONFIG_FILE, "w") as fp:
        fp.write(request.data)
        return "modlishka config file was updated"
    return "Error setting config file"

@module.handles_action('get_dns_config')
def get_dns_config(request: Request):
    with open(_DNS_CONFIG_FILE, "r") as fp:
        return fp.read()
    return ''

@module.handles_action('set_dns_config')
def set_dns_config(request: Request):
    with open(_DNS_CONFIG_FILE, "w") as fp:
        fp.write(request.data)
        return "dnsmask config was set"
    return "Error setting dnsmask config"

@module.handles_action('get_log')
def get_log(request: Request):
    if os.path.isfile(_MODLISHKA_LOG):
        with open(_MODLISHKA_LOG, "r") as fp:
            return fp.read()
    else:
        return "Modlishka not running"

@module.handles_action('run_modlishka')
def run_modlishka(request: Request):
    os.system('service dnsmasq restart')
    time.sleep(2) # this is to make sure dnsmasq has restarted properly
    pid = os.fork()
    if pid > 0:
        with open(_PID_FILE, "w") as fp:
            fp.write(str(pid))
        os.system(f'{_MODLISHKA_BIN} -debug -config {_CONFIG_FILE} &> {_MODLISHKA_LOG}')
    return pid

@module.handles_action('stop_modlishka')
def stop_modlishka(request: Request):
    pid = -1
    with open(_PID_FILE, "r") as fp:
        pid = int(fp.read())
    if pid > 0:
        os.system(f'kill {pid}')
        return "modlishka was stopped"
    return "Error: couldn't stop modlishka"

if __name__ == "__main__":
    module.start()
