"""
Sentinel - alert types the user has muted.

A muted alert is still recorded, so it stays in the history, but it is written as already
read: it no longer raises the unread counter, the tab badge or a dashboard's summary.
Kept in /root/.Sentinel/muted_alerts.json, next to my_networks.json. Standard library only.
"""

import json
import os

FILENAME = 'muted_alerts.json'

# Alert types that can be muted (the intrusion detection rules, see detect.py)
KINDS = ('evil_twin', 'my_ap_conflict', 'my_ap_downgrade', 'my_ap_changed', 'my_ap_channel',
         'deauth_flood', 'beacon_flood', 'karma_ap', 'pmkid_attempt')


def load(path):
    """The muted alert types. Never raises: a missing or damaged file mutes nothing."""
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        return set(k for k in data.get('kinds', []) if k in KINDS)
    except (IOError, OSError, ValueError, AttributeError, TypeError):
        return set()


def save(path, kinds):
    """Atomic write, readable by root only."""
    kinds = sorted(set(k for k in kinds if k in KINDS))
    tmp = path + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump({'version': 1, 'kinds': kinds}, fh)
    os.rename(tmp, path)
    return kinds


class Cache(object):
    """The muted types, read again only when the file changes (the engine asks every 5 s)."""

    def __init__(self, path):
        self.path = path
        self._stamp = None
        self._kinds = set()

    def get(self):
        try:
            stamp = os.stat(self.path).st_mtime
        except OSError:
            stamp = None
        if stamp != self._stamp:
            self._stamp = stamp
            self._kinds = load(self.path) if stamp is not None else set()
        return self._kinds
