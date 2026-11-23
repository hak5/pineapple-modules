#!/bin/bash
# PagerTAK drone Remote ID -> TAK - sourced by payload.sh.
#
# map/rid_decode.py (PagerTAK's own receiver, Python standard library only)
# passively decodes ASTM F3411 / OpenDroneID broadcasts over Wi-Fi (beacon +
# NAN, from tcpdump on wlan1mon) and Bluetooth (from btmon).
# map/rid_bridge.py turns its live state into TAK CoT on PagerTAK's connection.
#
# Note: while on, the receiver parks the Wi-Fi monitor interface (wlan1mon) on one
# channel (default 6, where Wi-Fi Remote ID beacons live) and sets it back to
# hopping on stop.

RID_WORKER="$MAP_DIR/rid_decode.py"
RID_STATE="$RUN/rid.json"
RID_LOG="$LOOT_DIR/drones.log"

rid_install() {
    local r id
    configure_python && return 0
    r=$(CONFIRMATION_DIALOG "Drone watch needs Python 3 (python3-light). Install it now? (internet)")
    [ "$r" = "$DUCKYSCRIPT_USER_CONFIRMED" ] || return 1
    id=$(START_SPINNER "Installing Python")
    { opkg update; opkg -d mmc install python3-light || opkg install python3-light; } >> ${LOG_TMP:-/tmp/pagertak}-rid-install.log 2>&1
    STOP_SPINNER "$id"
    configure_python || { ERROR_DIALOG "Python install failed. See ${LOG_TMP:-/tmp/pagertak}-rid-install.log"; return 1; }
}

rid_requirements() {
    command -v tcpdump >/dev/null 2>&1 || { ERROR_DIALOG "tcpdump is missing (opkg install tcpdump)."; return 1; }
    iw dev wlan1mon info >/dev/null 2>&1 || LOG yellow "wlan1mon not available - Bluetooth Remote ID only"
    rid_install
}

rid_start() {
    local ch scan=""
    rid_stop
    configure_python || return 1
    [ -f "$RID_WORKER" ] || { LOG red "Missing map/rid_decode.py"; return 1; }
    ch=$(cfg_get rid_channel 6)
    rm -f "$RID_STATE"
    # tracker watch already runs a passive LE scan; only start one when it is off
    { [ "$TRK_LOADED" = 1 ] && trk_running; } || scan="--ble-scan"
    PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -B "$RID_WORKER" --interface wlan1mon --channel "$ch" \
        --state "$RID_STATE" --run "$RUN" --csv "$LOOT_DIR/drones.csv" $scan \
        > ${LOG_TMP:-/tmp/pagertak}-rid-worker.log 2>&1 &
    echo $! > "$RUN/rid_worker.pid"
    PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -B "$MAP_DIR/rid_bridge.py" --state "$RID_STATE" --run "$RUN" \
        --uid "$C_UID" --product "$PRODUCT_NAME" --callsign "$C_CALLSIGN" --chat "$(cfg_get rid_chat 1)" --log "$RID_LOG" \
        > ${LOG_TMP:-/tmp/pagertak}-rid-bridge.log 2>&1 &
    echo $! > "$RUN/rid_bridge.pid"
    LOG green "Drone watch ON (Wi-Fi ch $ch + Bluetooth)"
}

rid_stop() {
    local f p
    for f in "$RUN/rid_bridge.pid" "$RUN/rid_worker.pid"; do
        p=$(cat "$f" 2>/dev/null); [ -n "$p" ] && kill "$p" 2>/dev/null   # receiver sets the Wi-Fi channel back on SIGTERM
        rm -f "$f"
    done
}
rid_running() { kill -0 "$(cat "$RUN/rid_worker.pid" 2>/dev/null)" 2>/dev/null; }

rid_toggle() {
    if [ "$(cfg_get rid 0)" = 1 ]; then
        cfg_set rid 0; rid_stop; LOG yellow "Drone watch OFF (Wi-Fi channel restored)"
    else
        rid_requirements || return
        cfg_set rid 1; rid_start || LOG red "Could not start drone watch - see ${LOG_TMP:-/tmp/pagertak}-rid-worker.log"
    fi
}

# Active drones from the worker's state: pick one to show on the map
rid_list() {
    local rows=() items=() i r
    [ -s "$RID_STATE" ] || { LOG "No Remote ID data yet"; return; }
    configure_python || return
    mapfile -t rows < <("$PYTHON_BIN" - "$RID_STATE" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
for r in s.get("records", []):
    if not r.get("has_location"):
        continue
    lat, lon = r["latitude_e7"] / 1e7, r["longitude_e7"] / 1e7
    rid = (r.get("uas_id") or r.get("mac") or "?")[-14:]
    d = ("%dm" % r["distance_m"]) if r.get("distance_m") is not None else "?"
    b = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((r.get("bearing_deg", 0) + 22.5) // 45) % 8] if r.get("bearing_deg") is not None else ""
    alt = r.get("height_m") if r.get("height_valid") else r.get("geo_altitude_m", "?")
    print("%s %s %s alt %sm%s|%.7f,%.7f" % (rid, d, b, alt, " (lost)" if r.get("is_lost") else "", lat, lon))
PY
)
    [ ${#rows[@]} -eq 0 ] && { LOG "No drones with a position yet"; return; }
    for i in "${!rows[@]}"; do items+=("${rows[$i]%%|*}"); done
    r=$(LIST_PICKER "Drones (pick = map)" "${items[@]}" "< Back" "${items[0]}"); picker_ok $? || return
    for i in "${!items[@]}"; do [ "${items[$i]}" = "$r" ] && map_view "${rows[$i]##*|}"; done
}

rid_status() {
    [ -s "$RID_STATE" ] || { LOG "Drone watch: no state yet"; return; }
    configure_python || return
    "$PYTHON_BIN" - "$RID_STATE" <<'PY' | while IFS= read -r l; do LOG white "$l"; done
import json, sys
s = json.load(open(sys.argv[1]))
print("Status: %s  active drones: %s" % (s.get("status"), s.get("active_count")))
print("Wi-Fi: %s (ch %s)  BLE: %s" % ("up" if s.get("wifi_alive") else "down", s.get("wifi_channel"), "up" if s.get("ble_alive") else "down"))
print("Frames %s / BLE %s / decoded %s" % (s.get("frames"), s.get("ble_frames"), s.get("decoded")))
for e in s.get("capture_errors", [])[-3:]:
    print("! %s" % e)
PY
}

menu_remoteid() {
    local r st last ch chat
    while :; do
        if [ "$(cfg_get rid 0)" = 1 ] && rid_running; then st="Drone watch: ON"; else st="Drone watch: OFF"; fi
        ch="Wi-Fi channel: $(cfg_get rid_channel 6)"
        chat="Chat on new drone: $([ "$(cfg_get rid_chat 1)" = 1 ] && echo On || echo Off)"
        r=$(LIST_PICKER "Drone Remote ID" "$st" "Active drones" "Receiver status" "$ch" "$chat" "< Back" "${last:-$st}"); picker_ok $? || return
        last=$r
        case "$r" in
            "Drone watch:"*)   rid_toggle ;;
            "Active drones")   rid_list ;;
            "Receiver status") rid_status ;;
            "Wi-Fi channel:"*)
                r=$(NUMBER_PICKER "Wi-Fi channel (1-13, US Remote ID: 6)" "$(cfg_get rid_channel 6)"); picker_ok $? || continue
                [[ $r =~ ^[0-9]+$ ]] && [ "$r" -ge 1 ] && [ "$r" -le 13 ] && cfg_set rid_channel "$r"
                [ "$(cfg_get rid 0)" = 1 ] && rid_start ;;
            "Chat on new drone:"*)
                cfg_set rid_chat "$([ "$(cfg_get rid_chat 1)" = 1 ] && echo 0 || echo 1)"
                [ "$(cfg_get rid 0)" = 1 ] && rid_start ;;
            *) return ;;
        esac
    done
}
