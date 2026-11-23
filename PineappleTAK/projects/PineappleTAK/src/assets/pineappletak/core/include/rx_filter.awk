# PagerTAK - incoming CoT pre-filter (busybox awk)
#
# Reads the raw stream from the TAK Server and prints one event per line for
# the Bash handler. awk reads in large blocks, while Bash reads a pipe one
# byte at a time, so on a busy server (aircraft, AIS, lightning, traffic
# feeds...) the Bash reader fell minutes behind: chats and contacts arrived
# late and contacts went stale. Here:
#   - chats, alerts, deletes, file shares and other non-position events always pass
#   - TAK users (events with <takv> or an endpoint) always pass
#   - other position items (feeds, markers) pass at most once per MIN_SEC per uid
# Usage: awk -v MIN_SEC=10 -f rx_filter.awk
BEGIN { RS = ">"; if (MIN_SEC == "") MIN_SEC = 10; now = uptime(); n = 0 }

function uptime(   l, a) {
    l = ""
    if ((getline l < "/proc/uptime") > 0) { close("/proc/uptime"); split(l, a, " "); return int(a[1]) }
    close("/proc/uptime")
    return 0
}

{
    buf = buf $0 ">"
    if ($0 !~ /<\/event$/) {
        if (length(buf) > 65536) buf = ""
        next
    }
    i = index(buf, "<event")
    ev = (i > 0) ? substr(buf, i) : ""
    buf = ""
    if (ev == "") next
    if (++n % 50 == 0) now = uptime()
    type = ""; uid = ""
    if (match(ev, /type=["'][^"']*/)) type = substr(ev, RSTART + 6, RLENGTH - 6)
    if (match(ev, /uid=["'][^"']*/)) uid = substr(ev, RSTART + 5, RLENGTH - 5)
    if ((type ~ /^a-/ || type ~ /^b-m-p-/) && ev !~ /<takv/ && ev !~ /endpoint=/) {
        if (uid in last && now - last[uid] < MIN_SEC) {
            now = uptime()                     # the clock may be behind on a quiet stream
            if (now - last[uid] < MIN_SEC) next
        }
        last[uid] = now
        if (++tracked > 20000) { split("", last); tracked = 0 }
    }
    gsub(/[\r\n]+/, " ", ev)
    print ev
    fflush()
}
