#!/usr/bin/env python3

import logging
import os
import subprocess
from pineapple.modules import Module, Request

module = Module('DenyIP', logging.DEBUG)

addresses_4 = []
addresses_6 = []

@module.handles_action("init")
def init(request):
	try:
		denylist = str(os.popen("ipset list").read())
		if not "Name: denylist" in denylist:
			subprocess.run(["ipset", "create", "denylist", "hash:ip", "hashsize", "4096"])
			subprocess.run(["ipset", "create", "denylist6", "hash:net", "hashsize", "4096", "family", "inet6"])
			subprocess.run(["iptables", "-I", "FORWARD", "-m", "set", "--match-set", "denylist", "src", "-j", "DROP",])
			subprocess.run(["iptables", "-I", "FORWARD", "-m", "set", "--match-set", "denylist6", "src", "-j", "DROP",])
		return "ok"
	except Exception as e:
		return "Error: " + str(e)

@module.handles_action("add")
def add_ip(request):
	if request.user_ip == "":
		return "Please specify an IP address"
	elif request.user_type == "":
		return "Please specify IPv4 or IPv6"
	elif request.user_ip == "" and request.user_type == "":
		return "Please specify an IP address and IPv4 or IPv6"
	elif request.user_type == "4":
		addresses_4.append(request.user_ip)
		return "ok"
	elif request.user_type == "6":
		addresses_6.append(request.user_ip)
		return "ok"

@module.handles_action("get4")
def fetch_denylist4(request):
	try:
		denylist = ""
		for address in addresses_4:
			denylist = denylist + address + "\n"
		return denylist
	except Exception as e:
		return "Error: " + str(e)

@module.handles_action("get6")
def fetch_denylist6(request):
	try:
		denylist = ""
		for address in addresses_6:
			denylist = denylist + address + "\n"
		return denylist
	except Exception as e:
		return "Error: " + str(e)

@module.handles_action("clear")
def clear_denylist(request):
	addresses_4.clear()
	addresses_6.clear()
	return "ok"

@module.handles_action("update")
def update(request):
	try:
		denylist = ""
		subprocess.run(["ipset", "flush", "denylist"])
		subprocess.run(["ipset", "flush", "denylist6"])

		for address in addresses_4:
			subprocess.run(["ipset", "add", "denylist", address])
		for address in addresses_6:
			subprocess.run(["ipset", "add", "denylist6", address])
		return "ok"
	except Exception as e:
		return "Error: " + str(e)

if __name__ == '__main__':
    module.start()