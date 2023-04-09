#!/usr/bin/env python3

import logging
import os
import subprocess
from pineapple.modules import Module, Request

module = Module('BlackIP', logging.DEBUG)

addresses_4 = []
addresses_6 = []

@module.handles_action("init")
def init(request):
	try:
		blacklist = str(os.popen("ipset list").read())
		if not "Name: blacklist" in blacklist:
			subprocess.run(["ipset", "create", "blacklist", "hash:ip", "hashsize", "4096"])
			subprocess.run(["ipset", "create", "blacklist6", "hash:net", "hashsize", "4096", "family", "inet6"])
			subprocess.run(["iptables", "-I", "FORWARD", "-m", "set", "--match-set", "blacklist", "src", "-j", "DROP",])
			subprocess.run(["iptables", "-I", "FORWARD", "-m", "set", "--match-set", "blacklist6", "src", "-j", "DROP",])
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
def fetch_blacklist4(request):
	try:
		blacklist = ""
		for address in addresses_4:
			blacklist = blacklist + address + "\n"
		return blacklist
	except Exception as e:
		return "Error: " + str(e)

@module.handles_action("get6")
def fetch_blacklist6(request):
	try:
		blacklist = ""
		for address in addresses_6:
			blacklist = blacklist + address + "\n"
		return blacklist
	except Exception as e:
		return "Error: " + str(e)

@module.handles_action("clear")
def clear_blacklist(request):
	addresses_4.clear()
	addresses_6.clear()
	return "ok"

@module.handles_action("update")
def update(request):
	try:
		blacklist = ""
		subprocess.run(["ipset", "flush", "blacklist"])
		subprocess.run(["ipset", "flush", "blacklist6"])

		for address in addresses_4:
			subprocess.run(["ipset", "add", "blacklist", address])
		for address in addresses_6:
			subprocess.run(["ipset", "add", "blacklist6", address])
		return "ok"
	except Exception as e:
		return "Error: " + str(e)

if __name__ == '__main__':
    module.start()