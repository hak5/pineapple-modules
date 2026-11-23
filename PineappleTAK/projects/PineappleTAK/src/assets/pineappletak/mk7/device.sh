#!/bin/bash
# PineappleTAK (WiFi Pineapple Mark VII) - device layer.
#
# PineappleTAK runs PagerTAK's engine, sensors and web console (core/) unchanged.
# This file stands in for the Pager-only pieces: the DuckyScript commands (screen,
# buttons, LED, settings store), the Pager's GPS and the Pager's _pineap tool.
# It is sourced twice by pineappletak.sh: once before the core is loaded (the
# stand-ins) and once after (overrides of core functions, with PTAK_STAGE=after).

PTAK_CONF=${PTAK_CONF:-/etc/pineappletak}       # settings: one file per key
PTAK_LOG=${PTAK_LOG:-/tmp/pineappletak.log}

if [ "${PTAK_STAGE:-before}" = before ]; then

# OpenWrt's BusyBox is often built without "timeout": a stand-in with the same
# "timeout [-s SIGNAL] SECONDS COMMAND..." form (also runs shell functions such as GPS_GET)
if ! command -v timeout >/dev/null 2>&1; then
    timeout() {
        local sig=TERM t p w rc
        [ "$1" = -s ] && { sig=$2; shift 2; }
        t=$1; shift
        "$@" 0<&0 & p=$!
        ( sleep "$t"; kill -s "$sig" "$p" 2>/dev/null ) 2>/dev/null & w=$!
        wait "$p"; rc=$?
        kill "$w" 2>/dev/null
        return $rc
    }
fi

DUCKYSCRIPT_USER_CONFIRMED=1; DUCKYSCRIPT_CANCELLED=2; DUCKYSCRIPT_REJECTED=3; DUCKYSCRIPT_ERROR=4

ptak_log() {
    printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$PTAK_LOG"
    # keep the log small (tmpfs)
    if [ "$(wc -c < "$PTAK_LOG" 2>/dev/null || echo 0)" -gt 262144 ]; then
        tail -n 1000 "$PTAK_LOG" > "$PTAK_LOG.tmp" && mv "$PTAK_LOG.tmp" "$PTAK_LOG"
    fi
}

# Screen and buttons: there are none. Messages go to the log (shown in the Pineapple UI
# module); questions are answered in the web console, so pickers return "cancelled".
LOG() { case "$1" in red|green|yellow|cyan|white|blue|magenta|gray) shift ;; esac; ptak_log "$*"; }
PROMPT() { ptak_log "NOTE: $*"; }
ERROR_DIALOG() { ptak_log "ERROR: $*"; }
ALERT() { ptak_log "ALERT: ${*//$'\n'/ }"; }
# Only reached from actions started in the web console (turning a sensor on, a test...),
# so asking again is not possible; the click in the browser is the answer.
CONFIRMATION_DIALOG() { ptak_log "OK: $*"; echo "$DUCKYSCRIPT_USER_CONFIRMED"; }
LIST_PICKER() { return 2; }
TEXT_PICKER() { return 2; }
NUMBER_PICKER() { return 2; }
START_SPINNER() { echo 0; }
STOP_SPINNER() { :; }
WAIT_FOR_INPUT() { sleep "${1:-1}"; }
RINGTONE() { :; }
VIBRATE() { :; }
UI_TAKEOVER() { return 1; }
UI_RELEASE() { :; }
BATTERY_PERCENT() { :; }          # USB powered: no battery to report
BATTERY_CHARGING() { :; }
GPS_GET() { :; }                  # replaced by gps_loop below

# Radio lock for the fox hunt (the Pager's PINEAPPLE_EXAMINE_* commands): PineAP stops
# hopping and the monitor radio stays on the channel until reset.
PINEAPPLE_EXAMINE_CHANNEL() { pineap pause >/dev/null 2>&1 && iw dev wlan1mon set channel "$1"; }
PINEAPPLE_EXAMINE_BSSID() { return 1; }      # channel of a MAC needs the recon database; the hunt then keeps hopping
PINEAPPLE_EXAMINE_RESET() { pineap unpause >/dev/null 2>&1; }

# Settings store (PAYLOAD_*_CONFIG): /etc/pineappletak/<key>, kept across reboots
PAYLOAD_GET_CONFIG() { cat "$PTAK_CONF/$2" 2>/dev/null; }
PAYLOAD_SET_CONFIG() { mkdir -p "$PTAK_CONF" && printf '%s' "$3" > "$PTAK_CONF/$2"; }
PAYLOAD_DEL_CONFIG() { rm -f "$PTAK_CONF/$2"; }

# LED: the Mark VII's red / green / blue system LEDs. "SLOW" blinks.
led_write() { [ -w "$1" ] && printf '%s' "$2" > "$1" 2>/dev/null; }
LED() {
    [ "$(PAYLOAD_GET_CONFIG x led)" = 0 ] && return 0
    local r=0 g=0 b=0 mode=${2:-SOLID} c v d
    case "$1" in
        RED) r=1 ;; GREEN) g=1 ;; BLUE) b=1 ;; YELLOW) r=1; g=1 ;; CYAN) g=1; b=1 ;;
        MAGENTA) r=1; b=1 ;; WHITE) r=1; g=1; b=1 ;; FAIL) r=1; mode=FAST ;; OFF) ;;
        *) return 0 ;;
    esac
    for c in red green blue; do
        d=/sys/class/leds/$c:system; [ -d "$d" ] || continue
        eval "v=\$${c:0:1}"
        if [ "$v" = 1 ] && [ "$mode" != SOLID ]; then
            led_write "$d/trigger" timer
            case $mode in FAST) led_write "$d/delay_on" 100; led_write "$d/delay_off" 100 ;;
                          *)    led_write "$d/delay_on" 500; led_write "$d/delay_off" 500 ;; esac
        else
            led_write "$d/trigger" none
            led_write "$d/brightness" "$([ "$v" = 1 ] && cat "$d/max_brightness" 2>/dev/null || echo 0)"
        fi
    done
}

else   # ---------------------------------------------------------------- after the core

DEVICE_NAME="WiFi Pineapple Mark VII"
DEVICE_WORD="Pineapple"                   # what messages call this device

# Position reports: the core adds "Batt N%"; the Mark VII has no battery
eval "$(declare -f cot_sa | sed '1s/^cot_sa/ptak_core_cot_sa/')"
cot_sa() { ptak_core_cot_sa | sed 's/ | Batt 0%//; s|<status battery="0"/>||'; }

# Clean-up removes the live-state folder only if this instance still owns it
eval "$(declare -f cleanup | sed '1s/^cleanup/ptak_core_cleanup/')"
cleanup() {
    if [ "$(cat "$RUN/owner" 2>/dev/null)" = "$$" ]; then
        ptak_core_cleanup
        [ "$(cat "$PTAK_PIDFILE" 2>/dev/null)" = "$$" ] && rm -f "$PTAK_PIDFILE"
    fi
}

# Web console address: the Mark VII's management network (172.16.42.1) when nothing else is found
eval "$(declare -f web_lan_ip | sed '1s/^web_lan_ip/ptak_core_web_lan_ip/')"
web_lan_ip() { ptak_core_web_lan_ip | sed 's/^172\.16\.52\.1$/172.16.42.1/'; }

# The Mark VII has no mmc install target: opkg installs go to the normal root
opkg() { if [ "$1" = -d ]; then shift 2; fi; command opkg "$@"; }

# Bluetooth tools for the tracker watch (the Mark VII also needs the kernel's Bluetooth drivers)
BT_PACKAGES="bluez-utils kmod-bluetooth"

# Overrides of functions in the core's sensor modules: called after they are loaded
ptak_modules_loaded() {
    # Recon database: wherever PineAP is set to write it (pineap.@config[0].recon_db_path)
    recon_db() {
        local d
        d=$(uci -q get pineap.@config[0].recon_db_path)
        for d in "$d" /root/recon.db /root/recon/recon.db; do [ -n "$d" ] && [ -f "$d" ] && { printf '%s' "$d"; return 0; }; done
        return 1
    }
}

# GPS: a USB GPS (u-blox and others) read as NMEA. No GPS = the manual position is used.
gps_device() {
    local d
    d=$(cfg_get gps_dev "")
    if [ -n "$d" ] && [ -c "$d" ]; then printf '%s' "$d"; return 0; fi
    for d in /dev/ttyACM0 /dev/ttyACM1 /dev/ttyUSB0 /dev/ttyUSB1; do [ -c "$d" ] && { printf '%s' "$d"; return 0; }; done
    return 1
}
gps_loop() {
    local dev pid
    while [ ! -f "$RUN/stop" ]; do
        if dev=$(gps_device); then
            stty -F "$dev" raw -echo 9600 2>/dev/null
            awk -v OUT="$RUN/gps" -v SYNC="$GPS_TIME_SYNC" -f "$PTAK_DIR/mk7/nmea.awk" < "$dev" 2>/dev/null &
            pid=$!
            echo "$dev" > "$RUN/gps.dev"
            # until the GPS is unplugged (the reader ends) or PineappleTAK stops
            while kill -0 "$pid" 2>/dev/null && [ ! -f "$RUN/stop" ] && [ -c "$dev" ]; do sleep 2; done
            kill "$pid" 2>/dev/null
            rm -f "$RUN/gps.dev"
        fi
        printf '0 - - - - - - - %s\n' "$(date +%s)" > "$RUN/gps.tmp" && mv "$RUN/gps.tmp" "$RUN/gps"
        sleep 5
    done
}

fi
