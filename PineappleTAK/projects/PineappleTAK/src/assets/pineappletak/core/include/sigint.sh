#!/bin/bash
# PagerTAK SIGINT helpers - sourced by payload.sh. Receive-only.
#
#   Radio control  lock the Wi-Fi monitor radio (wlan1mon) to one channel, or
#                  hand it back to recon hopping (fast / slow).
#   Fox hunt       follow one MAC address by signal strength, with a trail of
#                  readings at your GPS position (strongest reading marked).
#
# Uses the Pager's own tools: _pineap INTERFACE / MONITOR and the
# PINEAPPLE_EXAMINE_* DuckyScript commands, as in Hak5's Device Hunter payload.
#
# Runtime files ($RUN):
#   radio.owner   who locked the radio ("web ch 6", "fox aa:bb:..")
#   fox.pid / fox_mon.pid, fox.raw (monitor output), fox.cur, fox.track

SIG_IF="wlan1mon"

valid_mac() { [[ $1 =~ ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$ ]]; }

radio_set() {  # radio_set lock N | fast | slow   -> prints result line
    local what=$1 ch=$2
    if [ -f "$RUN/rid_worker.pid" ] && kill -0 "$(cat "$RUN/rid_worker.pid")" 2>/dev/null; then
        echo "err|Drone watch is using the radio (channel $(cfg_get rid_channel 6)). Turn it off first."; return
    fi
    fox_running && { echo "err|A fox hunt is using the radio. Stop it first."; return; }
    case "$what" in
        lock)
            [[ $ch =~ ^[0-9]+$ ]] && [ "$ch" -ge 1 ] && [ "$ch" -le 177 ] || { echo "err|Bad channel"; return; }
            if _pineap INTERFACE SET "$SIG_IF" CHANNEL "$ch" >/dev/null 2>&1 || iw dev "$SIG_IF" set channel "$ch" 2>/dev/null; then
                echo "web ch $ch" > "$RUN/radio.owner"; LOG yellow "Radio locked to channel $ch (web console)"
                echo "ok|Radio locked to channel $ch - recon only hears this channel now"
            else
                echo "err|Could not set channel $ch"
            fi ;;
        fast|slow)
            if _pineap INTERFACE SET "$SIG_IF" HOP "$what" >/dev/null 2>&1; then
                rm -f "$RUN/radio.owner"; LOG green "Radio hopping ($what)"
                echo "ok|Radio hopping all channels ($what)"
            else
                echo "err|Could not set hopping (needs _pineap)"
            fi ;;
        *) echo "err|Unknown radio action" ;;
    esac
}

fox_running() { kill -0 "$(cat "$RUN/fox.pid" 2>/dev/null)" 2>/dev/null; }

# fox_start MAC LABEL LOCK(0|1) [CHANNEL]
fox_start() {
    local mac=${1,,} label=$2 lock=$3 ch=$4 locked=""
    valid_mac "$mac" || { echo "err|Not a MAC address"; return; }
    command -v _pineap >/dev/null 2>&1 || { echo "err|Needs the _pineap tool (radio control)"; return; }
    fox_stop quiet
    if [ "$lock" = 1 ]; then
        if [ -f "$RUN/rid_worker.pid" ] && kill -0 "$(cat "$RUN/rid_worker.pid")" 2>/dev/null; then
            locked="(no channel lock: drone watch has the radio)"
        elif [[ $ch =~ ^[0-9]+$ ]] && [ "$ch" -gt 0 ]; then
            PINEAPPLE_EXAMINE_CHANNEL "$ch" 3600 >/dev/null 2>&1 && locked="locked to channel $ch"
        else
            PINEAPPLE_EXAMINE_BSSID "$mac" 3600 >/dev/null 2>&1 && locked="locked to its channel"
        fi
        [[ $locked == locked* ]] && echo "fox $mac" > "$RUN/radio.owner"
    fi
    : > "$RUN/fox.raw"; : > "$RUN/fox.track"
    printf '%s|%s|%s||||||%s\n' "$mac" "$label" "$(date +%s)" "$(date +%s)" > "$RUN/fox.cur"
    _pineap MONITOR "$mac" any rate=200 timeout=3600 > "$RUN/fox.raw" 2>&1 &
    echo $! > "$RUN/fox_mon.pid"
    fox_loop "$mac" "$label" > /dev/null 2>&1 &
    echo $! > "$RUN/fox.pid"
    LOG green "Fox hunt: $label $mac ${locked}"
    echo "ok|Hunting $mac ${locked:-(radio keeps hopping)}"
}

fox_loop() {
    local mac=$1 label=$2 start sz=0 nsz v sm best="" bl="" bo="" n=0 last="" a=() lt=0 now
    start=$(date +%s)
    while [ ! -f "$RUN/stop" ] && kill -0 "$(cat "$RUN/fox_mon.pid" 2>/dev/null)" 2>/dev/null; do
        nsz=$(wc -c < "$RUN/fox.raw" 2>/dev/null || echo 0)
        if [ "$nsz" != "$sz" ]; then
            sz=$nsz
            v=$(tail -n 5 "$RUN/fox.raw" | grep -oE -- '-[0-9]{1,3}' | tail -n 1)
            if [ -n "$v" ] && [ "$v" -gt -120 ] && [ "$v" -lt 0 ]; then
                a+=("$v"); [ ${#a[@]} -gt 3 ] && a=("${a[@]:1}")
                sm=$(( (${a[0]} + ${a[1]:-${a[0]}} + ${a[2]:-${a[0]}}) / 3 ))
                n=$((n + 1)); now=$(date +%s)
                if read_gps; then   # live fix only: a trail at a manual position means nothing
                    if [ -z "$best" ] || [ "$v" -gt "$best" ]; then best=$v; bl=$G_LAT; bo=$G_LON; fi
                    [ "$now" != "$lt" ] && { echo "$now $G_LAT $G_LON $sm" >> "$RUN/fox.track"; lt=$now; }
                else
                    { [ -z "$best" ] || [ "$v" -gt "$best" ]; } && best=$v
                fi
                last=$sm
                printf '%s|%s|%s|%s|%s|%s|%s|%s|%s\n' "$mac" "$label" "$start" "$last" "$best" "$bl" "$bo" "$n" "$now" \
                    > "$RUN/fox.cur.tmp" && mv "$RUN/fox.cur.tmp" "$RUN/fox.cur"
            fi
        fi
        sleep 1
    done
}

fox_stop() {
    local p f
    for f in "$RUN/fox.pid" "$RUN/fox_mon.pid"; do
        p=$(cat "$f" 2>/dev/null); [ -n "$p" ] && kill "$p" 2>/dev/null
        rm -f "$f"
    done
    pkill -f "_pineap MONITOR" 2>/dev/null
    if grep -q '^fox' "$RUN/radio.owner" 2>/dev/null; then
        PINEAPPLE_EXAMINE_RESET >/dev/null 2>&1 || _pineap EXAMINE CANCEL >/dev/null 2>&1
        rm -f "$RUN/radio.owner"
    fi
    [ "$1" = quiet ] || { LOG yellow "Fox hunt stopped"; echo "ok|Fox hunt stopped"; }
}
