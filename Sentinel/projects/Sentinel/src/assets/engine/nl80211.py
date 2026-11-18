"""
Sentinel - change a monitor interface's channel through nl80211 directly.

`iw dev <iface> set channel <n>` does the same, but starting a process about three
times a second costs a lot on the Mark VII's single core. This sends the very
message `iw` sends (NL80211_CMD_SET_WIPHY with the interface index, the frequency
and "20 MHz, no HT") over a generic netlink socket, and reads the kernel's answer.

It only tunes the receiver: nothing is transmitted over the air. The `send` calls
below write to a local netlink socket, to the device's own kernel, exactly as `iw`
does; the capture socket (AF_PACKET, engine.py) is still only ever read. Standard
library only. If anything here does not work on a device, the channel hopper falls
back to `iw`.
"""

import errno
import os
import socket
import struct

NETLINK_GENERIC = 16
GENL_ID_CTRL = 0x10
CTRL_CMD_GETFAMILY = 3
CTRL_ATTR_FAMILY_ID = 1
CTRL_ATTR_FAMILY_NAME = 2
NLM_F_REQUEST = 0x1
NLM_F_ACK = 0x4
NLMSG_ERROR = 0x2

NL80211_CMD_SET_WIPHY = 2
NL80211_ATTR_IFINDEX = 3
NL80211_ATTR_WIPHY_FREQ = 38
NL80211_ATTR_WIPHY_CHANNEL_TYPE = 39
NL80211_CHAN_NO_HT = 0


def channel_freq(ch):
    """MHz of a 2.4 or 5 GHz channel number, or None."""
    if ch == 14:
        return 2484
    if 1 <= ch <= 13:
        return 2407 + 5 * ch
    if 32 <= ch <= 177:
        return 5000 + 5 * ch
    return None


def _attr(atype, payload):
    data = struct.pack('=HH', 4 + len(payload), atype) + payload
    return data + b'\x00' * ((4 - len(data) % 4) % 4)


def _message(family, cmd, seq, attrs, version=0):
    genl = struct.pack('=BBH', cmd, version, 0)
    body = genl + b''.join(attrs)
    return struct.pack('=IHHII', 16 + len(body), family, NLM_F_REQUEST | NLM_F_ACK, seq, 0) + body


def set_channel_message(family, ifindex, freq, seq=1):
    """The message `iw dev <iface> set channel <n>` sends (20 MHz, no HT)."""
    return _message(family, NL80211_CMD_SET_WIPHY, seq, [
        _attr(NL80211_ATTR_IFINDEX, struct.pack('=I', ifindex)),
        _attr(NL80211_ATTR_WIPHY_FREQ, struct.pack('=I', freq)),
        _attr(NL80211_ATTR_WIPHY_CHANNEL_TYPE, struct.pack('=I', NL80211_CHAN_NO_HT)),
    ])


def parse_ack(data, seq):
    """0 when the kernel accepted request `seq`, else a negative errno (None: not our answer)."""
    offset = 0
    while offset + 16 <= len(data):
        length, mtype, _flags, mseq, _pid = struct.unpack_from('=IHHII', data, offset)
        if length < 16:
            return None
        if mtype == NLMSG_ERROR and mseq == seq and offset + 20 <= len(data):
            return struct.unpack_from('=i', data, offset + 16)[0]
        offset += (length + 3) & ~3
    return None


class Nl80211(object):
    """One socket per channel hopper (each runs in its own thread)."""

    def __init__(self, timeout=1.0):
        self.sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_GENERIC)
        self.sock.bind((0, 0))
        self.sock.settimeout(timeout)
        self.seq = 0
        self.family = self._family('nl80211')
        self._ifindex = {}

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _request(self, msg_for_seq):
        self.seq = (self.seq + 1) & 0x7fffffff or 1
        self.sock.send(msg_for_seq(self.seq))  # to the local kernel, not over the air
        while True:
            data = self.sock.recv(65536)
            code = parse_ack(data, self.seq)
            if code is not None:
                return code, data

    def _family(self, name):
        payload = name.encode() + b'\x00'

        def build(seq):
            return _message(GENL_ID_CTRL, CTRL_CMD_GETFAMILY, seq,
                            [_attr(CTRL_ATTR_FAMILY_NAME, payload)], version=1)
        self.seq += 1
        self.sock.send(build(self.seq))  # to the local kernel, not over the air
        while True:
            data = self.sock.recv(65536)
            length, mtype = struct.unpack_from('=IH', data)
            if mtype == NLMSG_ERROR:
                code = struct.unpack_from('=i', data, 16)[0]
                if code:
                    raise OSError(-code, os.strerror(-code))
                continue  # the ack that follows the answer
            offset = 20
            while offset + 4 <= length:
                alen, atype = struct.unpack_from('=HH', data, offset)
                if alen < 4:
                    break
                if atype == CTRL_ATTR_FAMILY_ID:
                    return struct.unpack_from('=H', data, offset + 4)[0]
                offset += (alen + 3) & ~3
            raise OSError(errno.ENOENT, 'nl80211 family not found')

    def set_channel(self, iface, ch):
        """True when the kernel accepted the channel; False otherwise (refused, busy...)."""
        freq = channel_freq(ch)
        if freq is None:
            return False
        if iface not in self._ifindex:
            self._ifindex[iface] = socket.if_nametoindex(iface)
        code, _ = self._request(lambda seq: set_channel_message(self.family, self._ifindex[iface], freq, seq))
        if code == -errno.ENODEV:
            self._ifindex.pop(iface, None)  # the interface was recreated: look it up next time
        return code == 0
