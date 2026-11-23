#!/bin/bash
# PineappleTAK - connects the WiFi Pineapple Mark VII to a TAK Server.
#
# Headless service (/etc/init.d/pineappletak). It runs PagerTAK's engine, sensors and
# web console (core/, shared with PagerTAK) with the Mark VII device layer (mk7/).
# Everything is used from the web console; the Pineapple UI module starts and stops
# this service and opens the console.
#
# Folders:  /root/pineappletak          this folder (code + certs, zones, markers, web password)
#           /etc/pineappletak           settings (one file per key)
#           /root/loot/PineappleTAK     chat, reports, sensor logs
#           /tmp/pineappletak           live state

PTAK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PTAK_VERSION="1.0.2"
export PATH="$PTAK_DIR/mk7/bin:$PATH"       # _pineap and sqlite3 stand-ins (see mk7/bin)

# 1. Stand-ins for the Pager's DuckyScript commands, then the shared core's functions
# shellcheck source=mk7/device.sh
. "$PTAK_DIR/mk7/device.sh"
_PAYLOAD_HOME="$PTAK_DIR/core"
eval "$(sed -n '1,/^# Main$/p' "$PTAK_DIR/core/payload.sh")"

# 2. Mark VII paths and names (before the core's modules read them)
RUN="/tmp/pineappletak"
LOOT_DIR="/root/loot/PineappleTAK"
PAYLOAD_VERSION="$PTAK_VERSION"
CFG_NS="pineappletak"
PRODUCT_NAME="PineappleTAK"
LOG_TMP="/tmp/pineappletak"                 # logs: /tmp/pineappletak-web.log, -enroll.log...
CERT_LOG="$LOG_TMP-cert.log"
CALLSIGN="Pineapple-MKVII"                 # default callsign until you set one
PTAK_PIDFILE="/var/run/pineappletak.pid"

# 3. Start-up (as the core's Main, without the Pager screen)
# A restart can begin before the previous instance has finished cleaning up: wait for it
old=$(cat "$PTAK_PIDFILE" 2>/dev/null)
if [ -n "$old" ] && [ "$old" != $$ ] && kill -0 "$old" 2>/dev/null; then
    kill "$old" 2>/dev/null
    for _ in $(seq 1 20); do kill -0 "$old" 2>/dev/null || break; sleep 0.5; done
fi
echo $$ > "$PTAK_PIDFILE"
rm -rf "$RUN"; mkdir -p "$RUN/outbox" "$RUN/tracks.d" "$LOOT_DIR"
echo $$ > "$RUN/owner"
# this device's TAK UID, made once (the core would name it PagerTAK-...)
[ -n "$(cfg_get uid "")" ] || cfg_set uid "PineappleTAK-$(head -c 8 /proc/sys/kernel/random/uuid)"
load_config
WEB_LOADED=0; SETUP_LOADED=0
# shellcheck source=core/include/web.sh
. "$PAYLOAD_DIR/include/web.sh" && WEB_LOADED=1
# shellcheck source=core/include/setup.sh
. "$PAYLOAD_DIR/include/setup.sh" && SETUP_LOADED=1
# Mark VII overrides of core functions
PTAK_STAGE=after
# shellcheck source=mk7/device.sh
. "$PTAK_DIR/mk7/device.sh"
[ "$(cfg_get web "")" = "" ] && cfg_set web 1             # the console is the Mark VII's screen

if [ ! -s "$WEB_AUTH" ]; then
    LOG red "No web console password yet - set one in the Pineapple UI (Modules > PineappleTAK)"
    exit 3
fi
web_install >/dev/null 2>&1

if [ "$(cfg_get configured 0)" != 1 ] || [ "$C_HOST" = "tak.example.com" ]; then
    LOG "Not set up yet - starting the web console in setup mode"
    setup_in_browser || { LOG red "Setup did not finish"; exit 0; }
fi
if [ "$C_PROTO" = "tls" ]; then
    setup_certs || { LED FAIL; LOG red "TLS certificates are not ready - see Settings in the web console"; exit 0; }
    cert_expiry_check
fi

trap cleanup EXIT
trap 'exit 0' TERM INT

for m in reports watch trackers remoteid survey sigint watchdog geofence; do
    [ -f "$PAYLOAD_DIR/include/$m.sh" ] || continue
    # shellcheck disable=SC1090
    . "$PAYLOAD_DIR/include/$m.sh" || continue
    case $m in
        reports) REPORTS_LOADED=1 ;; watch) WATCH_LOADED=1 ;; trackers) TRK_LOADED=1 ;;
        remoteid) RID_LOADED=1 ;; survey) SURVEY_LOADED=1 ;; sigint) SIGINT_LOADED=1 ;;
        watchdog) MD_LOADED=1 ;; geofence) GEO_LOADED=1 ;;
    esac
done
ptak_modules_loaded
if [ "${SURVEY_LOADED:-0}" = 1 ]; then for d in "$SURVEY_ROOT"/*/active; do [ -e "$d" ] && rm -f "$d"; done; fi

gps_loop > /dev/null 2>&1 &
GPS_PID=$!
engine &
ENGINE_PID=$!
echo "$ENGINE_PID" > "$RUN/engine.pid"
[ "${WATCH_LOADED:-0}" = 1 ] && [ "$(cfg_get watch 0)" = 1 ] && { watch_start || LOG yellow "Evil-twin watch is ON but the recon database is not available"; }
[ "${TRK_LOADED:-0}" = 1 ] && [ "$(cfg_get trk 0)" = 1 ] && { trk_start || LOG yellow "Tracker watch is ON but no Bluetooth adapter / tools were found"; }
[ "${RID_LOADED:-0}" = 1 ] && [ "$(cfg_get rid 0)" = 1 ] && { rid_start || LOG yellow "Drone watch is ON but could not start"; }
[ "${GEO_LOADED:-0}" = 1 ] && [ -s "$GEO_FILE" ] && geo_start
prune_loop > /dev/null 2>&1 &
echo $! > "$RUN/prune.pid"
[ "${MD_LOADED:-0}" = 1 ] && [ "$(cfg_get md 0)" = 1 ] && { : > "$RUN/activity"; md_start; }
if ! web_running; then
    web_start || LOG red "The web console did not start (see $WEB_LOG)"
fi
web_cfg_write
LOG green "PineappleTAK $PTAK_VERSION - $C_CALLSIGN - $(web_urls | head -n1)"

# Runs until the service is stopped (procd sends TERM)
while [ ! -f "$RUN/stop" ]; do
    sleep 5
    kill -0 "$ENGINE_PID" 2>/dev/null || { LOG red "Engine stopped - restarting"; engine & ENGINE_PID=$!; echo "$ENGINE_PID" > "$RUN/engine.pid"; }
done
