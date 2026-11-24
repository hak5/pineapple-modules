"""
Sentinel - attempts to collect the key of one of your networks (PMKID), and reconnections
right after a deauthentication burst.

What can be seen, passively:
  * a PMKID attack (hcxdumptool and the like): a device asks to join your access point,
    gets message 1 of the 4-way handshake (which carries the PMKID), never answers, and
    tries again;
  * a handshake capture: a deauthentication burst kicks your devices off, and they come
    back with a full handshake that the attacker records.
What cannot be seen: someone who only listens and waits for a device to join.

Built to avoid false alerts. An "abandoned handshake" is only counted when all of these hold:
  1. the access point is one of yours (the habits of other networks are unknown);
  2. Sentinel heard the device's own association request, at most 2 s before message 1:
     the device is within earshot, so its answer would have been heard too;
  3. no message 2 came back from that device;
  4. Sentinel heard other frames on that channel between 0.3 s and 1 s after message 1:
     it was still listening when the answer should have arrived (with channel hopping, a
     radio that left the channel proves nothing, and that case is simply not counted).
A wrong password still produces message 2, a full reconnection is not abandoned, and a
far-away device whose request was not heard does not count. Several abandoned handshakes
on one access point are needed (ATTEMPTS within WINDOW_S).

Device addresses are only kept in memory, for a few seconds, to tie the frames together.
Standard library only; never raises.
"""

import collections

ASSOC_TO_M1_S = 2.0          # association request -> message 1
LISTEN_FROM_S = 0.3          # a frame on the channel in [m1 + 0.3 s, m1 + 1 s] proves Sentinel
LISTEN_TO_S = 1.0            # was still listening when message 2 was due
ATTEMPTS = 3                 # abandoned handshakes on one of your access points...
WINDOW_S = 120.0             # ...within this time
RECONNECT_AFTER_S = 30.0     # reconnections counted after a deauthentication burst
BURST_WINDOW_S = 5.0         # the detector window that confirmed the burst (never count earlier joins)
MAX_PENDING = 512            # bounded memory against a flood of fake associations
MAX_ASSOC = 1024


class Watch(object):
    """Frame-level tracker. `frame` is called by the engine for every parsed frame."""

    def __init__(self):
        self.mine = set()
        self.heard = {}                                   # freq -> time of the last frame
        self.assoc = collections.OrderedDict()            # (ap, sta) -> time of the request
        self.pending = collections.OrderedDict()          # (ap, sta, m1 time) -> state
        self.abandoned = {}                               # ap -> deque of (time, pmkid)
        self.bursts = {}                                  # ap -> time a deauth burst was seen
        self.m1_times = {}                                # ap -> recent times of message 1
        self.found = []                                   # (time, ap, attempts, pmkid) to report
        self.reconnected = []                             # (ap, burst time, count) to report

    def set_mine(self, bssids):
        self.mine = set(bssids)

    def deauth_burst(self, ap, ts):
        """The detector saw a deauthentication burst on one of your access points."""
        if ap in self.mine:
            self.bursts[ap] = ts

    def frame(self, f, ts):
        try:
            self._frame(f, ts)
        except Exception:  # noqa: BLE001 - a hostile frame must not stop listening
            pass

    def _frame(self, f, ts):
        if f.freq:
            self.heard[f.freq] = ts
            self._listened(f.freq, ts)
        if not self.mine or f.addr1 is None:
            return
        if f.ftype == 0 and f.subtype in (0, 2):                  # (re)association request
            if f.addr1 in self.mine:
                self._remember(self.assoc, (f.addr1, f.addr2), ts, MAX_ASSOC)
            return
        if f.ftype != 2 or not f.info or 'eapol' not in f.info:
            return
        msg = f.info['eapol']['msg']
        if msg == 1 and f.from_ds and f.addr2 in self.mine:       # access point -> device
            ap, sta = f.addr2, f.addr1
            times = self.m1_times.setdefault(ap, collections.deque(maxlen=256))
            times.append(ts)
            asked = self.assoc.get((ap, sta))
            if asked is not None and 0 <= ts - asked <= ASSOC_TO_M1_S:
                key = (ap, sta)
                if key not in self.pending:
                    self._remember(self.pending, key, {'m1': ts, 'freq': f.freq, 'listened': False,
                                                       'pmkid': f.info['eapol']['pmkid']}, MAX_PENDING)
        elif msg == 2 and f.to_ds and f.addr1 in self.mine:       # device -> access point
            self.pending.pop((f.addr1, f.addr2), None)

    def _listened(self, freq, ts):
        for state in self.pending.values():
            if state['freq'] == freq and LISTEN_FROM_S <= ts - state['m1'] <= LISTEN_TO_S:
                state['listened'] = True

    @staticmethod
    def _remember(table, key, value, limit):
        table.pop(key, None)
        table[key] = value
        while len(table) > limit:
            table.popitem(last=False)

    def tick(self, now):
        """Called every window: settle the handshakes old enough, report what qualifies."""
        for key in list(self.pending):
            state = self.pending[key]
            if now - state['m1'] < LISTEN_TO_S:
                continue
            del self.pending[key]
            if state['listened']:
                q = self.abandoned.setdefault(key[0], collections.deque())
                q.append((state['m1'], state['pmkid']))
        for ap, q in list(self.abandoned.items()):
            while q and now - q[0][0] > WINDOW_S:
                q.popleft()
            if len(q) >= ATTEMPTS:
                self.found.append((now, ap, len(q), any(p for _, p in q)))
                q.clear()
            if not q:
                del self.abandoned[ap]
        for key in [k for k, t in self.assoc.items() if now - t > ASSOC_TO_M1_S + 5]:
            del self.assoc[key]
        for ap, ts in list(self.bursts.items()):
            if now - ts >= RECONNECT_AFTER_S:
                # The burst is confirmed at the end of its window: count from the window's start
                start = ts - BURST_WINDOW_S
                n = sum(1 for t in self.m1_times.get(ap, ()) if start <= t <= ts + RECONNECT_AFTER_S)
                if n:
                    self.reconnected.append((ap, ts, n))
                del self.bursts[ap]
        for ap in list(self.m1_times):
            q = self.m1_times[ap]
            while q and now - q[0] > 2 * (BURST_WINDOW_S + RECONNECT_AFTER_S):
                q.popleft()
            if not q:
                del self.m1_times[ap]
