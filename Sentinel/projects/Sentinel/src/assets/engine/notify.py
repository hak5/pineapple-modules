"""
Sentinel - notifications through ntfy (https://ntfy.sh, or your own ntfy server).

The settings live in /root/.Sentinel/notify.json (root only: it can hold an access token).
While listening, the engine runs a Notifier thread: every few seconds it reads the alerts written
since the last pass and posts the ones that qualify. It has its own database connection and never
blocks listening; a message that fails is tried again on the next pass.

Network names come from anyone in radio range, so messages are plain text: control characters
are removed, the length is capped, and ntfy's Markdown is never turned on.

Standard library only. HTTPS goes through Python's ssl module when the firmware has it, or
through curl otherwise.
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

import muted
import store

FILENAME = 'notify.json'
SEVERITY_RANK = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}
PRIORITY = {'critical': 5, 'high': 4, 'medium': 3, 'low': 2, 'info': 2}
DEFAULTS = {
    'version': 1,
    'enabled': False,
    'server': 'https://ntfy.sh',
    'topic': '',
    'token': '',
    'min_severity': 'high',
    'max_per_hour': 10,
    'status_messages': True,
}
TOPIC_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
SERVER_RE = re.compile(r'^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?$')
TOKEN_RE = re.compile(r'^[\x21-\x7e]{1,256}$')
PASS_INTERVAL = 10.0      # seconds between two looks at new alerts
TIMEOUT = 10              # seconds for one HTTP request
MAX_BODY = 900


# -- settings ---------------------------------------------------------------

def load(path):
    """The settings, with defaults. Never raises."""
    cfg = dict(DEFAULTS)
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            cfg.update((k, data[k]) for k in DEFAULTS if k in data)
    except (IOError, OSError, ValueError):
        pass
    return cfg


def validate(new, old):
    """Check settings sent by the interface. Returns (settings, None) or (None, error).
    An empty token keeps the saved one, unless clear_token is set."""
    if not isinstance(new, dict):
        return None, 'Invalid settings'
    cfg = dict(old)
    enabled = new.get('enabled')
    if not isinstance(enabled, bool):
        return None, 'enabled must be true or false'
    status = new.get('status_messages', cfg['status_messages'])
    if not isinstance(status, bool):
        return None, 'status_messages must be true or false'
    server = str(new.get('server') or '').strip().rstrip('/')
    if len(server) > 200 or not SERVER_RE.match(server):
        return None, 'The server must look like https://ntfy.sh or http://192.168.1.10:8080'
    topic = str(new.get('topic') or '').strip()
    if topic and not TOPIC_RE.match(topic):
        return None, 'The topic can only use letters, digits, - and _ (64 at most)'
    if enabled and not topic:
        return None, 'Choose a topic before turning notifications on'
    severity = new.get('min_severity')
    if severity not in ('critical', 'high', 'medium'):
        return None, 'The minimum severity must be critical, high or medium'
    per_hour = new.get('max_per_hour')
    if isinstance(per_hour, bool) or not isinstance(per_hour, int) or not 1 <= per_hour <= 60:
        return None, 'Messages per hour must be between 1 and 60'
    token = new.get('token')
    if new.get('clear_token') is True:
        cfg['token'] = ''
    elif token:
        token = str(token).strip()
        if not TOKEN_RE.match(token):
            return None, 'The access token has unexpected characters'
        cfg['token'] = token
    cfg.update({'enabled': enabled, 'status_messages': status, 'server': server, 'topic': topic,
                'min_severity': severity, 'max_per_hour': per_hour})
    return cfg, None


def save(path, cfg):
    """Atomic write, readable by root only."""
    tmp = path + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump(dict((k, cfg[k]) for k in DEFAULTS), fh, indent=2)
    os.rename(tmp, path)


def public(cfg):
    """What the interface may see: never the token itself."""
    out = dict((k, cfg[k]) for k in DEFAULTS if k != 'token')
    out['has_token'] = bool(cfg.get('token'))
    return out


# -- sending ----------------------------------------------------------------

def clean(text, limit=MAX_BODY):
    """Plain, single-paragraph-safe text: no control characters, bounded length."""
    text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', str(text))
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _https_in_python():
    try:
        import ssl  # noqa: F401  pylint: disable=unused-import,import-outside-toplevel
        return True
    except ImportError:
        return False


def send(cfg, title, message, priority=3, tags='', timeout=None):
    """Post one message. Returns None when it worked, or a short error. Never raises."""
    timeout = timeout or TIMEOUT
    url = '%s/%s' % (cfg['server'].rstrip('/'), cfg['topic'])
    headers = {'Title': clean(title, 120).encode('ascii', 'replace').decode('ascii'),
               'Priority': str(priority), 'Content-Type': 'text/plain; charset=utf-8'}
    if tags:
        headers['Tags'] = tags
    if cfg.get('token'):
        headers['Authorization'] = 'Bearer %s' % cfg['token']
    body = clean(message).encode('utf-8')
    if url.startswith('https://') and not _https_in_python():
        return _send_curl(url, headers, body, timeout)
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(256)
        return None
    except urllib.error.HTTPError as e:
        return 'The server answered %d%s' % (e.code, ' (check the access token)' if e.code in (401, 403) else '')
    except (urllib.error.URLError, OSError, ValueError) as e:
        return 'Could not reach the server (%s)' % getattr(e, 'reason', e)


def _send_curl(url, headers, body, timeout):
    """HTTPS through curl when Python has no ssl module. Headers go through a root-only
    file, so the token never shows up in the process list."""
    curl = shutil.which('curl')
    if not curl:
        return 'HTTPS needs python3-openssl or curl on the Pineapple'
    fd, hfile = tempfile.mkstemp(prefix='sentinel-notify-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            for k, v in headers.items():
                fh.write('%s: %s\n' % (k, v))
        done = subprocess.run([curl, '-sS', '-o', '/dev/null', '-w', '%{http_code}', '--max-time', str(timeout),
                               '-H', '@' + hfile, '--data-binary', '@-', url],
                              input=body, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout + 5, check=False)
        code = done.stdout.decode('ascii', 'replace').strip()
        if done.returncode == 0 and code.startswith('2'):
            return None
        if code and code != '000':
            return 'The server answered %s' % code
        return 'Could not reach the server (%s)' % done.stderr.decode('utf-8', 'replace').strip()[:120]
    except (OSError, subprocess.SubprocessError) as e:
        return 'curl failed (%s)' % e
    finally:
        try:
            os.unlink(hfile)
        except OSError:
            pass


# -- the engine's sender ----------------------------------------------------

class Notifier(object):
    """Posts new alerts while the engine listens. Runs in its own thread."""

    def __init__(self, db_path, data_dir):
        self.db_path = db_path
        self.path = os.path.join(data_dir, FILENAME)
        self.muted_path = os.path.join(data_dir, muted.FILENAME)
        self._halt = threading.Event()
        self._thread = None
        self._status = []            # status messages waiting to be sent
        self._lock = threading.Lock()
        self._sent = []              # times of the messages sent in the last hour
        self.held = 0                # alerts held back by the hourly limit, told in one message
        self.last_error = None
        self._last_pass_timeout = None   # set by stop(): the last pass must be quick

    def start(self):
        self._thread = threading.Thread(target=self._run, name='sentinel-notify', daemon=True)
        self._thread.start()

    def stop(self, timeout=5):
        """Ask for one last pass (it sends what is queued), wait at most `timeout` seconds."""
        self._last_pass_timeout = max(1, int(timeout))
        self._halt.set()
        if self._thread:
            self._thread.join(timeout)

    def status(self, text):
        """Queue a status message (radio lost, listening stopped...)."""
        with self._lock:
            self._status.append(clean(text, 300))

    def _room(self, now):
        self._sent = [t for t in self._sent if now - t < 3600]
        return len(self._sent)

    def _run(self):
        conn = None
        try:
            conn = store.connect(self.db_path)
            while True:
                stopping = self._halt.wait(PASS_INTERVAL)
                try:
                    self.run_once(conn, time.time())
                except sqlite3.Error as e:
                    self.last_error = 'Database error: %s' % e
                if stopping:
                    break
        except Exception as e:  # noqa: BLE001 - never let notifications take the engine down
            self.last_error = str(e)
        finally:
            if conn is not None:
                conn.close()

    def run_once(self, conn, now):
        """One pass: status messages, then new alerts. Returns how many messages were sent."""
        cfg = load(self.path)
        last = store.get_meta(conn).get('notify_last_id')
        newest = conn.execute('SELECT COALESCE(MAX(id), 0) FROM events').fetchone()[0]
        if not cfg['enabled'] or not cfg['topic']:
            # Nothing old is sent when notifications are turned on later
            with self._lock:
                self._status = []
            if last != newest:
                with conn:
                    store.set_meta(conn, {'notify_last_id': newest})
            return 0
        if last is None:
            last = newest
            with conn:
                store.set_meta(conn, {'notify_last_id': last})

        sent = 0
        with self._lock:
            pending, self._status = self._status, []
        if cfg['status_messages']:
            for i, text in enumerate(pending):
                err = send(cfg, 'Sentinel', text, priority=3, tags='satellite', timeout=self._last_pass_timeout)
                if err:
                    with self._lock:
                        self._status = pending[i:] + self._status
                    self.last_error = err
                    return sent
                self._sent.append(now)
                sent += 1

        silenced = muted.load(self.muted_path)
        limit = SEVERITY_RANK[cfg['min_severity']]
        rows = conn.execute(
            "SELECT id, ts, kind, severity, title, bssid FROM events WHERE id > ? AND source = 'wids' "
            "AND kind != 'suppressed' ORDER BY id LIMIT 200", (last,)).fetchall()
        for event_id, ts, kind, severity, title, bssid in rows:
            if kind not in silenced and SEVERITY_RANK.get(severity, 9) <= limit:
                if self._room(now) >= cfg['max_per_hour']:
                    self.held += 1
                else:
                    when = time.strftime('%H:%M', time.localtime(ts))
                    body = '%s\n%s at %s%s' % (title, severity.capitalize(), when,
                                               ', BSSID %s' % bssid if bssid else '')
                    err = send(cfg, 'Sentinel: %s alert' % severity.capitalize(), body,
                               priority=PRIORITY.get(severity, 3),
                               tags='rotating_light' if severity == 'critical' else 'warning')
                    if err:
                        self.last_error = err
                        break   # try this alert again on the next pass
                    self._sent.append(now)
                    sent += 1
            last = event_id
            with conn:
                store.set_meta(conn, {'notify_last_id': last})

        if self.held and self._room(now) < cfg['max_per_hour']:
            err = send(cfg, 'Sentinel: more alerts', '%d more alert%s were not sent (limit of %d per hour). '
                       'Open Sentinel to see them.' % (self.held, '' if self.held == 1 else 's',
                                                        cfg['max_per_hour']), priority=3, tags='warning')
            if not err:
                self._sent.append(now)
                self.held = 0
                sent += 1
        if sent:
            self.last_error = None
        return sent
