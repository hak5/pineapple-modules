#!/usr/bin/env python3
"""
Sentinel - defensive WiFi suite for the WiFi Pineapple Mark VII.

This is the module backend that answers the web UI. The heavy lifting
(capture and parsing) happens in assets/engine/engine.py, a separate
background process; this file only starts/stops it and reads its database.
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time

from pineapple.modules import Module, Request
from pineapple.helpers.opkg_helpers import OpkgJob
import pineapple.helpers.notification_helpers as notifier
from pineapple.jobs import JobManager

MODULE_NAME = 'Sentinel'
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.join(MODULE_DIR, 'assets', 'engine')
ENGINE = os.path.join(ENGINE_DIR, 'engine.py')

DATA_DIR = '/root/.%s' % MODULE_NAME
DB_PATH = os.path.join(DATA_DIR, 'sentinel.db')
SETTINGS_PATH = os.path.join(DATA_DIR, 'settings.json')
PID_PATH = '/tmp/sentinel-engine.pid'
LOG_PATH = '/tmp/sentinel-engine.log'

DEPENDENCIES = ['python3-sqlite3']
# Installing a package as root from the Internet takes a click: Sentinel is a cautious,
# passive module. Set to True to install it as soon as the module is opened.
AUTO_INSTALL_DEPENDENCIES = False
PYTHON_PACKAGES_PREFIXES = ('python3', 'libpython3', 'libsqlite3')
# What Sentinel changed on the radios (monitor interfaces created, interfaces taken down),
# so that stopping can undo it and uninstall.sh knows what to remove (audit 3.1)
RADIO_STATE_PATH = '/tmp/sentinel-radios.json'

CHANNELS_24 = [1, 6, 11, 2, 7, 3, 8, 4, 9, 5, 10]
# All 20 MHz 5 GHz channels, DFS included (receive-only listening). See engine.py.
CHANNELS_5 = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128,
              132, 136, 140, 144, 149, 153, 157, 161, 165]

DEFAULT_SETTINGS = {
    # Up to two radios capture in parallel, e.g. the built-in 2.4 GHz radio
    # and the 5 GHz extension, each hopping its own band.
    'radios': [
        {'iface': 'wlan1mon', 'enabled': True, 'hopping': True, 'channels': CHANNELS_24},
        {'iface': '', 'enabled': False, 'hopping': True, 'channels': CHANNELS_5},
    ],
    'dwell_ms': 750,
    # Privacy by default: off. Clients = MAC addresses of devices seen exchanging data;
    # probes = network names that nearby devices search for. Both belong to third parties.
    'track_clients': False,
    'track_probes': False,
    'autostart': False,
    # Passive intrusion detection (assets/engine/detect.py)
    'wids_enabled': True,
    'channel_window_minutes': 10,
    'audit_max_age_minutes': 60,
}

# The engine writes a heartbeat every 5 s. Without one for this long it is not listening.
HEARTBEAT_STALE = 20
# On the Mark VII the engine needs 4 to 6 s before its first heartbeat (Python imports
# alone take almost 3 s). Past this delay without a heartbeat, it is reported as stalled.
START_GRACE = 30

sys.path.insert(0, ENGINE_DIR)

_engine_proc = None      # the engine process, when this backend started it
_radio_warnings = {}     # monitor interface -> why it cannot hop, from the last start

module = Module(MODULE_NAME, logging.INFO)
job_manager = JobManager(name=MODULE_NAME, module=module, log_level=logging.INFO)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _sqlite_available():
    import importlib
    importlib.invalidate_caches()  # it may have been installed since the last try
    try:
        import sqlite3  # noqa: F401  pylint: disable=unused-import,import-outside-toplevel
        return True
    except ImportError:
        return False


# --------------------------------------------------------------------------
# Radio state: what Sentinel changed, to undo it (audit 3.1)
# --------------------------------------------------------------------------

def _radio_state():
    try:
        with open(RADIO_STATE_PATH, encoding='utf-8') as fh:
            state = json.load(fh)
        if isinstance(state, dict):
            return {'created': [n for n in state.get('created', []) if isinstance(n, str)],
                    'downed': [n for n in state.get('downed', []) if isinstance(n, str)]}
    except (IOError, OSError, ValueError):
        pass
    return {'created': [], 'downed': []}


def _remember_radio(kind, name):
    state = _radio_state()
    if name not in state[kind]:
        state[kind].append(name)
        try:
            with open(RADIO_STATE_PATH + '.tmp', 'w', encoding='utf-8') as fh:
                json.dump(state, fh)
            os.rename(RADIO_STATE_PATH + '.tmp', RADIO_STATE_PATH)
        except (IOError, OSError):
            pass


def _restore_radios():
    """Bring back up the interfaces Sentinel took down. Monitor interfaces it created stay:
    the next start uses them again, and uninstall.sh removes them."""
    state = _radio_state()
    for name in state['downed']:
        _run(['ip', 'link', 'set', name, 'up'])
    state['downed'] = []
    try:
        with open(RADIO_STATE_PATH, 'w', encoding='utf-8') as fh:
            json.dump(state, fh)
    except (IOError, OSError):
        pass


def _load_settings():
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))  # deep copy
    try:
        with open(SETTINGS_PATH, encoding='utf-8') as fh:
            saved = json.load(fh)
    except (IOError, ValueError):
        saved = {}
    # Migrate the single-radio format of v0.1.0
    if 'radios' not in saved and saved.get('iface'):
        saved['radios'] = [
            {'iface': saved['iface'], 'enabled': True,
             'hopping': saved.get('channel_hopping', True),
             'channels': saved.get('channels') or CHANNELS_24 + CHANNELS_5},
            dict(DEFAULT_SETTINGS['radios'][1]),
        ]
    for legacy in ('iface', 'channel_hopping', 'channels'):
        saved.pop(legacy, None)
    settings.update(saved)
    while len(settings['radios']) < 2:
        settings['radios'].append(dict(DEFAULT_SETTINGS['radios'][1]))
    settings['radios'] = settings['radios'][:2]
    return settings


def _ensure_data_dir():
    """The data folder holds the database and settings: root only (0700)."""
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)


def _save_settings(settings):
    _ensure_data_dir()
    tmp = SETTINGS_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(settings, fh, indent=2)
    os.rename(tmp, SETTINGS_PATH)


def _run(args, timeout=10):
    """Run a command. Returns (exit code, output) and never raises."""
    try:
        done = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=timeout, check=False)
        return done.returncode, done.stdout.decode('utf-8', 'replace')
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def _is_engine(pid):
    """False when `pid` clearly belongs to another program (a recycled PID)."""
    try:
        with open('/proc/%d/cmdline' % pid, 'rb') as fh:
            return b'engine.py' in fh.read()
    except (IOError, OSError):
        return True  # cannot tell: trust the PID file


def _engine_pid():
    """PID of the running engine, or None."""
    global _engine_proc
    if _engine_proc is not None:
        if _engine_proc.poll() is None:
            return _engine_proc.pid
        # It has exited (poll() also reaps it, so it does not linger as a zombie)
        _forget_pid(_engine_proc.pid)
        _engine_proc = None
    # An engine started by an earlier run of this backend keeps listening
    try:
        with open(PID_PATH, encoding='utf-8') as fh:
            pid = int(fh.read().strip())
        os.kill(pid, 0)
    except (IOError, ValueError, OSError):
        return None
    return pid if _is_engine(pid) else None


def _forget_pid(pid):
    try:
        with open(PID_PATH, encoding='utf-8') as fh:
            if int(fh.read().strip()) == pid:
                os.unlink(PID_PATH)
    except (IOError, ValueError, OSError):
        pass


def _engine_state(pid, engine, now=None):
    """
    'stopped', 'starting', 'listening' or 'stalled'. Only a recent heartbeat written
    by the process that is running now counts: the database also holds the last
    status of earlier runs.
    """
    if not pid:
        return 'stopped'
    now = now or time.time()
    heartbeat = engine.get('heartbeat')
    if (engine.get('pid') == pid and engine.get('running') and heartbeat is not None
            and now - heartbeat < HEARTBEAT_STALE):
        return 'listening'
    try:
        launched = os.path.getmtime(PID_PATH)
    except OSError:
        launched = 0
    return 'starting' if now - launched < START_GRACE else 'stalled'


def _db():
    """Read-only connection, or None when the engine has never run."""
    if not os.path.exists(DB_PATH):
        return None
    import store
    return store.connect(DB_PATH, readonly=True)


def _wireless_interfaces():
    out = []
    base = '/sys/class/net'
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for name in names:
        phy_path = os.path.join(base, name, 'phy80211', 'name')
        if not os.path.exists(phy_path):
            continue
        try:
            with open(phy_path, encoding='utf-8') as fh:
                phy = fh.read().strip()
            with open(os.path.join(base, name, 'type'), encoding='utf-8') as fh:
                link_type = int(fh.read().strip())
            with open(os.path.join(base, name, 'operstate'), encoding='utf-8') as fh:
                state = fh.read().strip()
        except (IOError, ValueError):
            continue
        try:
            with open(os.path.join(base, name, 'flags'), encoding='utf-8') as fh:
                up = bool(int(fh.read().strip(), 16) & 0x1)  # IFF_UP
        except (IOError, ValueError):
            up = state == 'up'
        out.append({'name': name, 'phy': phy, 'monitor': link_type == 803, 'state': state,
                    'up': up, 'bands': _phy_bands(phy)})
    return out


_BANDS_CACHE = {}


def _phy_bands(phy):
    """Which bands a radio supports, read from `iw phy <phy> info`."""
    if phy in _BANDS_CACHE:
        return _BANDS_CACHE[phy]
    bands = []
    try:
        out = subprocess.run(['iw', 'phy', phy, 'info'], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=5, check=False).stdout.decode('utf-8', 'replace')
    except (OSError, subprocess.SubprocessError):
        out = ''
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith('* ') or 'MHz' not in line or 'disabled' in line:
            continue
        try:
            freq = float(line[2:].split('MHz')[0].strip())
        except ValueError:
            continue
        band = '2.4' if freq < 3000 else ('5' if freq < 5925 else '6')
        if band not in bands:
            bands.append(band)
    _BANDS_CACHE[phy] = bands
    return bands


def _tail(path, lines=20):
    try:
        with open(path, encoding='utf-8') as fh:
            return fh.read().splitlines()[-lines:]
    except IOError:
        return []


def _ensure_monitor(iface):
    """
    Return the name of a monitor interface for `iface`, creating `<iface>mon`
    on the same radio when needed. Returns None when that is not possible.
    """
    interfaces = dict((i['name'], i) for i in _wireless_interfaces())
    if iface not in interfaces:
        return None
    if interfaces[iface]['monitor']:
        return iface
    new_name = '%smon' % iface
    if new_name not in interfaces:
        rc, _ = _run(['iw', 'phy', interfaces[iface]['phy'], 'interface', 'add',
                      new_name, 'type', 'monitor'])
        if rc != 0:
            return None
        _remember_radio('created', new_name)
    _run(['ip', 'link', 'set', new_name, 'up'])
    return new_name


def _iface_mode(name):
    """'managed', 'AP', 'monitor'... as reported by `iw`, or None."""
    rc, out = _run(['iw', 'dev', name, 'info'])
    for line in out.splitlines():
        words = line.split()
        if rc == 0 and len(words) >= 2 and words[0] == 'type':
            return words[1]
    return None


def _iface_connected(name):
    """True unless `iw` positively says the interface is not connected."""
    rc, out = _run(['iw', 'dev', name, 'link'])
    return not (rc == 0 and out.strip().startswith('Not connected'))


def _free_radio(monitor):
    """
    A monitor interface cannot change channel while another interface of the same
    radio is up: `iw` answers "Resource busy (-16)". That is the case of the MK7AC,
    whose `wlan3` comes up in client mode at every boot.

    Take the idle client-mode interfaces of that radio down. Anything in use (a
    connected client, an access point) is left alone. Returns the names of the
    interfaces that still keep the radio busy.
    """
    interfaces = _wireless_interfaces()
    phy = [i['phy'] for i in interfaces if i['name'] == monitor]
    blockers = []
    for i in interfaces:
        if not phy or i['phy'] != phy[0] or i['name'] == monitor or i['monitor'] or not i['up']:
            continue
        if _iface_mode(i['name']) == 'managed' and not _iface_connected(i['name']):
            rc, _ = _run(['ip', 'link', 'set', i['name'], 'down'])
            if rc == 0:
                _remember_radio('downed', i['name'])
                continue
        blockers.append(i['name'])
    return blockers


def _prepare_radios(settings):
    """
    Run before every engine start, because both of these are undone by a reboot:
      * a configured `<name>mon` that is gone is created again;
      * the radio of every hopping monitor interface is freed (see _free_radio).
    Returns {monitor interface: warning} for the radios that cannot hop.
    """
    warnings = {}
    for radio in settings['radios']:
        iface = radio.get('iface') or ''
        if not radio.get('enabled') or not iface:
            continue
        interfaces = dict((i['name'], i) for i in _wireless_interfaces())
        if iface not in interfaces and iface.endswith('mon'):
            _ensure_monitor(iface[:-3])
            interfaces = dict((i['name'], i) for i in _wireless_interfaces())
        if radio.get('hopping', True) and iface in interfaces and interfaces[iface]['monitor']:
            blockers = _free_radio(iface)
            if blockers:
                warnings[iface] = (
                    '%s is in use on the same radio, so %s cannot change channel. '
                    'Disconnect %s, or turn off channel hopping for this radio.'
                    % (' and '.join(blockers), iface, ' and '.join(blockers)))
    return warnings


def _start_engine():
    global _engine_proc, _radio_warnings
    if _engine_pid():
        return True, 'Monitoring is already running'
    if not _sqlite_available():
        return False, 'python3-sqlite3 is missing: install the dependency first'
    settings = _load_settings()
    _save_settings(settings)
    _radio_warnings = _prepare_radios(settings)
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as log:
            _engine_proc = subprocess.Popen(
                ['python3', ENGINE, '--db', DB_PATH, '--settings', SETTINGS_PATH,
                 '--pidfile', PID_PATH],
                stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
                close_fds=True)
    except OSError as e:
        return False, 'Monitoring could not start: %s' % e
    # The process exists from this instant, so record its PID now instead of waiting
    # for the engine to write it (4 to 6 s on the Mark VII). Until its first heartbeat
    # get_status reports "starting"; if it gives up, its reason is in the status.
    with open(PID_PATH, 'w', encoding='utf-8') as fh:
        fh.write(str(_engine_proc.pid))
    time.sleep(0.3)
    if _engine_pid() is None:
        err = _tail(LOG_PATH, 3)
        return False, 'Monitoring could not start: %s' % (' '.join(err) or 'see %s' % LOG_PATH)
    return True, 'Monitoring is starting'


def _stop_engine():
    pid = _engine_pid()
    if not pid:
        return True
    os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        time.sleep(0.25)
        if not _engine_pid():
            return True
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    for _ in range(8):  # make sure it is gone before anything else uses the radios (audit 3.6)
        time.sleep(0.25)
        if not _engine_pid():
            break
    return True


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------

@module.on_start()
def on_start():
    _ensure_data_dir()
    if not os.path.exists(SETTINGS_PATH):
        _save_settings(DEFAULT_SETTINGS)
    if _load_settings().get('autostart') and _sqlite_available() and not _engine_pid():
        _, msg = _start_engine()
        module.logger.info('Autostart: %s' % msg)

# The engine is intentionally NOT stopped when the module backend shuts down:
# monitoring keeps running in the background until the user stops it.


# --------------------------------------------------------------------------
# Dependencies
# --------------------------------------------------------------------------

_dep = {'state': None, 'job_id': None, 'error': None, 'warning': None, 'auto_tried': False,
        'before': None}


def _python_packages():
    """{name: version} of the installed Python and SQLite packages; {} when opkg fails."""
    rc, out = _run(['opkg', 'list-installed'])
    if rc != 0:
        return {}
    found = {}
    for line in out.splitlines():
        parts = line.split(' - ')
        if len(parts) >= 2 and parts[0].strip().startswith(PYTHON_PACKAGES_PREFIXES):
            found[parts[0].strip()] = parts[1].strip()
    return found


def _start_dependency_install():
    """Start the opkg job, or return the one already running."""
    if _dep['state'] == 'installing' and _dep['job_id']:
        return _dep['job_id']
    _dep.update(error=None, warning=None, before=_python_packages())
    _dep['job_id'] = job_manager.execute_job(OpkgJob(DEPENDENCIES[0], True),
                                             callbacks=[_dependencies_done])
    _dep['state'] = 'installing'
    return _dep['job_id']


def _dependencies_done(job):
    if job.was_successful and _sqlite_available():
        _dep['state'], _dep['error'] = 'ok', None
        module.send_notification('Sentinel: dependency installed.', notifier.SUCCESS)
    else:
        _dep['state'] = 'failed'
        _dep['error'] = str(getattr(job, 'error', None) or 'python3-sqlite3 could not be installed')
        module.send_notification('Sentinel: %s' % _dep['error'], notifier.ERROR)
    # Only python3-sqlite3 may appear: anything else changing means the feed upgraded part
    # of Python (the feed is newer than the firmware). Report it; never undo it here.
    before, after = _dep['before'] or {}, _python_packages()
    if before and after:
        changed = sorted(n for n in after if n != DEPENDENCIES[0] and before.get(n) != after[n])
        if changed:
            _dep['warning'] = ('Other Python packages were changed during the install: %s'
                               % ', '.join('%s %s' % (n, after[n]) for n in changed))
            module.send_notification('Sentinel: %s' % _dep['warning'], notifier.ERROR)


def _maybe_auto_install():
    """With AUTO_INSTALL_DEPENDENCIES, one automatic try per run of this backend."""
    if AUTO_INSTALL_DEPENDENCIES and not _dep['auto_tried'] and not _sqlite_available():
        _dep['auto_tried'] = True
        _start_dependency_install()


def _dependencies_status():
    sqlite = _sqlite_available()
    state = _dep['state']
    if sqlite and state != 'installing':
        state = 'ok'
    elif not sqlite and state not in ('installing', 'failed'):
        state = 'missing'
    return {'sqlite': sqlite, 'state': state, 'job_id': _dep['job_id'], 'error': _dep['error'],
            'warning': _dep['warning'], 'auto': AUTO_INSTALL_DEPENDENCIES}


@module.handles_action('check_dependencies')
def check_dependencies(request: Request):
    return _dependencies_status()


@module.handles_action('install_dependencies')
def install_dependencies(request: Request):
    try:
        return {'job_id': _start_dependency_install()}
    except Exception as e:
        _dep['state'], _dep['error'] = 'failed', str(e)
        return 'Could not start the install: %s' % e, False

# `poll_job` is registered automatically by JobManager.


# --------------------------------------------------------------------------
# Engine control and settings
# --------------------------------------------------------------------------

@module.handles_action('get_status')
def get_status(request: Request):
    try:
        _maybe_auto_install()
    except Exception as e:  # the status must answer whatever happens to the install
        _dep['state'], _dep['error'] = 'failed', str(e)
    pid = _engine_pid()
    engine = {}
    conn = _db()
    if conn is not None:
        try:
            import store
            engine = store.get_meta(conn).get('engine', {})
        finally:
            conn.close()
    heartbeat_age = time.time() - engine['heartbeat'] if engine.get('heartbeat') else None
    state = _engine_state(pid, engine)
    return {
        'state': state,
        'running': bool(pid),
        'pid': pid,
        'healthy': state == 'listening',
        'heartbeat_age': heartbeat_age,
        'radio_warnings': _radio_warnings if pid else {},
        'wids_unread': _with_db(lambda c: c.execute(
            "SELECT COUNT(*) FROM events WHERE source = 'wids' AND acknowledged = 0").fetchone()[0], 0),
        'engine': engine,
        'settings': _load_settings(),
        'interfaces': _wireless_interfaces(),
        'dependencies': _dependencies_status(),
        'log': _tail(LOG_PATH, 10),
        # The Pineapple has no battery-backed clock and often no Internet: its time can be far
        # behind. The page measures "x min ago" against this, not against the computer's clock.
        'server_time': time.time(),
    }


@module.handles_action('start_engine')
def start_engine(request: Request):
    ok, msg = _start_engine()
    return msg, ok


@module.handles_action('stop_engine')
def stop_engine(request: Request):
    _stop_engine()
    _restore_radios()  # give back the interfaces Sentinel took down (audit 3.1)
    return 'Monitoring stopped'


@module.handles_action('save_settings')
def save_settings(request: Request):
    incoming = getattr(request, 'settings', None) or {}
    settings = _load_settings()
    for key in DEFAULT_SETTINGS:
        if key in incoming:
            settings[key] = incoming[key]
    # Switches must be real booleans, numbers real bounded integers (audit 2.2)
    for key in ('track_clients', 'track_probes', 'autostart', 'wids_enabled'):
        if not isinstance(settings.get(key), bool):
            return 'Invalid value for %s' % key, False
    try:
        settings['dwell_ms'] = max(200, min(5000, int(settings['dwell_ms'])))
        settings['channel_window_minutes'] = max(1, min(240, int(settings['channel_window_minutes'])))
        settings['audit_max_age_minutes'] = max(1, min(7 * 24 * 60, int(settings['audit_max_age_minutes'])))
        radios = []
        for r in list(settings['radios'])[:2]:
            radios.append({
                'iface': str(r.get('iface') or '').strip(),
                'enabled': bool(r.get('enabled')),
                'hopping': bool(r.get('hopping', True)),
                'channels': [int(c) for c in (r.get('channels') or []) if 1 <= int(c) <= 233],
            })
        settings['radios'] = radios
    except (TypeError, ValueError, AttributeError, OverflowError):
        return 'Invalid settings', False
    active = [r for r in radios if r['enabled'] and r['iface']]
    if not active:
        return 'Enable at least one radio', False
    if any(r['hopping'] and not r['channels'] for r in active):
        return 'Each active radio needs at least one channel', False
    # A radio can only listen through a monitor interface: switch to `<name>mon`,
    # creating it when needed, instead of saving a name the engine would refuse.
    interfaces = dict((i['name'], i) for i in _wireless_interfaces())
    for r in active:
        if r['iface'] in interfaces and not interfaces[r['iface']]['monitor']:
            monitor = _ensure_monitor(r['iface'])
            if monitor is None:
                return 'Could not create a monitor interface for %s' % r['iface'], False
            r['iface'] = monitor
    if len(active) == 2 and active[0]['iface'] == active[1]['iface']:
        return 'Both radios use the same interface', False
    _save_settings(settings)
    restarted = False
    if _engine_pid():
        _stop_engine()
        ok, msg = _start_engine()
        if not ok:
            return msg, False
        restarted = True
    return {'settings': settings, 'restarted': restarted}


@module.handles_action('create_monitor')
def create_monitor(request: Request):
    """Create a monitor interface on the phy of an existing interface (e.g. a USB adapter)."""
    iface = getattr(request, 'iface', '')
    if not any(i['name'] == iface for i in _wireless_interfaces()):
        return 'Unknown interface', False
    monitor = _ensure_monitor(iface)
    if monitor is None:
        return 'Could not create the monitor interface (iw failed)', False
    return {'iface': monitor}


@module.handles_action('clear_data')
def clear_data(request: Request):
    was_running = bool(_engine_pid())
    _stop_engine()
    for suffix in ('', '-wal', '-shm'):
        try:
            os.unlink(DB_PATH + suffix)
        except OSError:
            pass
    if was_running:
        _start_engine()
    return 'Collected data cleared'


# --------------------------------------------------------------------------
# Data for the tabs
# --------------------------------------------------------------------------

def _with_db(fn, empty):
    conn = _db()
    if conn is None:
        return empty
    try:
        return fn(conn)
    finally:
        conn.close()


def _mine():
    import mynets
    return set(mynets.load(_mynets_path()))


def _audit_window(request=None):
    """The same window for the Overview score and the Security tab (audit 6.4)."""
    try:
        minutes = int(getattr(request, 'max_age_minutes', 0) or _load_settings()['audit_max_age_minutes'])
    except (TypeError, ValueError, OverflowError):
        minutes = DEFAULT_SETTINGS['audit_max_age_minutes']
    return max(1, min(7 * 24 * 60, minutes)) * 60


@module.handles_action('get_dashboard')
def get_dashboard(request: Request):
    import analysis

    settings = _load_settings()
    tracking = {'clients': bool(settings.get('track_clients')),
                'probes': bool(settings.get('track_probes'))}
    mine = _mine()

    def build(c):
        audit = analysis.security_audit(c, max_age=_audit_window(), mine=mine)
        return {
            'tracking': tracking,
            'stats': analysis.dashboard(c),
            'events': analysis.recent_events(c, limit=8, source='wids'),
            'spectrum': analysis.spectrum(c, max_age=600, mine=mine),
            'security': {'score': audit['score'], 'total': audit['total'],
                         'summary': audit['summary'], 'my_score': audit['my_score'],
                         'my_total': audit['my_total'], 'my_summary': audit['my_summary']},
            'my_networks': len(mine),
        }
    return _with_db(build, {'tracking': tracking, 'stats': None, 'events': [], 'spectrum': [],
                            'security': None, 'my_networks': len(mine)})


@module.handles_action('get_spectrum')
def get_spectrum(request: Request):
    import analysis
    try:
        minutes = int(getattr(request, 'max_age_minutes', 10) or 10)
    except (TypeError, ValueError, OverflowError):
        minutes = 10
    max_age = max(1, min(24 * 60, minutes)) * 60
    mine = _mine()
    return _with_db(lambda c: analysis.spectrum(c, max_age=max_age, mine=mine), [])


@module.handles_action('get_channels')
def get_channels(request: Request):
    import analysis
    window = int(getattr(request, 'window', 0) or _load_settings()['channel_window_minutes'])
    return _with_db(lambda c: analysis.channels_report(c, window_minutes=window),
                    {'channels': [], 'recommendation': {}, 'window_minutes': window})


@module.handles_action('get_audit')
def get_audit(request: Request):
    import analysis
    max_age = _audit_window(request)
    mine = _mine()
    return _with_db(lambda c: analysis.security_audit(c, max_age=max_age, mine=mine),
                    {'total': 0, 'networks': [], 'summary': {}, 'score': None,
                     'my_total': 0, 'my_score': None, 'my_summary': {}})


def _bounded_int(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError, OverflowError):
        return default


@module.handles_action('get_events')
def get_events(request: Request):
    import analysis
    limit = _bounded_int(getattr(request, 'limit', 100), 100, 1, 500)
    source = getattr(request, 'source', None)
    if source not in (None, 'wids'):
        return 'Unknown event source', False
    return _with_db(lambda c: analysis.recent_events(c, limit=limit, source=source), [])


@module.handles_action('get_detection')
def get_detection(request: Request):
    """Everything the Detection tab shows, in one request."""
    import analysis
    limit = _bounded_int(getattr(request, 'limit', 200), 200, 1, 500)
    mine = _mine()
    enabled = _load_settings().get('wids_enabled', True) is not False

    def build(c):
        by_severity = dict((r[0], r[1]) for r in c.execute(
            "SELECT severity, COUNT(*) FROM events WHERE source = 'wids' AND acknowledged = 0 "
            'GROUP BY severity'))
        return {
            'events': analysis.recent_events(c, limit=limit, source='wids'),
            'unacknowledged': sum(by_severity.values()),
            'by_severity': by_severity,
            'my_networks': len(mine),
            'enabled': enabled,
            'muted': silenced,
        }
    silenced = sorted(_muted())
    return _with_db(build, {'events': [], 'unacknowledged': 0, 'by_severity': {},
                            'my_networks': len(mine), 'enabled': enabled, 'muted': silenced})


def _muted_path():
    import muted
    return os.path.join(DATA_DIR, muted.FILENAME)


def _muted():
    import muted
    return muted.load(_muted_path())


@module.handles_action('set_alert_muted')
def set_alert_muted(request: Request):
    """Mute or unmute one type of alert. Muting also marks its unread alerts as read."""
    import muted
    kind = getattr(request, 'kind', None)
    if kind not in muted.KINDS:
        return 'Unknown alert type', False
    on = getattr(request, 'muted', None)
    if not isinstance(on, bool):
        return 'muted must be true or false', False
    kinds = _muted()
    if on:
        kinds.add(kind)
    else:
        kinds.discard(kind)
    try:
        _ensure_data_dir()
        saved = muted.save(_muted_path(), kinds)
    except (IOError, OSError) as e:
        return 'Could not save the setting: %s' % e, False
    if on and os.path.exists(DB_PATH):
        import store
        conn = store.connect(DB_PATH)
        try:
            with conn:
                conn.execute("UPDATE events SET acknowledged = 1 "
                             "WHERE source = 'wids' AND kind = ? AND acknowledged = 0", (kind,))
        finally:
            conn.close()
    return {'muted': saved}


# --------------------------------------------------------------------------
# My networks (kept in their own file: "Clear collected data" does not touch them)
# --------------------------------------------------------------------------

def _mynets_path():
    return os.path.join(DATA_DIR, 'my_networks.json')


def _my_networks_reply(entries):
    return {'networks': sorted(entries.values(), key=lambda e: (e.get('ssid') or '', e['bssid']))}


@module.handles_action('get_my_networks')
def get_my_networks(request: Request):
    import mynets
    return _my_networks_reply(mynets.load(_mynets_path()))


@module.handles_action('set_my_network')
def set_my_network(request: Request):
    import mynets
    bssid = mynets.valid_bssid(getattr(request, 'bssid', None))
    mine = getattr(request, 'mine', None)
    if bssid is None:
        return 'Invalid BSSID', False
    if not isinstance(mine, bool):
        return 'Invalid value for "mine"', False
    entries = mynets.load(_mynets_path())
    if not mine:
        entries.pop(bssid, None)
    elif bssid not in entries:
        if len(entries) >= mynets.MAX_NETWORKS:
            return 'At most %d networks can be marked' % mynets.MAX_NETWORKS, False
        found = _with_db(lambda c: mynets.baseline_from_db(c, bssid), None)
        if found is None:
            return 'Not enough observations of this access point yet', False
        entries[bssid] = mynets.make_entry(bssid, found)
    try:
        mynets.save(_mynets_path(), entries)
    except (IOError, OSError) as e:
        return 'Could not save the list: %s' % e, False
    return _my_networks_reply(entries)


@module.handles_action('set_my_networks')
def set_my_networks(request: Request):
    """
    Mark or unmark several access points at once (the star at the top of the list).
    `bssids`: a list of 64 at most; `mine`: a real boolean. One write of the file.
    Access points without enough observations are skipped and listed in `refused`.
    """
    import mynets
    raw = getattr(request, 'bssids', None)
    mine = getattr(request, 'mine', None)
    if not isinstance(mine, bool):
        return 'Invalid value for "mine"', False
    if not isinstance(raw, list) or len(raw) > mynets.MAX_NETWORKS:
        return 'Invalid list of BSSIDs', False
    bssids = []
    for b in raw:
        v = mynets.valid_bssid(b)
        if v is None:
            return 'Invalid BSSID', False
        if v not in bssids:
            bssids.append(v)
    entries = mynets.load(_mynets_path())
    refused = []
    if mine:
        found = _with_db(lambda c: dict((b, mynets.baseline_from_db(c, b)) for b in bssids
                                        if b not in entries), {})
        for b in bssids:
            if b in entries:
                continue
            if len(entries) >= mynets.MAX_NETWORKS or not found.get(b):
                refused.append(b)
                continue
            entries[b] = mynets.make_entry(b, found[b])
    else:
        for b in bssids:
            entries.pop(b, None)
    try:
        mynets.save(_mynets_path(), entries)
    except (IOError, OSError) as e:
        return 'Could not save the list: %s' % e, False
    reply = _my_networks_reply(entries)
    reply['refused'] = refused
    return reply


@module.handles_action('clear_my_networks')
def clear_my_networks(request: Request):
    """Unmark every network at once. Needs confirm=True, a real boolean."""
    import mynets
    if getattr(request, 'confirm', None) is not True:
        return 'Confirmation required', False
    try:
        mynets.save(_mynets_path(), {})
    except (IOError, OSError) as e:
        return 'Could not save the list: %s' % e, False
    return _my_networks_reply({})


@module.handles_action('rebaseline_my_network')
def rebaseline_my_network(request: Request):
    """Take what the access point announces now as its reference (after a router update)."""
    import mynets
    bssid = mynets.valid_bssid(getattr(request, 'bssid', None))
    if bssid is None:
        return 'Invalid BSSID', False
    entries = mynets.load(_mynets_path())
    if bssid not in entries:
        return 'This access point is not one of your networks', False
    found = _with_db(lambda c: mynets.baseline_from_db(c, bssid), None)
    if found is None:
        return 'Not enough observations of this access point yet', False
    entries[bssid] = mynets.make_entry(bssid, found)
    try:
        mynets.save(_mynets_path(), entries)
    except (IOError, OSError) as e:
        return 'Could not save the list: %s' % e, False
    return _my_networks_reply(entries)


@module.handles_action('suggest_my_networks')
def suggest_my_networks(request: Request):
    import mynets
    bssid = mynets.valid_bssid(getattr(request, 'bssid', None))
    if bssid is None:
        return 'Invalid BSSID', False
    entries = mynets.load(_mynets_path())
    return {'suggestions': _with_db(lambda c: mynets.suggestions(c, bssid, entries), [])}


@module.handles_action('ack_events')
def ack_events(request: Request):
    if not os.path.exists(DB_PATH):
        return True
    import store
    conn = store.connect(DB_PATH)
    try:
        with conn:
            conn.execute('UPDATE events SET acknowledged = 1 WHERE acknowledged = 0')
    finally:
        conn.close()
    return True


if __name__ == '__main__':
    module.start()
