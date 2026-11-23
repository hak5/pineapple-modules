#!/bin/bash
# PagerTAK tracker / counter-surveillance watch - sourced by payload.sh.
#
# Passive Bluetooth LE listening (hcitool lescan --passive + btmon: the Pager
# never sends scan requests) plus the Wi-Fi recon database. Detects:
#   TRACKER     Apple Find My (AirTag + Find My accessories), Tile, Samsung
#               SmartTag, Google Find My Device network tags
#   FOLLOWING   the same tracker seen for FOLLOW_MIN_SEC at FOLLOW_MIN_PLACES
#               places at least FOLLOW_MIN_DIST meters apart (you moved, it came along)
#   FLOCK       Flock Safety cameras / Penguin battery packs (BLE + Wi-Fi)
#   AXON        Axon (TASER) body cameras / devices (BLE + Wi-Fi OUIs)
# Detection only - nothing is transmitted over the air.
#
# Signatures (facts, re-implemented here):
#   Find My:  Apple company ID 76, advertisement type 0x12 (btmon "Type: Unknown (18)")
#   Tile:     service UUID 0xFEED / 0xFEEC        SmartTag: 0xFD5A
#   Google FMDN: service data 0xFEAA with frame 0x40/0x41
#   Flock:    BLE names flock / penguin / fs ext battery, company ID 0x09C8 (2504),
#             OUI b4:1e:52; Wi-Fi SSIDs Flock-* / Penguin-*
#             (from Flock-You by colonelpanichacks, MIT)
#   Axon:     OUIs 00:25:DF 00:58:28 00:C0:D4 84:70:03, company "TASER"
#             (OUIs as credited in the BluePine payload by cncartist)

TRK_INTERVAL=${TRK_INTERVAL:-60}     # seconds between scans
TRK_LISTEN=${TRK_LISTEN:-12}          # seconds listening per scan
TRK_IFACE=${TRK_IFACE:-hci0}
FOLLOW_MIN_SEC=${FOLLOW_MIN_SEC:-600}
FOLLOW_MIN_PLACES=${FOLLOW_MIN_PLACES:-3}
FOLLOW_MIN_DIST=${FOLLOW_MIN_DIST:-200}
TRK_LOG="$LOOT_DIR/trackers.log"
TRK_IGNORE="$PAYLOAD_DIR/watch/trackers.ignore"
AXON_OUIS="00:25:df 00:58:28 00:c0:d4 84:70:03"
FLOCK_OUIS="b4:1e:52"

trk_requirements() {
    command -v btmon >/dev/null 2>&1 && command -v hcitool >/dev/null 2>&1 && return 0
    local r id
    r=$(CONFIRMATION_DIALOG "Tracker watch needs Bluetooth tools (bluez-utils). Install now? (internet)")
    [ "$r" = "$DUCKYSCRIPT_USER_CONFIRMED" ] || return 1
    id=$(START_SPINNER "Installing"); { opkg update; opkg install bluez-utils; } >> ${LOG_TMP:-/tmp/pagertak}-bt-install.log 2>&1; STOP_SPINNER "$id"
    command -v btmon >/dev/null 2>&1 && command -v hcitool >/dev/null 2>&1 && return 0
    ERROR_DIALOG "Could not install bluez-utils. See ${LOG_TMP:-/tmp/pagertak}-bt-install.log"
    return 1
}

# Parse btmon text on stdin -> lines: mac|kind|name|rssi   (only interesting devices)
trk_parse_btmon() {
    awk -v axon="$AXON_OUIS" -v flock="$FLOCK_OUIS" '
    function emit(   k, oui, n) {
        if (mac == "") return
        oui = tolower(substr(mac, 1, 8)); n = tolower(name)
        k = ""
        if (findmy) k = "FINDMY"
        else if (tile) k = "TILE"
        else if (smarttag) k = "SMARTTAG"
        else if (fmdn) k = "GOOGLEFMDN"
        else if (index(" " flock " ", " " oui " ") || cid == 2504 || n ~ /flock|penguin|fs ext battery/) k = "FLOCK"
        else if (index(" " axon " ", " " oui " ") || tolower(company) ~ /taser/) k = "AXON"
        if (k != "") printf "%s|%s|%s|%s\n", toupper(mac), k, name, rssi
        mac = ""
    }
    function reset() { mac = ""; name = ""; company = ""; cid = -1; apple = 0; findmy = 0; tile = 0; smarttag = 0; feaa = 0; fmdn = 0; rssi = "" }
    BEGIN { reset() }
    /Advertising Report|Extended Advertising Report/ { if (mac != "") emit(); reset() }
    /^[[:space:]]+Address: [0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]/ && mac == "" { match($0, /[0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]/); mac = substr($0, RSTART, RLENGTH) }
    /^[[:space:]]+Company: / {
        company = $0; sub(/^[[:space:]]+Company: /, "", company)
        if (match(company, /\(([0-9]+)\)$/)) cid = substr(company, RSTART + 1, RLENGTH - 2) + 0
        apple = (cid == 76)
    }
    /Type: [^(]*\(18\)/ && apple { findmy = 1 }
    /\(0xfeed\)|\(0xfeec\)/ { tile = 1 }
    /\(0xfd5a\)/ { smarttag = 1 }
    /Service Data: .*\(0xfeaa\)/ { feaa = 1; next }
    feaa == 1 && /Data: / { d = $0; sub(/.*Data: /, "", d); if (d ~ /^4[01]/) fmdn = 1; feaa = 0 }
    /Name \((complete|short)\): / { name = $0; sub(/.*Name \((complete|short)\): /, "", name); gsub(/\|/, "/", name) }
    /^[[:space:]]+RSSI: -?[0-9]+ dBm/ { match($0, /-?[0-9]+ dBm/); rssi = substr($0, RSTART, RLENGTH - 4); emit(); reset() }
    END { emit() }'
}

# Wi-Fi side from the recon DB (Flock / Axon) -> mac|kind|ssid|rssi
trk_wifi_hits() {
    local db since=$1 q
    db=$(recon_db 2>/dev/null) || return 0
    command -v sqlite3 >/dev/null 2>&1 || return 0
    q="SELECT lower(bssid), CAST(ssid AS TEXT), MAX(signal) FROM ssid WHERE type=8 AND time>=$since GROUP BY lower(bssid)
       UNION ALL SELECT lower(w.mac), CAST(s.ssid AS TEXT), MAX(s.signal) FROM ssid s JOIN wifi_device w ON s.wifi_device=w.hash
       WHERE s.type=4 AND s.time>=$since GROUP BY lower(w.mac);"
    timeout 8 sqlite3 -readonly -separator '|' -cmd ".timeout 2000" "$db" "$q" 2>/dev/null | awk -F'|' -v axon="$AXON_OUIS" -v flock="$FLOCK_OUIS" '
        { m = $1; if (length(m) == 12) m = substr(m,1,2) ":" substr(m,3,2) ":" substr(m,5,2) ":" substr(m,7,2) ":" substr(m,9,2) ":" substr(m,11,2)
          oui = substr(m, 1, 8); s = tolower($2); k = ""
          if (index(" " flock " ", " " oui " ") || s ~ /^(flock|penguin)-/) k = "FLOCK"
          else if (index(" " axon " ", " " oui " ")) k = "AXON"
          if (k != "") printf "%s|%s|%s|%s\n", toupper(m), k, $2, $3 }'
}

trk_kind_name() {
    case "$1" in
        FINDMY) echo "Apple Find My tracker (AirTag/compatible)" ;; TILE) echo "Tile tracker" ;;
        SMARTTAG) echo "Samsung SmartTag" ;; GOOGLEFMDN) echo "Google Find My Device tag" ;;
        FLOCK) echo "Flock Safety camera/battery" ;; AXON) echo "Axon (TASER) device" ;; *) echo "$1" ;;
    esac
}
trk_is_tracker() { case "$1" in FINDMY|TILE|SMARTTAG|GOOGLEFMDN) return 0 ;; esac; return 1; }

# trk_following mac -> 0 if the sightings show it travelling with us
trk_following() {
    local f="$RUN/trk/${1//:/}.sight"
    [ -f "$f" ] || return 1
    awk -v mins="$FOLLOW_MIN_SEC" -v places="$FOLLOW_MIN_PLACES" -v dist="$FOLLOW_MIN_DIST" '
        function rad(d) { return d * 3.14159265358979 / 180 }
        function hav(a1, o1, a2, o2,   p1, p2, dp, dl, h) { p1 = rad(a1); p2 = rad(a2); dp = p2 - p1; dl = rad(o2 - o1)
            h = sin(dp/2)^2 + cos(p1)*cos(p2)*sin(dl/2)^2; return 2 * 6371000 * atan2(sqrt(h), sqrt(1-h)) }
        $2 == "-" { next }
        { if (first == "") first = $1; last = $1
          ok = 1; for (i = 1; i <= n; i++) if (hav(la[i], lo[i], $2, $3) < dist) { ok = 0; break }
          if (ok) { n++; la[n] = $2; lo[n] = $3 } }
        END { exit !((last - first) >= mins && n >= places) }' "$f"
}

trk_alert() {  # trk_alert LEVEL mac kind name rssi
    local level=$1 mac=$2 kind=$3 name=$4 rssi=$5 label cs rem chat type uid
    label=$(trk_kind_name "$kind")
    best_position || { P_LAT=0; P_LON=0; }
    case "$level" in
        FOLLOWING) type="a-h-G"; cs="FOLLOWING: $kind"; chat="ALERT: $label appears to be FOLLOWING $C_CALLSIGN ($mac, seen across multiple locations)" ;;
        *)         type="a-u-G"; cs="$kind ${mac: -5}"; chat="$label near $C_CALLSIGN: $mac${name:+ \"$name\"} ${rssi:+${rssi}dBm}" ;;
    esac
    uid="$PRODUCT_NAME-trk-${mac//:/}"
    rem="$level - $label
MAC: $mac${name:+  Name: $name}
Signal: ${rssi:-?} dBm  Detected by: $C_CALLSIGN  $(date '+%F %T')
Marker = where $C_CALLSIGN heard it."
    if [ "$(cfg_get trk_send 1)" = 1 ]; then
        [ "$P_LAT" != 0 ] && queue_cot "$(report_marker_xml "$uid" "$type" "$cs" "$P_LAT" "$P_LON" "$rem" "" 3600)"
        queue_cot "$(cot_chat "$chat")"
        chat_log "OUT [All] $C_CALLSIGN: $chat"
    fi
    [ "$P_LAT" != 0 ] && track_seen "$uid" "$P_LAT" "$P_LON" "$cs" "$type" "" "marker"
    mkdir -p "$LOOT_DIR"; echo "$(date '+%F %T') $level $kind $mac name='$name' rssi=$rssi pos=$P_LAT,$P_LON" >> "$TRK_LOG"
    printf '%s|%s|%s|%s|%s\n' "$(date +%s)" "$level" "$mac" "$kind" "$name" >> "$RUN/trk_alerts"
    if [ "$level" = FOLLOWING ]; then
        LOG red "FOLLOWING: $label $mac"; RINGTONE alert >/dev/null 2>&1 &
        ALERT "TRACKER FOLLOWING YOU
$label
$mac" >/dev/null 2>&1 &
    else
        LOG yellow "$label: $mac${name:+ $name}"; RINGTONE warning >/dev/null 2>&1 &
    fi
}

trk_scan_once() {
    local out="$RUN/btmon.txt" now mac kind name rssi key last level since
    now=$(date +%s); mkdir -p "$RUN/trk"
    hciconfig "$TRK_IFACE" up >/dev/null 2>&1
    timeout -s INT $((TRK_LISTEN + 2)) btmon > "$out" 2>/dev/null &
    local bp=$!
    sleep 1
    timeout -s INT "$TRK_LISTEN" hcitool -i "$TRK_IFACE" lescan --passive --duplicates >/dev/null 2>&1
    wait "$bp" 2>/dev/null
    since=$((now - TRK_INTERVAL - 30))
    best_position || { P_LAT="-"; P_LON="-"; }
    while IFS='|' read -r mac kind name rssi; do
        [ -z "$mac" ] && continue
        grep -qix "$mac" "$TRK_IGNORE" 2>/dev/null && continue
        key="${mac//:/}"
        echo "$now $P_LAT $P_LON $rssi" >> "$RUN/trk/$key.sight"
        [ -f "$RUN/trk/$key.kind" ] || echo "$kind|$name" > "$RUN/trk/$key.kind"
        level=""
        if trk_is_tracker "$kind"; then
            if [ "$(cfg_get trk_follow 1)" = 1 ] && trk_following "$mac"; then level=FOLLOWING
            elif [ "$(cfg_get trk_any 0)" = 1 ]; then level=TRACKER; fi
        elif [ "$(cfg_get trk_flockaxon 1)" = 1 ]; then
            level=$kind
        fi
        [ -z "$level" ] && continue
        last=$(cat "$RUN/trk/$key.$level" 2>/dev/null || echo 0)
        if [ "$level" = FOLLOWING ]; then [ $((now - last)) -lt 1800 ] && continue
        else [ $((now - last)) -lt 3600 ] && continue; fi
        echo "$now" > "$RUN/trk/$key.$level"
        trk_alert "$level" "$mac" "$kind" "$name" "$rssi"
    done < <( { trk_parse_btmon < "$out"; trk_wifi_hits "$since"; } | sort -u -t'|' -k1,1)
    # keep sighting files small
    find "$RUN/trk" -name '*.sight' -size +8k -exec sh -c 'tail -n 60 "$1" > "$1.t" && mv "$1.t" "$1"' _ {} \; 2>/dev/null
}

trk_loop() {
    trap 'exit 0' TERM INT
    LOG green "Tracker watch ON (passive BLE listening)"
    while [ ! -f "$RUN/stop" ] && [ "$(cfg_get trk 0)" = 1 ]; do
        trk_scan_once
        sleep $(( TRK_INTERVAL > TRK_LISTEN ? TRK_INTERVAL - TRK_LISTEN : 1 ))
    done
}
trk_start() { trk_stop; command -v btmon >/dev/null 2>&1 || return 1; trk_loop & echo $! > "$RUN/trk.pid"; }
trk_stop() { local p; p=$(cat "$RUN/trk.pid" 2>/dev/null); [ -n "$p" ] && kill "$p" 2>/dev/null; rm -f "$RUN/trk.pid"; }
trk_running() { kill -0 "$(cat "$RUN/trk.pid" 2>/dev/null)" 2>/dev/null; }

trk_toggle() {
    if [ "$(cfg_get trk 0)" = 1 ]; then cfg_set trk 0; trk_stop; LOG yellow "Tracker watch OFF"
    else trk_requirements || return; cfg_set trk 1; trk_start || LOG red "Could not start tracker watch"; fi
}

# Recent detections this session, nearest-first by signal; pick one to ignore
trk_recent() {
    local rows=() items=() i r f mac kind name n first dur
    for f in "$RUN"/trk/*.kind; do
        [ -f "$f" ] || continue
        mac=$(basename "$f" .kind | sed 's/../&:/g; s/:$//'); IFS='|' read -r kind name < "$f"
        n=$(wc -l < "${f%.kind}.sight" 2>/dev/null || echo 0)
        first=$(head -n1 "${f%.kind}.sight" | cut -d' ' -f1); dur=$(( ($(date +%s) - ${first:-$(date +%s)}) / 60 ))
        rows+=("$mac"); items+=("$kind ${mac: -8}${name:+ $name} x$n ${dur}m")
    done
    [ ${#rows[@]} -eq 0 ] && { LOG "No trackers / devices detected yet"; return; }
    r=$(LIST_PICKER "Detected (pick to ignore)" "${items[@]}" "< Back" "< Back"); picker_ok $? || return
    [ "$r" = "< Back" ] && return
    for i in "${!items[@]}"; do
        if [ "${items[$i]}" = "$r" ] && [ "$(CONFIRMATION_DIALOG "Ignore ${rows[$i]} from now on? (e.g. your own or a teammate's tag)")" = "$DUCKYSCRIPT_USER_CONFIRMED" ]; then
            mkdir -p "$(dirname "$TRK_IGNORE")"; echo "${rows[$i]}" >> "$TRK_IGNORE"; LOG green "Ignoring ${rows[$i]}"
        fi
    done
}

trk_options() {
    local r f a fa s
    while :; do
        f="Following alerts: $([ "$(cfg_get trk_follow 1)" = 1 ] && echo On || echo Off)"
        a="Every tracker seen: $([ "$(cfg_get trk_any 0)" = 1 ] && echo On || echo Off)"
        fa="Flock / Axon alerts: $([ "$(cfg_get trk_flockaxon 1)" = 1 ] && echo On || echo Off)"
        s="Send alerts to TAK: $([ "$(cfg_get trk_send 1)" = 1 ] && echo On || echo Off)"
        r=$(LIST_PICKER "Tracker alerts" "$f" "$a" "$fa" "$s" "Clear ignore list" "< Back" "$f"); picker_ok $? || return
        case "$r" in
            "Following"*)  cfg_set trk_follow "$([ "$(cfg_get trk_follow 1)" = 1 ] && echo 0 || echo 1)" ;;
            "Every"*)      cfg_set trk_any "$([ "$(cfg_get trk_any 0)" = 1 ] && echo 0 || echo 1)" ;;
            "Flock"*)      cfg_set trk_flockaxon "$([ "$(cfg_get trk_flockaxon 1)" = 1 ] && echo 0 || echo 1)" ;;
            "Send"*)       cfg_set trk_send "$([ "$(cfg_get trk_send 1)" = 1 ] && echo 0 || echo 1)" ;;
            "Clear ignore list") rm -f "$TRK_IGNORE"; LOG yellow "Ignore list cleared" ;;
            *) return ;;
        esac
    done
}

menu_trackers() {
    local r st last
    while :; do
        if [ "$(cfg_get trk 0)" = 1 ] && trk_running; then st="Tracker watch: ON"; else st="Tracker watch: OFF"; fi
        r=$(LIST_PICKER "Trackers / counter-surv" "$st" "Detected devices" "Alert options" "< Back" "${last:-$st}"); picker_ok $? || return
        last=$r
        case "$r" in
            "Tracker watch:"*) trk_toggle ;;
            "Detected devices") trk_recent ;;
            "Alert options")    trk_options ;;
            *) return ;;
        esac
    done
}
