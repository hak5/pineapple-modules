#!/usr/bin/env python3
"""PineappleTAK module for the WiFi Pineapple Mark VII - back-end (connects it to a TAK Server).

The Pineapple UI page uses these actions to install and control the PineappleTAK
service (/root/pineappletak, /etc/init.d/pineappletak). Everything TAK-related is
done in PineappleTAK's own web console, which this page opens.
"""
import logging
import os
import shutil
import subprocess
import time

from pineapple.modules import Module, Request

module = Module('PineappleTAK', logging.WARNING)

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, 'assets', 'pineappletak')       # the service, shipped with the module
HOME = '/root/pineappletak'                                 # where the service runs
CONF = '/etc/pineappletak'
INIT = '/etc/init.d/pineappletak'
RUN = '/tmp/pineappletak'
LOG = '/tmp/pineappletak.log'
INSTALL_LOG = '/tmp/pineappletak-install.log'
# Your data inside the service folder: kept when the module is updated
KEEP = ('core/certs', 'core/geofences.txt', 'core/items.txt', 'core/overlays', 'core/tiles',
        'core/watch', 'core/web/auth', 'core/web/tls')

INIT_SCRIPT = """#!/bin/sh /etc/rc.common
# PineappleTAK - puts the WiFi Pineapple Mark VII on the TAK map (installed by the PineappleTAK module)
START=99
STOP=10
USE_PROCD=1

start_service() {
    procd_open_instance
    procd_set_param command /bin/bash /root/pineappletak/pineappletak.sh
    procd_set_param respawn 3600 15 5
    procd_set_param term_timeout 15
    procd_set_param stdout 0
    procd_set_param stderr 0
    procd_close_instance
}
"""


def sh(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode, p.stdout.decode('utf-8', 'replace')
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def first_line(path, default=''):
    try:
        with open(path) as fh:
            return fh.readline().strip()
    except OSError:
        return default


def conf(key, default=''):
    v = first_line(os.path.join(CONF, key))
    return v if v else default


def version_of(base):
    try:
        with open(os.path.join(base, 'pineappletak.sh'), errors='replace') as fh:
            for line in fh:
                if line.startswith('PTAK_VERSION='):
                    return line.split('=', 1)[1].strip().strip('"')
    except OSError:
        pass
    return ''


def installed():
    return os.path.isfile(os.path.join(HOME, 'pineappletak.sh')) and os.path.isfile(INIT)


def running():
    code, _ = sh([INIT, 'running']) if os.path.isfile(INIT) else (1, '')
    if code == 0:
        return True
    pid = first_line('/var/run/pineappletak.pid')
    return bool(pid) and os.path.exists('/proc/%s' % pid)


def enabled():
    code, _ = sh([INIT, 'enabled']) if os.path.isfile(INIT) else (1, '')
    return code == 0


def missing_packages():
    need = []
    if not shutil.which('bash'):
        need.append('bash')
    code, _ = sh(['python3', '-c', 'import sqlite3'])
    if code != 0:
        need.append('python3-sqlite3')
    if not os.path.exists('/etc/ssl/certs/ca-certificates.crt'):
        need.append('ca-bundle')                    # public CAs: many enrollment ports use one
    return need


def console_urls():
    port = conf('web_port', '8484')
    scheme = 'https' if conf('web_https') == '1' else 'http'
    ips = []
    code, out = sh(['uci', '-q', 'get', 'network.lan.ipaddr'])
    if code == 0 and out.strip():
        ips.append(out.strip().split('/')[0])
    listen = conf('web_listen', 'all')
    if listen == 'all':
        name = first_line('/proc/sys/kernel/hostname')
        if name and name != 'OpenWrt':
            ips.append(name)
    if listen in ('vpn', 'all'):                          # same choices as the console's "Listen on"
        _, out = sh(['ip', '-4', '-o', 'addr', 'show'])
        for line in out.splitlines():
            p = line.split()
            if len(p) > 3 and p[1] != 'lo' and (listen == 'all' or p[1] in ('wt0', 'wg0', 'tun0')):
                ips.append(p[3].split('/')[0])
    return ['%s://%s:%s' % (scheme, ip, port) for ip in dict.fromkeys(ips)] or ['%s://172.16.42.1:%s' % (scheme, port)]


@module.handles_action('status')
def status(request: Request):
    st = first_line(os.path.join(RUN, 'status')).split('|')
    gps = first_line(os.path.join(RUN, 'gps')).split()
    try:
        with open(LOG, errors='replace') as fh:
            log = fh.read().splitlines()[-12:]
    except OSError:
        log = []
    return {
        'installed': installed(),
        'module_version': version_of(ASSETS) if os.path.isdir(ASSETS) else '',
        'service_version': version_of(HOME) if os.path.isfile(os.path.join(HOME, 'pineappletak.sh')) else '',
        'running': running(),
        'enabled': enabled(),
        'password_set': os.path.getsize(os.path.join(HOME, 'core/web/auth')) > 0
        if os.path.isfile(os.path.join(HOME, 'core/web/auth')) else False,
        'configured': conf('configured') == '1',
        'setup_mode': os.path.exists(os.path.join(RUN, 'setup_mode')),
        'link': st[0] if st and st[0] else '',
        'last_report': st[1] if len(st) > 1 else '',
        'error': st[2] if len(st) > 2 else '',
        'callsign': conf('callsign'),
        'server': ('%s:%s (%s)' % (conf('host'), conf('port', '8089'), conf('proto', 'tls'))) if conf('host') else '',
        'gps': ('fix, %s satellites' % gps[7]) if gps and gps[0] == '1' else
               ('GPS on %s, no fix yet' % first_line(os.path.join(RUN, 'gps.dev')) if os.path.exists(os.path.join(RUN, 'gps.dev'))
                else ('manual position' if conf('manual_pos') else 'no GPS and no manual position')),
        'urls': console_urls(),
        'listen': conf('web_listen', 'all'),
        'port': conf('web_port', '8484'),
        'scheme': 'https' if conf('web_https') == '1' else 'http',
        'missing': missing_packages(),
        'log': log,
    }


@module.handles_action('install')
def install(request: Request):
    """Installs or updates the service from the module. Your settings and data are kept."""
    if not os.path.isdir(ASSETS):
        return 'The module is missing its service files - reinstall the module', False
    with open(INSTALL_LOG, 'w') as lg:
        need = missing_packages()
        if need:
            lg.write('opkg install %s\n' % ' '.join(need))
            lg.flush()
            code, out = sh(['opkg', 'update'], timeout=180)
            lg.write(out)
            code, out = sh(['opkg', 'install'] + need, timeout=300)
            lg.write(out)
            if missing_packages():
                return 'Could not install %s (internet needed) - see %s' % (', '.join(missing_packages()), INSTALL_LOG), False
        was_running = running()
        if was_running:
            sh([INIT, 'stop'], timeout=30)
        os.makedirs(HOME, exist_ok=True)
        keep = os.path.join('/tmp', 'pineappletak-keep')
        shutil.rmtree(keep, ignore_errors=True)
        for rel in KEEP:                                    # move your data aside...
            src = os.path.join(HOME, rel)
            if os.path.exists(src):
                dst = os.path.join(keep, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
        for name in os.listdir(HOME):                       # ...replace the code...
            p = os.path.join(HOME, name)
            shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
        for name in os.listdir(ASSETS):
            s, d = os.path.join(ASSETS, name), os.path.join(HOME, name)
            shutil.copytree(s, d) if os.path.isdir(s) else shutil.copy2(s, d)
        for rel in KEEP:                                    # ...and put your data back
            src = os.path.join(keep, rel)
            if os.path.exists(src):
                dst = os.path.join(HOME, rel)
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                elif os.path.exists(dst):
                    os.remove(dst)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
        shutil.rmtree(keep, ignore_errors=True)
        for root, _, files in os.walk(HOME):
            for f in files:
                if f.endswith('.sh') or root.endswith('/mk7/bin'):
                    os.chmod(os.path.join(root, f), 0o755)
        os.makedirs(os.path.join(HOME, 'core/certs'), mode=0o700, exist_ok=True)
        with open(INIT, 'w') as fh:
            fh.write(INIT_SCRIPT)
        os.chmod(INIT, 0o755)
        os.makedirs(CONF, exist_ok=True)
        if was_running:
            sh([INIT, 'start'])
    return 'PineappleTAK %s installed' % version_of(HOME)


@module.handles_action('set_password')
def set_password(request: Request):
    pw = str(getattr(request, 'password', ''))
    if len(pw) < 8:
        return 'Use at least 8 characters', False
    if not installed():
        return 'Install PineappleTAK first', False
    p = subprocess.run(['python3', '-B', os.path.join(HOME, 'core/web/pagertak_web.py'), '--hash-password'],
                       input=(pw + '\n').encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    h = p.stdout.decode().strip()
    if p.returncode != 0 or not h:
        return 'Could not set the password', False
    path = os.path.join(HOME, 'core/web/auth')
    with open(path + '.tmp', 'w') as fh:
        fh.write(h + '\n')
    os.chmod(path + '.tmp', 0o600)
    os.replace(path + '.tmp', path)
    return 'Console password set'


@module.handles_action('service')
def service(request: Request):
    """op: start | stop | restart | enable | disable"""
    op = str(getattr(request, 'op', ''))
    if op not in ('start', 'stop', 'restart', 'enable', 'disable'):
        return 'Unknown action', False
    if not installed():
        return 'Install PineappleTAK first', False
    if op in ('start', 'restart') and not status(request)['password_set']:
        return 'Set a console password first', False
    code, out = sh([INIT, op], timeout=40)
    if op in ('start', 'restart'):
        time.sleep(3)
        if not running():
            return 'PineappleTAK did not start - see the log below', False
    return {'start': 'Started', 'stop': 'Stopped', 'restart': 'Restarted',
            'enable': 'Starts when the Pineapple boots', 'disable': 'No longer starts at boot'}[op]


@module.handles_action('set_listen')
def set_listen(request: Request):
    """mode: all | vpn | usb - where the console can be reached. Restarts PineappleTAK if it is running."""
    mode = str(getattr(request, 'mode', ''))
    if mode not in ('all', 'vpn', 'usb'):
        return 'Unknown choice', False
    if not installed():
        return 'Install PineappleTAK first', False
    os.makedirs(CONF, exist_ok=True)
    with open(os.path.join(CONF, 'web_listen'), 'w') as fh:
        fh.write(mode + '\n')
    text = {'all': 'Console listens on all interfaces (host name, IP and USB)',
            'vpn': 'Console listens on USB + VPN only', 'usb': 'Console listens on the USB address only'}[mode]
    if running():
        sh([INIT, 'restart'], timeout=40)
        time.sleep(3)
        text += ' - PineappleTAK restarted'
    return text


@module.handles_action('uninstall')
def uninstall(request: Request):
    """Removes the service. keep_data=true keeps settings, certificates and loot."""
    if os.path.isfile(INIT):
        sh([INIT, 'stop'], timeout=30)
        sh([INIT, 'disable'])
        os.remove(INIT)
    if str(getattr(request, 'keep_data', 'true')).lower() in ('false', '0', 'no'):
        shutil.rmtree(HOME, ignore_errors=True)
        shutil.rmtree(CONF, ignore_errors=True)
        return 'PineappleTAK removed with its settings and certificates (loot kept in /root/loot/PineappleTAK)'
    for name in ('pineappletak.sh', 'mk7'):
        p = os.path.join(HOME, name)
        shutil.rmtree(p) if os.path.isdir(p) else (os.remove(p) if os.path.exists(p) else None)
    return 'PineappleTAK removed; settings, certificates and loot kept for a reinstall'


if __name__ == '__main__':
    module.start()
