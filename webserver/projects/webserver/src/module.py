import base64
import logging
import os
import json
import socket
import subprocess
import shutil
import threading
import uuid
from pineapple.modules import Module, Request

module = Module('webserver', logging.DEBUG)

SITES_PATH      = '/root/sites'
NGINX_AVAILABLE = '/etc/nginx/sites-available'
NGINX_ENABLED   = '/etc/nginx/sites-enabled'
ASSETS_PATH     = os.path.dirname(os.path.realpath(__file__)) + '/assets'
SKELETON_PATH   = ASSETS_PATH + '/skeleton'
TEMPLATES_PATH  = ASSETS_PATH + '/templates'
HOSTS_FILE      = '/etc/hosts'
HOSTS_START     = '# webserver-module-start'
HOSTS_END       = '# webserver-module-end'
PINEAPPLE_IP    = '172.16.42.1'
BOOT_FLAG       = '/root/.webserver/start_at_boot'
RC_LOCAL        = '/etc/rc.local'
RC_MARKER       = '# webserver-module'
RC_LINES = (
    'mkdir -p /tmp/modules',
    'PYTHONPATH=/usr/lib/pineapple python3 /pineapple/ui/modules/webserver/module.py >> /tmp/modules/webserver.log 2>&1 &',
    '/usr/sbin/nginx',
)

_jobs: dict = {}


# ─────────────────────────── Boot helpers ───────────────────────────────────

def _is_start_at_boot() -> bool:
    return os.path.exists(BOOT_FLAG)


def _set_start_at_boot(enabled: bool):
    os.makedirs(os.path.dirname(BOOT_FLAG), exist_ok=True)
    if enabled:
        open(BOOT_FLAG, 'w').close()
        _write_rc_local(True)
    else:
        if os.path.exists(BOOT_FLAG):
            os.remove(BOOT_FLAG)
        _write_rc_local(False)


def _write_rc_local(add: bool):
    try:
        with open(RC_LOCAL, 'r') as f:
            content = f.read()
    except Exception:
        content = '#!/bin/sh\nexit 0\n'

    lines = content.splitlines()
    clean, in_block = [], False
    for line in lines:
        if line.strip() == RC_MARKER + '-start':
            in_block = True; continue
        if line.strip() == RC_MARKER + '-end':
            in_block = False; continue
        if not in_block:
            clean.append(line)

    if add:
        insert_at = next((i for i, l in enumerate(clean) if l.strip() == 'exit 0'), len(clean))
        block = [RC_MARKER + '-start'] + list(RC_LINES) + [RC_MARKER + '-end', '']
        clean = clean[:insert_at] + block + clean[insert_at:]

    with open(RC_LOCAL, 'w') as f:
        f.write('\n'.join(clean) + '\n')


# ─────────────────────────── Dependency helpers ─────────────────────────────

def _nginx_installed() -> bool:
    return os.path.exists('/usr/sbin/nginx')


def _php_installed() -> bool:
    for p in ('/usr/bin/php-fpm7', '/usr/sbin/php-fpm7', '/usr/bin/php7-fpm'):
        if os.path.exists(p):
            return True
    return False


def _install_packages(job_id: str):
    try:
        subprocess.run(['opkg', 'update'], capture_output=True, timeout=120)
        result = subprocess.run(
            ['opkg', 'install', 'nginx', 'php7-fpm'],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            _jobs[job_id] = {'is_complete': True, 'job_error': None, 'payload': True}
        else:
            _jobs[job_id] = {'is_complete': True,
                             'job_error': result.stderr.strip() or 'opkg failed', 'payload': False}
    except subprocess.TimeoutExpired:
        _jobs[job_id] = {'is_complete': True, 'job_error': 'Installation timed out', 'payload': False}
    except Exception as e:
        _jobs[job_id] = {'is_complete': True, 'job_error': str(e), 'payload': False}


# ─────────────────────────── DNS helpers ────────────────────────────────────

def _update_hosts_file():
    sites = _get_sites()
    enabled = [s for s in sites if s.get('enabled', False)]

    try:
        with open(HOSTS_FILE, 'r') as f:
            content = f.read()
    except Exception:
        content = ''

    lines = content.split('\n')
    clean, in_block = [], False
    for line in lines:
        if line.strip() == HOSTS_START:
            in_block = True; continue
        if line.strip() == HOSTS_END:
            in_block = False; continue
        if not in_block:
            clean.append(line)

    while clean and clean[-1].strip() == '':
        clean.pop()

    if enabled:
        clean.append('')
        clean.append(HOSTS_START)
        for s in enabled:
            clean.append(f'{PINEAPPLE_IP} {s["hostname"]}')
            for alias in s.get('aliases', []):
                if alias:
                    clean.append(f'{PINEAPPLE_IP} {alias}')
        clean.append(HOSTS_END)

    with open(HOSTS_FILE, 'w') as f:
        f.write('\n'.join(clean) + '\n')


def _reload_dnsmasq():
    try:
        r = subprocess.run(['pgrep', 'dnsmasq'], capture_output=True, text=True)
        if r.returncode == 0:
            pid = r.stdout.strip().split('\n')[0]
            subprocess.run(['kill', '-HUP', pid], capture_output=True)
    except Exception as e:
        module.logger.error(f'dnsmasq reload failed: {e}')


# ─────────────────────────── Nginx helpers ──────────────────────────────────

def _ensure_dirs():
    os.makedirs(SITES_PATH, exist_ok=True)
    os.makedirs(NGINX_AVAILABLE, exist_ok=True)
    os.makedirs(NGINX_ENABLED, exist_ok=True)


def _check_ports_available() -> list:
    busy = []
    for port in (80,):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            sock.bind(('0.0.0.0', port))
        except OSError:
            busy.append(port)
        finally:
            sock.close()
    return busy


def _patch_nginx_conf():
    nginx_conf = '/etc/nginx/nginx.conf'
    include_line = '    include /etc/nginx/sites-enabled/*;'
    try:
        with open(nginx_conf, 'r') as f:
            content = f.read()
        if 'sites-enabled' not in content:
            idx = content.rfind('}')
            if idx != -1:
                content = content[:idx] + include_line + '\n' + content[idx:]
            with open(nginx_conf, 'w') as f:
                f.write(content)
    except Exception as e:
        module.logger.error(f'nginx.conf patch failed: {e}')


def _is_nginx_running() -> bool:
    r = subprocess.run(['pgrep', '-f', 'nginx: master'], capture_output=True)
    return r.returncode == 0


def _is_php_running() -> bool:
    r = subprocess.run(['pgrep', '-f', 'php-fpm'], capture_output=True)
    return r.returncode == 0


def _start_webserver():
    _ensure_dirs()
    _patch_nginx_conf()
    subprocess.Popen(['nginx'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sites = _get_sites()
    if any(s.get('php', False) and s.get('enabled', False) for s in sites):
        subprocess.Popen(['php-fpm7'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _stop_webserver():
    subprocess.Popen(['nginx', '-s', 'stop'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.Popen(['killall', '-q', 'php-fpm7'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _reload_nginx() -> bool:
    if _is_nginx_running():
        return subprocess.run(['nginx', '-s', 'reload'], capture_output=True).returncode == 0
    return False


def _get_nginx_vhost(site_name: str, hostname: str, php: bool, aliases: list = None) -> str:
    server_names = hostname
    if aliases:
        extras = ' '.join(a for a in aliases if a)
        if extras:
            server_names += ' ' + extras

    php_block = ''
    if php:
        php_block = """
    location ~ \\.php$ {
        fastcgi_pass unix:/var/run/php7-fpm.sock;
        fastcgi_index index.php;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }"""

    return f"""server {{
    listen 80;
    server_name {server_names};
    root {SITES_PATH}/{site_name};
    index index.php index.html index.htm;
    access_log /tmp/webserver_access_{site_name}.log;

    location ~ \\.log$ {{
        deny all;
        return 404;
    }}

    location / {{
        try_files $uri $uri/ =404;
    }}{php_block}
}}
"""


# ─────────────────────────── Site helpers ───────────────────────────────────

def _get_sites() -> list:
    _ensure_dirs()
    sites = []
    for site_name in sorted(os.listdir(SITES_PATH)):
        site_path = os.path.join(SITES_PATH, site_name)
        if not os.path.isdir(site_path):
            continue
        meta = {'name': site_name, 'hostname': site_name, 'php': False, 'aliases': []}
        meta_path = os.path.join(site_path, 'site.json')
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f:
                    meta.update(json.load(f))
            except Exception:
                pass
        meta['name']    = site_name
        meta['enabled'] = os.path.lexists(os.path.join(NGINX_ENABLED, site_name))
        if not isinstance(meta.get('aliases'), list):
            meta['aliases'] = []
        sites.append(meta)
    return sites


def _save_site_meta(site_name: str, meta: dict):
    with open(os.path.join(SITES_PATH, site_name, 'site.json'), 'w') as f:
        json.dump(meta, f, indent=2)


def _safe_path(base: str, rel: str):
    resolved = os.path.realpath(os.path.join(base, rel)) if rel else os.path.realpath(base)
    return resolved if resolved.startswith(os.path.realpath(base)) else None


def _parse_aliases(raw) -> list:
    if isinstance(raw, list):
        return [a.strip().lower() for a in raw if isinstance(a, str) and a.strip()]
    if isinstance(raw, str):
        return [a.strip().lower() for a in raw.split(',') if a.strip()]
    return []


# ─────────────────────────── Action handlers ────────────────────────────────

@module.handles_action('check_dependencies')
def check_dependencies(request: Request):
    return {'installed': _nginx_installed(), 'nginx': _nginx_installed(), 'php': _php_installed()}


@module.handles_action('manage_dependencies')
def manage_dependencies(request: Request):
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {'is_complete': False, 'job_error': None, 'payload': None}
    threading.Thread(target=_install_packages, args=(job_id,), daemon=True).start()
    return {'job_id': job_id}


@module.handles_action('poll_job')
def poll_job(request: Request):
    job_id = getattr(request, 'job_id', None)
    if not job_id or job_id not in _jobs:
        return {'is_complete': True, 'job_error': 'Job not found', 'payload': None}
    return _jobs[job_id]


@module.handles_action('status')
def status(request: Request):
    return {
        'nginx_running': _is_nginx_running(),
        'php_running':   _is_php_running(),
        'sites':         _get_sites(),
        'start_at_boot': _is_start_at_boot(),
    }


@module.handles_action('set_start_at_boot')
def set_start_at_boot(request: Request):
    enabled = bool(getattr(request, 'enabled', False))
    _set_start_at_boot(enabled)
    return {'start_at_boot': _is_start_at_boot()}


@module.handles_action('toggle_webserver')
def toggle_webserver(request: Request):
    if _is_nginx_running():
        _stop_webserver()
        return {'running': False}
    busy = _check_ports_available()
    if busy:
        return (
            'Port 80 is already in use. '
            'EvilPortal or another web service is likely running. Stop it first.',
            False
        )
    _start_webserver()
    return {'running': _is_nginx_running()}


@module.handles_action('reload_webserver')
def reload_webserver(request: Request):
    return {'success': _reload_nginx()}


@module.handles_action('list_sites')
def list_sites(request: Request):
    return {'sites': _get_sites()}


@module.handles_action('list_templates')
def list_templates(request: Request):
    templates = []
    if os.path.isdir(TEMPLATES_PATH):
        for name in sorted(os.listdir(TEMPLATES_PATH)):
            if os.path.isdir(os.path.join(TEMPLATES_PATH, name)):
                templates.append(name)
    return {'templates': templates}


@module.handles_action('create_site')
def create_site(request: Request):
    site_name   = request.site_name.strip().lower().replace(' ', '_')
    hostname    = request.hostname.strip().lower()
    php_enabled = bool(getattr(request, 'php', False))
    template_id = (getattr(request, 'template', None) or 'basic').strip()
    aliases     = _parse_aliases(getattr(request, 'aliases', []))

    if not site_name or not hostname:
        return 'Site name and hostname are required', False

    site_path = os.path.join(SITES_PATH, site_name)
    if os.path.exists(site_path):
        return f'A site named "{site_name}" already exists', False

    template_path = os.path.join(TEMPLATES_PATH, template_id)
    if not os.path.isdir(template_path):
        template_path = SKELETON_PATH

    shutil.copytree(template_path, site_path)
    meta = {'name': site_name, 'hostname': hostname, 'php': php_enabled, 'aliases': aliases}
    _save_site_meta(site_name, meta)

    with open(os.path.join(NGINX_AVAILABLE, site_name), 'w') as f:
        f.write(_get_nginx_vhost(site_name, hostname, php_enabled, aliases))

    return {'site': meta}


@module.handles_action('duplicate_site')
def duplicate_site(request: Request):
    source_name = request.source_name
    new_name    = request.site_name.strip().lower().replace(' ', '_')
    new_hostname = request.hostname.strip().lower()
    new_aliases  = _parse_aliases(getattr(request, 'aliases', []))

    if not new_name or not new_hostname:
        return 'Name and hostname are required', False

    source_path = os.path.join(SITES_PATH, source_name)
    new_path    = os.path.join(SITES_PATH, new_name)

    if not os.path.exists(source_path):
        return f'Source site "{source_name}" not found', False
    if os.path.exists(new_path):
        return f'A site named "{new_name}" already exists', False

    php_enabled = False
    try:
        with open(os.path.join(source_path, 'site.json')) as f:
            php_enabled = json.load(f).get('php', False)
    except Exception:
        pass

    shutil.copytree(source_path, new_path,
                    ignore=shutil.ignore_patterns('credentials.log'))

    meta = {'name': new_name, 'hostname': new_hostname, 'php': php_enabled, 'aliases': new_aliases}
    _save_site_meta(new_name, meta)

    with open(os.path.join(NGINX_AVAILABLE, new_name), 'w') as f:
        f.write(_get_nginx_vhost(new_name, new_hostname, php_enabled, new_aliases))

    return {'site': {**meta, 'enabled': False}}


@module.handles_action('rename_site')
def rename_site(request: Request):
    old_name     = request.site_name
    new_name     = getattr(request, 'new_name', old_name).strip().lower().replace(' ', '_')
    new_hostname = getattr(request, 'new_hostname', '').strip().lower()
    new_aliases  = _parse_aliases(getattr(request, 'aliases', []))

    if not new_name or not new_hostname:
        return 'Name and hostname are required', False

    old_path = os.path.join(SITES_PATH, old_name)
    new_path = os.path.join(SITES_PATH, new_name)

    if not os.path.exists(old_path):
        return f'Site "{old_name}" not found', False
    if new_name != old_name and os.path.exists(new_path):
        return f'A site named "{new_name}" already exists', False

    was_enabled = os.path.lexists(os.path.join(NGINX_ENABLED, old_name))

    # Remove old symlink and nginx config
    for p in (os.path.join(NGINX_ENABLED, old_name), os.path.join(NGINX_AVAILABLE, old_name)):
        if os.path.lexists(p):
            os.remove(p)

    if new_name != old_name:
        os.rename(old_path, new_path)

    # Preserve php flag
    php_enabled = False
    try:
        with open(os.path.join(new_path, 'site.json')) as f:
            php_enabled = json.load(f).get('php', False)
    except Exception:
        pass

    meta = {'name': new_name, 'hostname': new_hostname, 'php': php_enabled, 'aliases': new_aliases}
    _save_site_meta(new_name, meta)

    with open(os.path.join(NGINX_AVAILABLE, new_name), 'w') as f:
        f.write(_get_nginx_vhost(new_name, new_hostname, php_enabled, new_aliases))

    if was_enabled:
        os.symlink(os.path.join(NGINX_AVAILABLE, new_name),
                   os.path.join(NGINX_ENABLED, new_name))

    _update_hosts_file()
    _reload_dnsmasq()
    _reload_nginx()
    return {'site': {**meta, 'enabled': was_enabled}}


@module.handles_action('delete_site')
def delete_site(request: Request):
    site_name = request.site_name
    for path in (os.path.join(NGINX_ENABLED, site_name),
                 os.path.join(NGINX_AVAILABLE, site_name)):
        if os.path.lexists(path):
            os.remove(path)
    site_path = os.path.join(SITES_PATH, site_name)
    if os.path.exists(site_path):
        shutil.rmtree(site_path)
    _update_hosts_file()
    _reload_dnsmasq()
    _reload_nginx()
    return {'success': True}


@module.handles_action('enable_site')
def enable_site(request: Request):
    site_name = request.site_name
    available = os.path.join(NGINX_AVAILABLE, site_name)
    enabled   = os.path.join(NGINX_ENABLED,   site_name)
    if not os.path.exists(available):
        return 'Nginx config not found for this site', False
    if not os.path.lexists(enabled):
        os.symlink(available, enabled)
    _update_hosts_file()
    _reload_dnsmasq()
    _reload_nginx()
    return {'enabled': True}


@module.handles_action('disable_site')
def disable_site(request: Request):
    site_name = request.site_name
    enabled   = os.path.join(NGINX_ENABLED, site_name)
    if os.path.lexists(enabled):
        os.remove(enabled)
    _update_hosts_file()
    _reload_dnsmasq()
    _reload_nginx()
    return {'enabled': False}


@module.handles_action('load_directory')
def load_directory(request: Request):
    site_name = request.site_name
    rel_path  = getattr(request, 'path', '') or ''
    base      = os.path.join(SITES_PATH, site_name)
    target    = _safe_path(base, rel_path)
    if target is None:
        return 'Access denied', False
    if not os.path.isdir(target):
        return 'Directory not found', False
    files = []
    for name in os.listdir(target):
        full = os.path.join(target, name)
        rel  = os.path.join(rel_path, name) if rel_path else name
        files.append({'name': name, 'path': rel,
                      'is_dir': os.path.isdir(full),
                      'size': os.path.getsize(full) if not os.path.isdir(full) else 0})
    files.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
    return {'files': files, 'path': rel_path}


@module.handles_action('load_file')
def load_file(request: Request):
    site_name = request.site_name
    file_path = request.file_path
    base      = os.path.join(SITES_PATH, site_name)
    target    = _safe_path(base, file_path)
    if target is None:
        return 'Access denied', False
    if not os.path.isfile(target):
        return 'File not found', False
    try:
        with open(target, 'r', errors='replace') as f:
            return {'content': f.read(), 'path': file_path}
    except Exception as e:
        return str(e), False


@module.handles_action('save_file')
def save_file(request: Request):
    site_name = request.site_name
    file_path = request.file_path
    content   = request.content
    base      = os.path.join(SITES_PATH, site_name)
    target    = _safe_path(base, file_path)
    if target is None:
        return 'Access denied', False
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        with open(target, 'w') as f:
            f.write(content)
        return {'success': True}
    except Exception as e:
        return str(e), False


@module.handles_action('upload_file')
def upload_file(request: Request):
    site_name   = request.site_name
    file_path   = getattr(request, 'file_path', '') or ''
    content_b64 = request.content_b64
    base        = os.path.join(SITES_PATH, site_name)
    target      = _safe_path(base, file_path)
    if target is None:
        return 'Access denied', False
    try:
        data = base64.b64decode(content_b64)
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, 'wb') as f:
            f.write(data)
        return {'success': True}
    except Exception as e:
        return str(e), False


@module.handles_action('delete_file')
def delete_file(request: Request):
    site_name = request.site_name
    file_path = request.file_path
    base      = os.path.join(SITES_PATH, site_name)
    target    = _safe_path(base, file_path)
    if target is None:
        return 'Access denied', False
    if not os.path.exists(target):
        return 'File not found', False
    shutil.rmtree(target) if os.path.isdir(target) else os.remove(target)
    return {'success': True}


@module.handles_action('get_access_log')
def get_access_log(request: Request):
    lines_n   = min(int(getattr(request, 'lines', 100)), 500)
    site_name = (getattr(request, 'site_name', '') or '').strip()

    if site_name:
        log_path = f'/tmp/webserver_access_{site_name}.log'
        try:
            if not os.path.exists(log_path):
                return {'log': '(no traffic yet for this site)'}
            result = subprocess.run(['tail', f'-n{lines_n}', log_path],
                                    capture_output=True, text=True, timeout=5)
            return {'log': result.stdout or '(empty)'}
        except Exception as e:
            return {'log': f'Error: {e}'}

    # All sites combined
    try:
        lines = []
        if os.path.isdir(SITES_PATH):
            for sn in sorted(os.listdir(SITES_PATH)):
                p = f'/tmp/webserver_access_{sn}.log'
                if os.path.exists(p):
                    try:
                        r = subprocess.run(['tail', '-n50', p],
                                           capture_output=True, text=True, timeout=3)
                        for line in r.stdout.splitlines():
                            lines.append(f'[{sn}] {line}')
                    except Exception:
                        pass
        return {'log': '\n'.join(lines[-lines_n:]) if lines else '(no traffic yet)'}
    except Exception as e:
        return {'log': f'Error: {e}'}


@module.handles_action('get_credentials')
def get_credentials(request: Request):
    entries = []
    try:
        for site_name in sorted(os.listdir(SITES_PATH)):
            cred_file = os.path.join(SITES_PATH, site_name, 'credentials.log')
            if not os.path.isfile(cred_file):
                continue
            try:
                with open(cred_file, 'r', errors='replace') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split('\t')
                        entries.append({
                            'site':      site_name,
                            'timestamp': parts[0] if len(parts) > 0 else '',
                            'ip':        parts[1] if len(parts) > 1 else '',
                            'username':  parts[2] if len(parts) > 2 else '',
                            'password':  parts[3] if len(parts) > 3 else '',
                        })
            except Exception:
                pass
    except Exception:
        pass
    entries.sort(key=lambda e: e.get('timestamp', ''), reverse=True)
    return {'credentials': entries}


@module.handles_action('clear_credentials')
def clear_credentials(request: Request):
    site_name = (getattr(request, 'site_name', '') or '').strip()
    try:
        targets = [site_name] if site_name else os.listdir(SITES_PATH)
        for sn in targets:
            f = os.path.join(SITES_PATH, sn, 'credentials.log')
            if os.path.isfile(f):
                os.remove(f)
    except Exception as e:
        return str(e), False
    return {'success': True}


@module.handles_action('get_stats')
def get_stats(request: Request):
    stats = {}
    try:
        for site_name in sorted(os.listdir(SITES_PATH)):
            log_path = f'/tmp/webserver_access_{site_name}.log'
            try:
                if os.path.exists(log_path):
                    with open(log_path, 'r') as f:
                        stats[site_name] = sum(1 for l in f if l.strip())
                else:
                    stats[site_name] = 0
            except Exception:
                stats[site_name] = 0
    except Exception:
        pass
    return {'stats': stats}


@module.on_start()
def on_start():
    if _is_start_at_boot() and not _is_nginx_running():
        _start_webserver()


if __name__ == '__main__':
    module.start()
