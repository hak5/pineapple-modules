#!/usr/bin/env python3

import logging
import os
import subprocess
from pineapple.modules import Module, Request

module = Module('dnsspoof', logging.DEBUG)

@module.handles_action("backup")
def backup(request):
	try:
		if not os.path.exists('modules/dnsspoof/host-backup.txt'):
			with open("/etc/hosts", "r") as file:
				hosts = file.read()
			with open("modules/dnsspoof/host-backup.txt", "w+") as backup:
				backup.write(hosts)
		return "ok"
	except Exception as e:
		return "Error: " + str(e)

@module.handles_action("add")
def add_host(request):
	try:
		with open("/etc/hosts", "r") as file:
			hosts = file.read().replace("\n\n", "\n" + request.user_ip + " " + request.user_domain + "\n\n", 1)
		os.remove("/etc/hosts")
		with open("/etc/hosts", "w") as file:
			file.write(hosts)
		return "ok"
	except Exception as e:
		return "Error: " + str(e)

@module.handles_action("get")
def fetch_hosts(request):
	try:
		with open("/etc/hosts", "r") as file:
			hosts = file.read().partition("\n\n")[0]
		return hosts
	except:
		return "Error"

@module.handles_action("update")
def update_dns(request):
	try:
		subprocess.run(["killall", "dnsmasq", "&&", "/etc/init.d/dnsmasq", "start"])
		return "ok"
	except Exception as e:
		return "Error: " + str(e)

@module.handles_action("reset")
def reset_hosts(request):
	try:
		with open("modules/dnsspoof/host-backup.txt", "r") as backup:
			old = backup.read()
		with open("/etc/hosts", "w+") as file:
			file.write(old)
		return "ok"
	except Exception as e:
		return "Error: " + str(e)

if __name__ == '__main__':
    module.start()