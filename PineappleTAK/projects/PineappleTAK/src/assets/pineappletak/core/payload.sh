#!/bin/bash
# Title: PagerTAK
# Description: Puts the Pager on the TAK map (GPS position as CoT) with GeoChat, alerts, field reports, Wi-Fi/BLE/drone sensors and a browser web console
# Author: SECT0101
# Version: 2.3.2
# Category: General
#
# Core (no extra packages):
#   - Position reports (SA) to a TAK Server over TLS 8089 / TCP 8087 / UDP
#   - GeoChat to All Chat Rooms or one TAK user, quick messages, store-and-forward
#   - Alerts: 911 / Ring The Bell / Geo-fence Breached / Troops In Contact / Custom,
#     to everyone or chosen contacts, repeated until cancelled
#   - Field reports: SALUTE, SITREP, MEDEVAC 9-line, Damage assessment (MGRS + DTG)
#
# Requirements:
#   - A USB GPS configured under Settings > GPS (or set a manual position)
#   - A network path to your TAK Server (client Wi-Fi, USB tether, WireGuard,
#     OpenVPN, or the NetBird_VPN payload)
#   - TLS mode: openssl (opkg install openssl-util) and a TAK client certificate
#     as unencrypted PEM in certs/ (see certs/README.md, or upload it in the web console)
#
# Optional, per feature (each asks before installing anything):
#   - Map on the Pager screen, QR code: python3-light (the screen driver, map/pagerfb.py, ships with PagerTAK)
#     (downloaded pinned + SHA-256 verified), current firmware (UI_TAKEOVER); QR adds qrencode
#   - Web console (Settings > Web console): python3-light + Leaflet (pinned + verified)
#   - Sensor stats, evil-twin watch, site survey, SIGINT Wi-Fi tables: sqlite3-cli + recon running
#   - Trackers / counter-surveillance: bluez tools (btmon, hcitool)
#   - Drone Remote ID: python3-light + tcpdump (decoder included: map/rid_decode.py)
#   - Fox hunt / radio control: the Pager's own _pineap and PINEAPPLE_EXAMINE_* tools
#
# LED State Descriptions
#   Magenta Solid  - Setup / configuring
#   Cyan Slow      - Connecting to the TAK Server
#   Green Solid    - Connected, GPS fix, sending position
#   Yellow Solid   - Connected, no GPS fix (last known or manual position)
#   Red Slow       - Disconnected, retrying
#
# Controls (main screen)
#   A      - Menu: Map, Contacts, Chat >, Reports >, Sensors >, EMERGENCY 911,
#            Send position now, Status, Settings >, Exit
#   UP     - Quick message to All Chat Rooms
#   DOWN   - Type a message to All Chat Rooms
#   RIGHT  - Send position now
#   LEFT   - Status (also shows the web console address)
#   B      - Exit
#   Any button also resets the man-down watchdog timer.
#
# Files
#   include/   modules: reports, watch (evil twin), trackers, remoteid, survey,
#              sigint (radio / fox hunt), geofence, watchdog (man-down), web (console glue)
#   map/       Pager map viewer, QR screen, Remote ID bridge, survey package builder, basemaps
#   web/       web console server (Python standard library) and page
#   certs/     your TAK certificates (never commit them)
#   Saved here at run time: geofences.txt, items.txt, overlays/, tiles/, watch/, web/auth
#   Loot: /root/loot/PagerTAK (chat logs, reports, alerts, surveys)
#
# Everything under Options is a DEFAULT. Values chosen in the on-device
# setup / Settings menu (or the web console) are saved with PAYLOAD_SET_CONFIG and win over these.

# Options
TAK_HOST="tak.example.com"      # TAK Server hostname or IP (placeholder - change me)
TAK_PROTO="tls"                 # tls (8089, client cert) | tcp (8087, no auth) | udp (send-only)
TAK_PORT="8089"
CALLSIGN="PAGER-1"
TEAM="Cyan"                     # White Yellow Orange Magenta Red Maroon Purple Dark Blue Blue Cyan Teal Green Dark Green Brown
ROLE="Team Member"              # Team Member, Team Lead, HQ, Sniper, Medic, Forward Observer, RTO, K9
SA_INTERVAL="30"                # seconds between position reports
CLIENT_PEM="client.pem"         # in certs/ : client certificate + private key, unencrypted PEM
CA_PEM="ca.pem"                 # in certs/ : TAK Server CA (truststore) PEM. Missing = server not verified
CHAT_RINGTONE="bonus"           # ringtone played on incoming chat ("" = silent)
GPS_TIME_SYNC="1"               # 1 = set the clock from GPS if it is clearly wrong (TAK drops old CoT)
QUICK_MESSAGES=("Copy" "WILCO" "Say again" "Standing by" "En route" "On scene" "RTB" "Need assistance" "All clear")
                                # quick messages (can also be edited in the web console, Settings > Quick messages)
CHAT_RECEIPTS="1"               # 1 = send delivered / read receipts for direct messages (ticks in ATAK and CloudTAK)
RECON_STATS="1"                 # 1 = add Wi-Fi recon counts (APs / open APs / clients) to position reports
RECON_WINDOW="300"              # seconds of recon history counted
MAP_SOURCE="USGS Topo"          # basemap: any <name> from map/sources/*.xml (ATAK map source format)
MAP_TILE_URL="https://tiles.example.com/{z}/{x}/{y}.png"   # optional extra "Custom" basemap (placeholder)
MAP_ZOOM="15"
TRACK_MAX_AGE="1800"            # seconds before a contact/marker drops off the map and contacts list
RX_FEED_MIN_SEC="10"            # feeds and markers: use at most one update per item every N seconds (TAK users and chat: all)
COT_RADIUS_KM="0"               # only show TAK items within this many km of you (0 = everything)
WEB_PORT="8484"                 # web console port (Settings > Web console; off until you turn it on)
MANDOWN_MINUTES="10"            # man-down watchdog: minutes without movement (off until you turn it on)

#############################################################################
# Internals - no changes needed below this line
#############################################################################

PAYLOAD_VERSION="2.3.2"
DEVICE_NAME="WiFi Pineapple Pager"
PRODUCT_NAME=${PRODUCT_NAME:-PagerTAK}    # name in messages and CoT (PineappleTAK on the Mark VII)
DEVICE_WORD=${DEVICE_WORD:-Pager}          # what messages call this device
CFG_NS="pagertak"
ALL_ROOM="All Chat Rooms"
# The Pager may run a temporary copy of payload.sh (e.g. from /tmp); it passes the
# real payload folder in $_PAYLOAD_HOME. Fall back to the script's folder, then the
# standard install paths. The real folder is the one holding map/pagertak_map.py.
find_payload_dir() {
    local d
    for d in "${_PAYLOAD_HOME:-}" "${PAYLOAD_HOME:-}" "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" \
             /root/payloads/user/general/PagerTAK /mmc/root/payloads/user/general/PagerTAK; do
        [ -n "$d" ] && [ -f "$d/map/pagertak_map.py" ] && { printf '%s' "$d"; return 0; }
    done
    printf '%s' "${_PAYLOAD_HOME:-/root/payloads/user/general/PagerTAK}"
}
PAYLOAD_DIR="$(find_payload_dir)"
CERT_DIR="$PAYLOAD_DIR/certs"
LOOT_DIR="/root/loot/PagerTAK"
MAP_DIR="$PAYLOAD_DIR/map"
TILE_DIR="$PAYLOAD_DIR/tiles"
RUN="/tmp/pagertak"
QUICK_DEFAULT=("${QUICK_MESSAGES[@]}")

# bash 5.2+ treats '&' in ${var//pat/rep} as "matched text"; XML escaping needs it literal
shopt -u patsub_replacement 2>/dev/null

trap '' PIPE

# Regexes kept in variables so bash [[ =~ ]] handles < > and quotes correctly
Q="[\"']"; NQ="[^\"']"
RE_EV_TYPE="<event[^>]*[[:space:]]type=${Q}(${NQ}*)"
RE_EV_UID="<event[^>]*[[:space:]]uid=${Q}(${NQ}*)"
RE_EV_STALE="<event[^>]*[[:space:]]stale=${Q}(${NQ}*)"
RE_EV_TIME="<event[^>]*[[:space:]]time=${Q}(${NQ}*)"
RE_CONTACT_CS="<contact[^>]*[[:space:]]callsign=${Q}(${NQ}*)"
RE_SENDER_CS="senderCallsign=${Q}(${NQ}*)"
RE_CHATROOM="<__chat[^>]*[[:space:]]chatroom=${Q}(${NQ}*)"
RE_CHAT_ID="<__chat[^>]*[[:space:]]id=${Q}(${NQ}*)"
RE_MSG_ID="<__chat[^>]*[[:space:]]messageId=${Q}(${NQ}*)"
RE_UID0="<chatgrp[^>]*[[:space:]]uid0=${Q}(${NQ}*)"
RE_LINK_UID="<link[^>]*[[:space:]]uid=${Q}(${NQ}*)"
RE_REMARKS="<remarks[^>]*>([^<]*)</remarks>"
RE_EMERG="<emergency[^>]*>([^<]*)</emergency>"
RE_EMERG_TYPE="<emergency[^>]*[[:space:]]type=${Q}(${NQ}*)"
RE_PT_LAT="<point[^>]*[[:space:]]lat=${Q}(${NQ}*)"
RE_PT_LON="<point[^>]*[[:space:]]lon=${Q}(${NQ}*)"
RE_GROUP="<__group[^>]*[[:space:]]name=${Q}(${NQ}*)"

#############################################################################
# Helpers
#############################################################################

picker_ok() {
    case "$1" in
        "$DUCKYSCRIPT_CANCELLED"|"$DUCKYSCRIPT_REJECTED"|"$DUCKYSCRIPT_ERROR") return 1 ;;
    esac
    return 0
}

cfg_get() {   # cfg_get key default
    local v
    v=$(PAYLOAD_GET_CONFIG "$CFG_NS" "$1" 2>/dev/null)
    if [ -n "$v" ]; then printf '%s' "$v"; else printf '%s' "$2"; fi
}

cfg_set() { PAYLOAD_SET_CONFIG "$CFG_NS" "$1" "$2" >/dev/null 2>&1; }

load_config() {
    C_HOST=$(cfg_get host "$TAK_HOST")
    C_PROTO=$(cfg_get proto "$TAK_PROTO")
    C_PORT=$(cfg_get port "$TAK_PORT")
    C_CALLSIGN=$(cfg_get callsign "$CALLSIGN")
    C_TEAM=$(cfg_get team "$TEAM")
    C_ROLE=$(cfg_get role "$ROLE")
    C_INTERVAL=$(cfg_get interval "$SA_INTERVAL")
    C_CLIENT_PEM=$(cfg_get client_pem "$CLIENT_PEM")
    C_CA_PEM=$(cfg_get ca_pem "$CA_PEM")
    C_RINGTONE=$(cfg_get ringtone "$CHAT_RINGTONE")
    C_MANUAL=$(cfg_get manual_pos "")
    C_TILE_URL=$(cfg_get tile_url "$MAP_TILE_URL")
    C_MAP_SOURCE=$(cfg_get map_source "$MAP_SOURCE")
    C_RECON=$(cfg_get recon "$RECON_STATS")
    local q; q=$(cfg_get quick_msgs "")
    if [ -n "$q" ]; then IFS='|' read -r -a QUICK_MESSAGES <<< "$q"; else QUICK_MESSAGES=("${QUICK_DEFAULT[@]}"); fi
    C_RECEIPTS=$(cfg_get receipts "$CHAT_RECEIPTS")
    C_UID=$(cfg_get uid "")
    if [ -z "$C_UID" ]; then
        C_UID="$PRODUCT_NAME-$(head -c 8 /proc/sys/kernel/random/uuid)"
        cfg_set uid "$C_UID"
    fi
    [[ "$C_INTERVAL" =~ ^[0-9]+$ ]] && [ "$C_INTERVAL" -ge 5 ] || C_INTERVAL=30
    [ "$C_RINGTONE" = "none" ] && C_RINGTONE=""
    return 0
}

xml_esc() {
    local s=$1
    s=${s//&/&amp;}; s=${s//</&lt;}; s=${s//>/&gt;}; s=${s//\"/&quot;}; s=${s//\'/&apos;}
    s=${s//$'\n'/ }
    printf '%s' "$s"
}

xml_unesc() {
    local s=$1
    s=${s//&lt;/<}; s=${s//&gt;/>}; s=${s//&quot;/\"}; s=${s//&apos;/\'}; s=${s//&#10;/ }; s=${s//&amp;/&}
    printf '%s' "$s"
}

iso_time() { date -u -d "@$1" '+%Y-%m-%dT%H:%M:%S.000Z'; }

new_id() { cat /proc/sys/kernel/random/uuid; }

json_num() {  # json_num "<json line>" key
    local re="\"$2\":(-?[0-9.]+)"
    [[ $1 =~ $re ]] && printf '%s' "${BASH_REMATCH[1]}"
}

valid_coord() {
    [[ $1 =~ ^-?[0-9]+(\.[0-9]+)?$ ]] || return 1
    [[ $1 =~ ^-?0+(\.0+)?$ ]] && return 1
    return 0
}

chat_log() {  # chat_log "line"
    mkdir -p "$LOOT_DIR"
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOOT_DIR/chat_$(date +%Y%m%d).log"
}

# Read the latest GPS snapshot written by gps_loop into G_* variables
read_gps() {
    G_FIX=0; G_LAT=""; G_LON=""; G_HAE="0"; G_CE="9999999.0"
    G_SPEED="0"; G_TRACK="0"; G_SATS="-"; G_TIME=0
    [ -f "$RUN/gps" ] || return 1
    local f lat lon hae ce spd trk sats t
    read -r f lat lon hae ce spd trk sats t < "$RUN/gps"
    G_FIX=${f:-0}
    [ "$G_FIX" = 1 ] || return 1
    G_LAT=$lat; G_LON=$lon
    [ "$hae" != "-" ] && G_HAE=$hae
    [ "$ce" != "-" ] && G_CE=$ce
    [ "$spd" != "-" ] && G_SPEED=$spd
    [ "$trk" != "-" ] && G_TRACK=$trk
    G_SATS=$sats; G_TIME=$t
    return 0
}

# Best position available for a CoT point: fix > last fix > manual
# Sets P_LAT P_LON P_HAE P_CE P_SRC P_HOW ; returns 1 if nothing usable
best_position() {
    if read_gps; then
        P_LAT=$G_LAT; P_LON=$G_LON; P_HAE=$G_HAE; P_CE=$G_CE; P_SRC="GPS"; P_HOW="m-g"
        printf '%s %s %s %s\n' "$G_LAT" "$G_LON" "$G_HAE" "$G_CE" > "$RUN/lastfix"
        return 0
    fi
    if [ -f "$RUN/lastfix" ]; then
        read -r P_LAT P_LON P_HAE P_CE < "$RUN/lastfix"; P_SRC="GPS"; P_HOW="h-g-i-g-o"
        return 0
    fi
    if [ -n "$C_MANUAL" ]; then
        P_LAT=${C_MANUAL%%,*}; P_LON=${C_MANUAL##*,}; P_LAT=${P_LAT// /}; P_LON=${P_LON// /}
        if valid_coord "$P_LAT" && valid_coord "$P_LON"; then
            P_HAE=0; P_CE="9999999.0"; P_SRC="USER"; P_HOW="h-e"
            return 0
        fi
    fi
    return 1
}

#############################################################################
# CoT builders (each returns one single-line <event>)
#############################################################################

# Wi-Fi recon counts from the Pager's recon database, cached for 60 s.
# Sets R_APS R_OPEN R_CLIENTS ; returns 1 when unavailable.
recon_stats() {
    [ "$C_RECON" = 1 ] || return 1
    command -v sqlite3 >/dev/null 2>&1 || return 1
    local db="" d now since t out
    for d in /root/recon/recon.db /mmc/root/recon/recon.db; do [ -f "$d" ] && { db=$d; break; }; done
    [ -n "$db" ] || return 1
    now=$(date +%s)
    if [ -f "$RUN/recon" ]; then
        IFS='|' read -r t R_APS R_OPEN R_CLIENTS < "$RUN/recon"
        [ $((now - ${t:-0})) -lt 60 ] && [ -n "$R_APS" ] && return 0
    fi
    since=$((now - RECON_WINDOW))
    out=$(timeout 5 sqlite3 -readonly -cmd ".timeout 2000" "$db" \
        "SELECT (SELECT count(DISTINCT bssid) FROM ssid WHERE type=8 AND time>=$since),
                (SELECT count(DISTINCT bssid) FROM ssid WHERE type=8 AND time>=$since AND (encryption=0 OR encryption IS NULL)),
                (SELECT count(DISTINCT wifi_device) FROM ssid WHERE type=4 AND time>=$since);" 2>/dev/null) || return 1
    IFS='|' read -r R_APS R_OPEN R_CLIENTS <<< "$out"
    [[ $R_APS =~ ^[0-9]+$ ]] || return 1
    printf '%s|%s|%s|%s\n' "$now" "$R_APS" "$R_OPEN" "$R_CLIENTS" > "$RUN/recon"
    return 0
}

cot_sa() {
    best_position || return 1
    local now stale batt chg remarks cs team role
    now=$(date +%s); stale=$((now + C_INTERVAL + 30))
    batt=$(BATTERY_PERCENT 2>/dev/null); batt=${batt//[^0-9]/}; [ -z "$batt" ] && batt=0
    chg=$(BATTERY_CHARGING 2>/dev/null)
    cs=$(xml_esc "$C_CALLSIGN"); team=$(xml_esc "$C_TEAM"); role=$(xml_esc "$C_ROLE")
    remarks="$DEVICE_NAME | Batt ${batt}%"
    case "$chg" in 1|true|yes|charging|Charging) remarks+=" (charging)" ;; esac
    if [ "$P_HOW" = "m-g" ]; then
        remarks+=" | GPS fix, ${G_SATS} sats"
    elif [ "$P_SRC" = "GPS" ]; then
        remarks+=" | NO FIX - last known position"
    else
        remarks+=" | NO FIX - manual position"
    fi
    local recon_xml=""
    if recon_stats; then
        remarks+=" | Sensor $((RECON_WINDOW / 60))m: ${R_APS} APs (${R_OPEN} open), ${R_CLIENTS} clients"
        recon_xml="<__pagertak_recon window=\"$RECON_WINDOW\" aps=\"$R_APS\" open=\"$R_OPEN\" clients=\"$R_CLIENTS\"/>"
    fi
    printf '%s' "<event version=\"2.0\" uid=\"$C_UID\" type=\"a-f-G-U-C\" how=\"$P_HOW\" time=\"$(iso_time "$now")\" start=\"$(iso_time "$now")\" stale=\"$(iso_time "$stale")\">"\
"<point lat=\"$P_LAT\" lon=\"$P_LON\" hae=\"$P_HAE\" ce=\"$P_CE\" le=\"9999999.0\"/>"\
"<detail>"\
"<takv device=\"$DEVICE_NAME\" platform=\"$PRODUCT_NAME\" os=\"OpenWrt\" version=\"$PAYLOAD_VERSION\"/>"\
"<contact callsign=\"$cs\" endpoint=\"*:-1:stcp\"/>"\
"<uid Droid=\"$cs\"/>"\
"<__group name=\"$team\" role=\"$role\"/>"\
"<precisionlocation geopointsrc=\"$P_SRC\" altsrc=\"$P_SRC\"/>"\
"<status battery=\"$batt\"/>"\
"<track course=\"${G_TRACK:-0}\" speed=\"${G_SPEED:-0}\"/>"\
"<remarks>$(xml_esc "$remarks")</remarks>"\
"$recon_xml"\
"</detail></event>"
}

# cot_chat "message" [to_uid to_callsign]   (no recipient = All Chat Rooms)
cot_chat() {
    local msg to_uid=$2 to_cs=$3 now stale mid room rid uid1 dest="" lat=0 lon=0 hae=0 cs
    msg=$(xml_esc "$1"); cs=$(xml_esc "$C_CALLSIGN")
    now=$(date +%s); stale=$((now + 86400)); mid=$(new_id)
    mkdir -p "$RUN/sent.d" && printf '%s|%s|%s|sent\n' "$now" "${to_cs:-All}" "${1//$'\n'/ }" > "$RUN/sent.d/$mid"   # for delivered / read receipts
    if best_position; then lat=$P_LAT; lon=$P_LON; hae=$P_HAE; fi
    if [ -n "$to_uid" ]; then
        room=$(xml_esc "$to_cs"); rid=$(xml_esc "$to_uid"); uid1=$rid
        dest="<marti><dest callsign=\"$room\"/></marti>"
    else
        room=$ALL_ROOM; rid=$ALL_ROOM; uid1=$ALL_ROOM
    fi
    printf '%s' "<event version=\"2.0\" uid=\"GeoChat.$C_UID.$rid.$mid\" type=\"b-t-f\" how=\"h-g-i-g-o\" time=\"$(iso_time "$now")\" start=\"$(iso_time "$now")\" stale=\"$(iso_time "$stale")\">"\
"<point lat=\"$lat\" lon=\"$lon\" hae=\"$hae\" ce=\"9999999.0\" le=\"9999999.0\"/>"\
"<detail>"\
"<__chat parent=\"RootContactGroup\" groupOwner=\"false\" messageId=\"$mid\" chatroom=\"$room\" id=\"$rid\" senderCallsign=\"$cs\">"\
"<chatgrp uid0=\"$C_UID\" uid1=\"$uid1\" id=\"$rid\"/>"\
"</__chat>"\
"<link uid=\"$C_UID\" type=\"a-f-G-U-C\" relation=\"p-p\"/>"\
"<remarks source=\"BAO.F.ATAK.$C_UID\" to=\"$rid\" time=\"$(iso_time "$now")\">$msg</remarks>"\
"$dest"\
"</detail></event>"
}

# cot_receipt d|r messageId sender_uid sender_callsign - delivered / read receipt for a direct message
# we received. The event uid is the message's messageId. ATAK reads <__chatreceipt>, CloudTAK reads
# <__chat>; both carry the original message's chat fields (it was a DM to us: room = our callsign,
# id = our UID, chatgrp uid0 = sender, uid1 = us) and go back to the sender only.
cot_receipt() {
    local now cs room suid mid grp
    now=$(date +%s); cs=$(xml_esc "$C_CALLSIGN"); room=$(xml_esc "$4"); suid=$(xml_esc "$3"); mid=$(xml_esc "$2")
    grp="parent=\"RootContactGroup\" groupOwner=\"false\" messageId=\"$mid\" chatroom=\"$cs\" id=\"$C_UID\" senderCallsign=\"$cs\"><chatgrp uid0=\"$suid\" uid1=\"$C_UID\" id=\"$C_UID\"/>"
    printf '%s' "<event version=\"2.0\" uid=\"$mid\" type=\"b-t-f-$1\" how=\"h-g-i-g-o\" time=\"$(iso_time "$now")\" start=\"$(iso_time "$now")\" stale=\"$(iso_time $((now + 86400)))\">"\
"<point lat=\"0\" lon=\"0\" hae=\"0\" ce=\"9999999.0\" le=\"9999999.0\"/>"\
"<detail>"\
"<__chatreceipt $grp</__chatreceipt>"\
"<__chat $grp</__chat>"\
"<link uid=\"$C_UID\" type=\"a-f-G-U-C\" relation=\"p-p\"/>"\
"<marti><dest callsign=\"$room\"/></marti>"\
"</detail></event>"
}

# Your alert ($RUN/emergency, one line): kind|label|dest|message
#   kind  911 | bell | geo | contact | custom      (an empty file = 911 to everyone, as in 1.x)
#   dest  "" = everyone, or uid:callsign,uid:callsign
EMERG_KINDS=(911 bell geo contact custom)
emerg_type()  { case "$1" in bell) echo b-a-o-pan ;; geo) echo b-a-g ;; contact) echo b-a-o-opn ;; custom) echo b-a-o-c ;; *) echo b-a-o-tbl ;; esac; }
emerg_label() { case "$1" in bell) echo "Ring The Bell" ;; geo) echo "Geo-fence Breached" ;; contact) echo "Troops In Contact" ;; custom) echo "${2:-Custom}" ;; *) echo "911 Alert" ;; esac; }
emerg_read() { E_KIND=911; E_LABEL=""; E_DEST=""; E_MSG=""; [ -s "$RUN/emergency" ] && IFS='|' read -r E_KIND E_LABEL E_DEST E_MSG < "$RUN/emergency"; E_KIND=${E_KIND:-911}; E_LABEL=$(emerg_label "$E_KIND" "$E_LABEL"); }

# marti_dests "uid:cs,uid:cs" -> <marti><dest callsign=../>...</marti> (empty for everyone)
marti_dests() {
    local d out="" IFS=','
    for d in $1; do [ -n "$d" ] && out+="<dest callsign=\"$(xml_esc "${d#*:}")\"/>"; done
    [ -n "$out" ] && printf '<marti>%s</marti>' "$out"
}

# cot_emergency [cancel]  (reads $RUN/emergency)
cot_emergency() {
    local now stale type body cs lat=0 lon=0 hae=0 rem=""
    emerg_read
    cs=$(xml_esc "$C_CALLSIGN"); now=$(date +%s); stale=$((now + 3600))
    if best_position; then lat=$P_LAT; lon=$P_LON; hae=$P_HAE; fi
    if [ "$1" = "cancel" ]; then
        type="b-a-o-can"; body="<emergency cancel=\"true\">$cs</emergency>"
    else
        type=$(emerg_type "$E_KIND"); body="<emergency type=\"$(xml_esc "$E_LABEL")\">$cs</emergency>"
        [ -n "$E_MSG" ] && rem="<remarks>$(xml_esc "$E_MSG")</remarks>"
    fi
    printf '%s' "<event version=\"2.0\" uid=\"$C_UID-9-1-1\" type=\"$type\" how=\"h-e\" time=\"$(iso_time "$now")\" start=\"$(iso_time "$now")\" stale=\"$(iso_time "$stale")\">"\
"<point lat=\"$lat\" lon=\"$lon\" hae=\"$hae\" ce=\"9999999.0\" le=\"9999999.0\"/>"\
"<detail>$(marti_dests "$E_DEST")<link uid=\"$C_UID\" type=\"a-f-G-U-C\" relation=\"p-p\"/>"\
"<contact callsign=\"$cs-Alert\"/>$body$rem</detail></event>"
}

# emergency_send kind label dest message
emergency_send() {
    local kind=$1 label=${2//|//} dest=$3 msg=${4//|//} who
    printf '%s|%s|%s|%s\n' "$kind" "$label" "$dest" "$msg" > "$RUN/emergency"
    emerg_read
    queue_cot "$(cot_emergency)"
    RINGTONE alert >/dev/null 2>&1 &
    if [ -n "$dest" ]; then who="to $(tr ',' '\n' <<< "$dest" | cut -d: -f2- | tr '\n' ',' | sed 's/,$//; s/,/, /g')"; else who="to everyone"; fi
    LOG red "EMERGENCY SENT: $E_LABEL $who"
    chat_log "OUT EMERGENCY $E_LABEL $who${msg:+ - $msg}"
}

emergency_cancel() {
    [ -f "$RUN/emergency" ] || return 1
    queue_cot "$(cot_emergency cancel)"
    rm -f "$RUN/emergency"
    LOG green "Emergency cancel sent"
    chat_log "OUT EMERGENCY CANCELLED"
}

# Hand a CoT event to the network engine (store-and-forward while offline)
queue_cot() {
    mkdir -p "$RUN/outbox"
    local f="$RUN/outbox/$(date +%s)-$$-$RANDOM"
    printf '%s\n' "$1" > "$f.tmp" && mv "$f.tmp" "$f.cot"
}

#############################################################################
# GPS reader (background) - writes one line to $RUN/gps every few seconds:
#   fix lat lon hae ce speed track sats epoch     ("-" = unknown)
#############################################################################

gps_loop() {
    local have_pipe=0 raw lat lon alt acc out tpv sky spd trk sats hae t
    command -v gpspipe >/dev/null 2>&1 && have_pipe=1
    while [ ! -f "$RUN/stop" ]; do
        raw=$(timeout 5 GPS_GET 2>/dev/null)
        read -r lat lon alt acc _ <<< "$raw"
        spd="-"; trk="-"; sats="-"; hae=${alt:--}
        if [ "$have_pipe" = 1 ]; then
            out=$(timeout 3 gpspipe -w -n 12 2>/dev/null)
            tpv=$(printf '%s\n' "$out" | grep -m1 '"class":"TPV"')
            sky=$(printf '%s\n' "$out" | grep -m1 '"class":"SKY"')
            t=$(json_num "$tpv" speed); [ -n "$t" ] && spd=$t
            t=$(json_num "$tpv" track); [ -n "$t" ] && trk=$t
            t=$(json_num "$tpv" altHAE); [ -n "$t" ] && hae=$t
            t=$(json_num "$sky" uSat)
            if [ -n "$t" ]; then sats=$t
            elif [ -n "$sky" ]; then sats=$(printf '%s' "$sky" | grep -o '"used":true' | wc -l)
            fi
            # TAK drops CoT with a badly wrong timestamp; fix the clock from GPS once
            if [ "$GPS_TIME_SYNC" = 1 ] && [ ! -f "$RUN/timesynced" ] && [ "$(date -u +%Y)" -lt 2025 ]; then
                local re='"time":"([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}:[0-9]{2}:[0-9]{2})'
                if [[ $tpv =~ $re ]]; then
                    date -u -s "${BASH_REMATCH[1]} ${BASH_REMATCH[2]}" >/dev/null 2>&1 && : > "$RUN/timesynced"
                fi
            fi
        fi
        if valid_coord "$lat" && valid_coord "$lon"; then
            [[ $acc =~ ^[0-9]+(\.[0-9]+)?$ ]] && [[ ! $acc =~ ^0+(\.0+)?$ ]] || acc="-"
            printf '1 %s %s %s %s %s %s %s %s\n' "$lat" "$lon" "${hae:--}" "$acc" "$spd" "$trk" "$sats" "$(date +%s)" > "$RUN/gps.tmp"
        else
            printf '0 - - - - - - %s %s\n' "$sats" "$(date +%s)" > "$RUN/gps.tmp"
        fi
        mv "$RUN/gps.tmp" "$RUN/gps"
        sleep 4
    done
}

#############################################################################
# Receiver (background, one per connection) - splits the CoT stream on </event>
#############################################################################

contact_seen() {  # contact_seen uid callsign
    local line="$2|$1"
    grep -qxF "$line" "$RUN/contacts" 2>/dev/null && return
    { grep -v "|$1\$" "$RUN/contacts" 2>/dev/null; printf '%s\n' "$line"; } > "$RUN/contacts.tmp"
    mv "$RUN/contacts.tmp" "$RUN/contacts"
}

# One small file per uid so updates are O(1): lat|lon|callsign|type|team|epoch|kind|stale_epoch
track_seen() {  # track_seen uid lat lon callsign type team kind [stale_epoch]
    valid_coord "$2" && valid_coord "$3" || return
    local f="$RUN/tracks.d/$(printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_')"
    printf '%s|%s|%s|%s|%s|%s|%s|%s\n' "$2" "$3" "${4//|//}" "$5" "${6//|//}" "$(date +%s)" "$7" "${8:-0}" > "$f.tmp" && mv "$f.tmp" "$f"
}

track_forget() {  # track_forget uid  - removes a received item (deleted or stale in TAK)
    local n; n=$(printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_')
    rm -f "$RUN/tracks.d/$n" "$RUN/cot.d/$n"
}

# iso_epoch 2026-11-20T20:50:22.123Z -> ISO_EPOCH (UTC seconds, 0 if unreadable). Pure bash, no fork.
iso_epoch() {
    ISO_EPOCH=0
    [[ $1 =~ ^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2}) ]] || return 1
    local y=$((10#${BASH_REMATCH[1]})) m=$((10#${BASH_REMATCH[2]})) d=$((10#${BASH_REMATCH[3]}))
    local H=$((10#${BASH_REMATCH[4]})) M=$((10#${BASH_REMATCH[5]})) S=$((10#${BASH_REMATCH[6]})) era yoe doy doe
    [ "$m" -le 2 ] && y=$((y - 1))
    era=$((y / 400)); yoe=$((y - era * 400))
    doy=$(( (153 * ((m + 9) % 12) + 2) / 5 + d - 1 ))
    doe=$(( yoe * 365 + yoe / 4 - yoe / 100 + doy ))
    ISO_EPOCH=$(( (era * 146097 + doe - 719468) * 86400 + H * 3600 + M * 60 + S ))
}

# Drops received items that are stale (their own CoT stale time; TAK users excepted) or not updated for TRACK_MAX_AGE.
# Your own markers (kind "mine") are kept.
prune_tracks() {
    local f now line ts kind stale n
    now=$(date +%s)
    for f in "$RUN"/tracks.d/*; do
        [ -f "$f" ] || continue
        IFS= read -r line < "$f" || continue
        IFS='|' read -r _ _ _ _ _ ts kind stale <<< "$line"
        [ "$kind" = mine ] && continue
        # TAK users stay (shown as stale, like ATAK) until TRACK_MAX_AGE without an update;
        # markers and other items go at their own stale time
        if { [ "$kind" != client ] && [[ $stale =~ ^[0-9]+$ ]] && [ "$stale" -gt 0 ] && [ "$stale" -lt "$now" ]; } ||
           { [[ $ts =~ ^[0-9]+$ ]] && [ $((now - ts)) -gt "$TRACK_MAX_AGE" ]; }; then
            n=$(basename "$f"); rm -f "$f" "$RUN/cot.d/$n"
        fi
    done
    for f in "$RUN"/sent.d/*; do         # receipts are only tracked for a day
        [ -f "$f" ] || continue
        IFS='|' read -r ts _ < "$f"
        [[ $ts =~ ^[0-9]+$ ]] && [ $((now - ts)) -gt 86400 ] && rm -f "$f"
    done
    for f in "$RUN"/cot.d/*; do          # raw events whose item is gone
        [ -f "$f" ] && [ ! -f "$RUN/tracks.d/$(basename "$f")" ] && rm -f "$f"
    done
}
prune_loop() { while [ ! -f "$RUN/stop" ]; do sleep 60; prune_tracks; done; }

# Clears everything received from TAK (map items, raw events). Contacts for direct messages stay.
clear_received() {
    local f n=0 line
    for f in "$RUN"/tracks.d/*; do
        [ -f "$f" ] || continue
        IFS= read -r line < "$f"
        [ "$(cut -d'|' -f7 <<< "$line")" = mine ] && continue
        rm -f "$f"; n=$((n + 1))
    done
    rm -rf "$RUN/cot.d"; mkdir -p "$RUN/cot.d"
    : > "$RUN/trails.clear"
    LOG green "Cleared $n received items"
    echo "ok|Cleared $n received items (your own markers and zones are kept)"
}

# A receipt for one of our messages: sent.d/<messageId> moves to delivered, then read
chat_receipt_in() {  # chat_receipt_in type messageId [raw event]
    local f="$RUN/sent.d/$2" line st s="$LOOT_DIR/receipts_sample.log"
    # keep the first few receipts other TAK apps send, to compare formats (small, kept once)
    if [ -n "$3" ] && [ "$(wc -c < "$s" 2>/dev/null || echo 0)" -lt 16000 ]; then
        printf '%s %s\n%s\n\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" "${3:0:3000}" >> "$s"
    fi
    [[ $2 =~ ^[A-Za-z0-9._-]{1,100}$ ]] && [ -f "$f" ] || return
    IFS= read -r line < "$f" || return
    st=${line##*|}
    if [ "$1" = b-t-f-r ]; then st="read"; elif [ "$st" != "read" ]; then st="delivered"; fi
    printf '%s|%s\n' "${line%|*}" "$st" > "$f.tmp" && mv "$f.tmp" "$f"
}

unread_count() { local n=0; [ -s "$RUN/unread" ] && n=$(wc -l < "$RUN/unread"); echo "${n// /}"; }

# Marks every unread message as read and sends read receipts for the direct ones
chat_mark_read() {
    [ -s "$RUN/unread" ] || return 0
    local t mid suid cs label
    mv "$RUN/unread" "$RUN/unread.r" 2>/dev/null || return 0
    if [ "$C_RECEIPTS" = 1 ]; then
        while IFS='|' read -r t mid suid cs label; do
            [ "$label" = DM ] && [ -n "$mid" ] && [ -n "$suid" ] && queue_cot "$(cot_receipt r "$mid" "$suid" "$cs")"
        done < "$RUN/unread.r"
    fi
    rm -f "$RUN/unread.r"
}

handle_chat() {
    local ev=$1 etype=${2:-b-t-f} cs="?" room="" rid="" suid="" text="" label mid=""
    if [[ $ev =~ $RE_MSG_ID ]]; then mid=${BASH_REMATCH[1]}
    elif [[ $ev =~ $RE_EV_UID ]]; then mid=${BASH_REMATCH[1]}
    fi
    case "$etype" in
        b-t-f-d|b-t-f-r) chat_receipt_in "$etype" "$mid" "$ev"; return ;;
        b-t-f-?*) return ;;                         # pending / failed receipts and other chat sub-types
    esac
    [[ $ev =~ $RE_SENDER_CS ]] && cs=$(xml_unesc "${BASH_REMATCH[1]}")
    [[ $ev =~ $RE_CHATROOM ]] && room=$(xml_unesc "${BASH_REMATCH[1]}")
    [[ $ev =~ $RE_CHAT_ID ]] && rid=$(xml_unesc "${BASH_REMATCH[1]}")
    if [[ $ev =~ $RE_UID0 ]]; then suid=${BASH_REMATCH[1]}
    elif [[ $ev =~ $RE_LINK_UID ]]; then suid=${BASH_REMATCH[1]}
    fi
    [ "$suid" = "$C_UID" ] && return            # our own message echoed back
    [[ $ev =~ $RE_REMARKS ]] && text=$(xml_unesc "${BASH_REMATCH[1]}")
    [ -z "$text" ] && return
    if [ "$rid" = "$C_UID" ]; then label="DM"
    elif [ "$room" = "$ALL_ROOM" ] || [ -z "$room" ]; then label="All"
    else label="$room"
    fi
    [ -n "$suid" ] && [ "$cs" != "?" ] && contact_seen "$suid" "$cs"
    if [ "$label" = DM ] && [ "$C_RECEIPTS" = 1 ] && [ -n "$mid" ] && [ -n "$suid" ]; then
        queue_cot "$(cot_receipt d "$mid" "$suid" "$cs")"
    fi
    printf '%s|%s|%s|%s|%s\n' "$(date +%s)" "${mid//|/}" "${suid//|/}" "${cs//|//}" "$label" >> "$RUN/unread"
    printf '%s|%s|%s\n' "${suid//|/}" "${cs//|//}" "$label" > "$RUN/lastfrom.tmp" && mv "$RUN/lastfrom.tmp" "$RUN/lastfrom"
    LOG cyan "[$label] $cs: $text"
    chat_log "IN  [$label] $cs: $text"
    printf '%s|%s|%s|%s\n' "$(date +%s)" "$label" "$cs" "${text//$'\n'/ }" > "$RUN/lastchat.tmp" && mv "$RUN/lastchat.tmp" "$RUN/lastchat"
    [ -n "$C_RINGTONE" ] && RINGTONE "$C_RINGTONE" >/dev/null 2>&1 &
}

handle_event() {
    local ev=$1 type="" uid="" cs="" etype=""
    [[ $ev =~ $RE_EV_TYPE ]] || return
    type=${BASH_REMATCH[1]}
    [[ $ev =~ $RE_EV_UID ]] && uid=${BASH_REMATCH[1]}
    case "$type" in
        b-t-f*)
            handle_chat "$ev" "$type"
            ;;
        b-a-o-tbl|b-a-o-pan|b-a-o-opn|b-a-g|b-a-o-c)
            [ "$uid" = "$C_UID-9-1-1" ] && return
            [[ $ev =~ $RE_EMERG ]] && cs=$(xml_unesc "${BASH_REMATCH[1]}")
            [[ $ev =~ $RE_EMERG_TYPE ]] && etype=$(xml_unesc "${BASH_REMATCH[1]}")
            LOG red "EMERGENCY ${etype:-alert}: ${cs:-unknown}"
            chat_log "EMERGENCY ${etype:-alert}: ${cs:-unknown}"
            RINGTONE alert >/dev/null 2>&1 &
            ALERT "EMERGENCY
${etype:-Alert}
${cs:-unknown}" >/dev/null 2>&1 &
            ;;
        b-a-o-can)
            [ "$uid" = "$C_UID-9-1-1" ] && return
            [[ $ev =~ $RE_EMERG ]] && cs=$(xml_unesc "${BASH_REMATCH[1]}")
            LOG green "Emergency cancelled: ${cs:-unknown}"
            chat_log "EMERGENCY CANCELLED: ${cs:-unknown}"
            ;;
        t-x-d-d)                                    # another client deleted an item
            [[ $ev =~ $RE_LINK_UID ]] && track_forget "${BASH_REMATCH[1]}"
            ;;
        a-*|b-m-p-*)
            [ "$uid" = "$C_UID" ] && return
            local kind="marker" lat="" lon="" team="" stale=0 t0 now
            # Real TAK clients carry takv or an endpoint; everything else is a map marker
            if [[ $ev == *"<takv"* || $ev == *"endpoint="* ]]; then kind="client"; fi
            if [[ $ev =~ $RE_EV_STALE ]] && iso_epoch "${BASH_REMATCH[1]}"; then
                stale=$ISO_EPOCH; now=$(date +%s)
                # Measure the stale time from the event's own time, so a Pager clock that is off
                # (or a sender's) does not make fresh items look stale
                if [[ $ev =~ $RE_EV_TIME ]] && iso_epoch "${BASH_REMATCH[1]}" && [ "$ISO_EPOCH" -gt 0 ]; then
                    t0=$ISO_EPOCH; stale=$(( now + stale - t0 ))
                fi
                if [ "$kind" != client ] && [ "$stale" -lt "$now" ]; then track_forget "$uid"; return; fi   # sent already stale = gone
            fi
            [[ $ev =~ $RE_CONTACT_CS ]] && cs=$(xml_unesc "${BASH_REMATCH[1]}")
            [ "$kind" = client ] && [ -n "$cs" ] && contact_seen "$uid" "$cs"
            [[ $ev =~ $RE_PT_LAT ]] && lat=${BASH_REMATCH[1]}
            [[ $ev =~ $RE_PT_LON ]] && lon=${BASH_REMATCH[1]}
            [[ $ev =~ $RE_GROUP ]] && team=$(xml_unesc "${BASH_REMATCH[1]}")
            track_seen "$uid" "$lat" "$lon" "${cs:-$uid}" "$type" "$team" "$kind" "$stale"
            # last raw event per track, for the web console's CoT details view
            mkdir -p "$RUN/cot.d" && printf '%s' "${ev:0:16000}" > "$RUN/cot.d/$(printf '%s' "$uid" | tr -c 'A-Za-z0-9._-' '_')"
            ;;
    esac
}

rx_loop() {
    local ev
    # awk splits the stream into one event per line and thins out busy feeds,
    # so chats and TAK users are handled right away (see include/rx_filter.awk)
    awk -v MIN_SEC="$RX_FEED_MIN_SEC" -f "$PAYLOAD_DIR/include/rx_filter.awk" | while IFS= read -r ev; do
        handle_event "$ev"
    done
    : > "$RUN/rx_eof"
}

#############################################################################
# Network engine (background) - owns the connection, sends SA + outbox,
# reconnects with backoff. It is the only writer to the socket.
#############################################################################

SSL_PID=""; RX_PID=""

conn_close() {
    [ -n "$RX_PID" ] && kill "$RX_PID" 2>/dev/null
    [ -n "$SSL_PID" ] && kill "$SSL_PID" 2>/dev/null
    exec 3>&- 4<&- 2>/dev/null
    RX_PID=""; SSL_PID=""
    rm -f "$RUN/tx" "$RUN/rx"
}

# Bash's /dev/tcp is missing in some builds (OpenWrt's bash package): checked once
tcp_dev_ok() {
    if [ -z "$TCP_DEV_OK" ]; then
        if bash -c 'exec 3<>/dev/tcp/127.0.0.1/9' 2>&1 | grep -qi "no such file"; then TCP_DEV_OK=0; else TCP_DEV_OK=1; fi
    fi
    [ "$TCP_DEV_OK" = 1 ]
}

# tcp_probe HOST PORT [SECONDS] - does the port answer? (Bash /dev/tcp, else Python)
# Sets PROBE_ERR to the reason when it doesn't. Works without the timeout command.
tcp_probe() {
    local t=${3:-8} tmo=()
    command -v timeout >/dev/null 2>&1 && tmo=(timeout "$t")
    if tcp_dev_ok && [ ${#tmo[@]} -gt 0 ]; then
        PROBE_ERR=$("${tmo[@]}" bash -c ": <>/dev/tcp/$1/$2" 2>&1) && return 0
        PROBE_ERR=${PROBE_ERR##*: }; [ -z "$PROBE_ERR" ] && PROBE_ERR="no answer in ${t}s"
        return 1
    fi
    PROBE_ERR=$("${PYTHON_BIN:-python3}" -c 'import socket, sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), float(sys.argv[3])).close()
except socket.timeout:
    sys.exit("no answer in %ss" % sys.argv[3])
except OSError as e:
    sys.exit(e.strerror or str(e))' "$1" "$2" "$t" 2>&1) && return 0
    [ -z "$PROBE_ERR" ] && PROBE_ERR="no answer"
    return 1
}

# A plain TCP link through Python, for a Bash without /dev/tcp: stdin -> server -> stdout
TCP_LINK_PY='import os, socket, sys, threading
s = socket.create_connection((sys.argv[1], int(sys.argv[2])), 10)
def up():
    while True:
        d = os.read(0, 65536)
        if not d:
            break
        s.sendall(d)
    s.shutdown(socket.SHUT_WR)
threading.Thread(target=up, daemon=True).start()
while True:
    d = s.recv(65536)
    if not d:
        break
    os.write(1, d)'

conn_open() {
    rm -f "$RUN/rx_eof"
    case "$C_PROTO" in
        udp)
            exec 3>"/dev/udp/$C_HOST/$C_PORT" 2>/dev/null || return 1
            ;;
        tcp)
            tcp_probe "$C_HOST" "$C_PORT" || { LAST_ERR="$C_HOST:$C_PORT: $PROBE_ERR"; return 1; }
            if tcp_dev_ok; then
                exec 3<>"/dev/tcp/$C_HOST/$C_PORT" 2>/dev/null || return 1
                rx_loop <&3 &
            else                                    # same as TLS below, with a Python link instead of openssl
                rm -f "$RUN/tx" "$RUN/rx"; mkfifo "$RUN/tx" "$RUN/rx" || return 1
                "${PYTHON_BIN:-python3}" -c "$TCP_LINK_PY" "$C_HOST" "$C_PORT" < "$RUN/tx" > "$RUN/rx" 2> "$RUN/ssl.log" &
                SSL_PID=$!
                exec 3> "$RUN/tx" 4< "$RUN/rx"
                rx_loop <&4 &
            fi
            RX_PID=$!
            ;;
        tls)
            local cert="$CERT_DIR/$C_CLIENT_PEM" ca="$CERT_DIR/$C_CA_PEM" args
            tcp_probe "$C_HOST" "$C_PORT" || { LAST_ERR="$C_HOST:$C_PORT: $PROBE_ERR"; return 1; }
            args=(-quiet -connect "$C_HOST:$C_PORT" -cert "$cert" -key "$cert")
            [[ $C_HOST =~ ^[0-9.]+$ ]] || args+=(-servername "$C_HOST")
            [ -f "$ca" ] && args+=(-CAfile "$ca" -verify_return_error)
            rm -f "$RUN/tx" "$RUN/rx"; mkfifo "$RUN/tx" "$RUN/rx" || return 1
            openssl s_client "${args[@]}" < "$RUN/tx" > "$RUN/rx" 2> "$RUN/ssl.log" &
            SSL_PID=$!
            exec 3> "$RUN/tx" 4< "$RUN/rx"
            sleep 3
            if ! kill -0 "$SSL_PID" 2>/dev/null; then
                LAST_ERR=$(grep -im1 "error\|unable\|fail" "$RUN/ssl.log" | cut -c1-80)
                [ -z "$LAST_ERR" ] && LAST_ERR="TLS handshake failed"
                conn_close
                return 1
            fi
            rx_loop <&4 &
            RX_PID=$!
            ;;
        *)
            LAST_ERR="unknown protocol $C_PROTO"; return 1 ;;
    esac
    return 0
}

conn_dead() {
    [ -f "$RUN/rx_eof" ] && return 0
    [ -n "$SSL_PID" ] && ! kill -0 "$SSL_PID" 2>/dev/null && return 0
    return 1
}

send_raw() { printf '%s\n' "$1" >&3 2>/dev/null; }

engine_status() {  # engine_status state
    printf '%s|%s|%s\n' "$1" "${LAST_SA:-never}" "${LAST_ERR:-}" > "$RUN/status.tmp"
    mv "$RUN/status.tmp" "$RUN/status"
}

engine() {
    trap 'conn_close; exit 0' TERM INT
    local connected=0 next_try=0 backoff=5 next_sa=0 now f ev led="" newled nofix_warned=0
    LAST_SA=""; LAST_ERR=""
    while [ ! -f "$RUN/stop" ]; do
        now=$(date +%s)
        if [ -f "$RUN/reload" ]; then
            rm -f "$RUN/reload"; load_config
            if [ -f "$RUN/reconnect" ]; then
                rm -f "$RUN/reconnect"; conn_close; connected=0; next_try=0; backoff=5
            fi
            next_sa=0
        fi

        if [ "$connected" = 0 ]; then
            if [ "$now" -ge "$next_try" ]; then
                engine_status "connecting"; LED CYAN SLOW; led="cyan"
                LOG "Connecting $C_PROTO://$C_HOST:$C_PORT ..."
                if conn_open; then
                    connected=1; backoff=5; next_sa=0; LAST_ERR=""
                    LOG green "Connected to TAK Server"
                    engine_status "connected"
                else
                    LOG red "Connect failed: ${LAST_ERR:-error}"
                    LOG red "Retry in ${backoff}s"
                    engine_status "disconnected"; LED RED SLOW; led="red"
                    next_try=$((now + backoff)); backoff=$((backoff * 2)); [ "$backoff" -gt 60 ] && backoff=60
                fi
            fi
            sleep 1; continue
        fi

        if conn_dead; then
            conn_close; connected=0; next_try=$((now + 5))
            LAST_ERR="connection lost"; LOG red "TAK connection lost"
            engine_status "disconnected"; LED RED SLOW; led="red"
            continue
        fi

        if [ "$now" -ge "$next_sa" ] || [ -f "$RUN/sa_now" ]; then
            rm -f "$RUN/sa_now"
            if ev=$(cot_sa); then
                if send_raw "$ev"; then
                    LAST_SA=$(date '+%H:%M:%S'); nofix_warned=0
                    [ -f "$RUN/emergency" ] && send_raw "$(cot_emergency)"
                else
                    conn_close; connected=0; LAST_ERR="send failed"; continue
                fi
            elif [ "$nofix_warned" = 0 ]; then
                LOG yellow "Waiting for GPS fix (or set a manual position)"
                nofix_warned=1
            fi
            next_sa=$((now + C_INTERVAL))
            engine_status "connected"
        fi

        # Queued chat / emergency messages, oldest first
        for f in "$RUN"/outbox/*.cot; do
            [ -e "$f" ] || break
            if send_raw "$(cat "$f")"; then rm -f "$f"; else connected=0; break; fi
        done
        [ "$connected" = 0 ] && { conn_close; LAST_ERR="send failed"; continue; }


        if read_gps; then newled="green"; else newled="yellow"; fi
        [ -s "$RUN/unread" ] && newled="magenta"            # unread chat until you open Chat on the Pager or the web
        if [ "$newled" != "$led" ]; then
            case "$newled" in green) LED GREEN ;; magenta) LED MAGENTA SLOW ;; *) LED YELLOW ;; esac
            led=$newled
        fi
        sleep 1
    done
    conn_close
}

#############################################################################
# UI
#############################################################################

send_chat() {  # send_chat "text" [to_uid to_cs]
    local label="All"
    [ -n "$2" ] && label="DM $3"
    queue_cot "$(cot_chat "$1" "$2" "$3")"
    LOG green "[$label] me: $1"
    chat_log "OUT [$label] $C_CALLSIGN: $1"
}

pick_quick() {  # pick_quick [title] - prints chosen quick message
    local r q
    q=$(cfg_get quick_msgs "")             # may have been changed in the web console
    if [ -n "$q" ]; then IFS='|' read -r -a QUICK_MESSAGES <<< "$q"; else QUICK_MESSAGES=("${QUICK_DEFAULT[@]}"); fi
    r=$(LIST_PICKER "${1:-Quick message}" "${QUICK_MESSAGES[@]}" "${QUICK_MESSAGES[0]}")
    picker_ok $? || return 1
    [ -n "$r" ] || return 1
    printf '%s' "$r"
}

type_msg() {  # prints typed message
    local r
    r=$(TEXT_PICKER "${1:-Message}" "")
    picker_ok $? || return 1
    [ -n "$r" ] || return 1
    printf '%s' "$r"
}

direct_message() {
    local names=() sel uid mode msg
    if [ ! -s "$RUN/contacts" ]; then
        PROMPT "No TAK contacts seen yet.
Contacts appear once other users report position."
        return
    fi
    mapfile -t names < <(cut -d'|' -f1 "$RUN/contacts" | sort -u)
    sel=$(LIST_PICKER "Send to" "${names[@]}" "${names[0]}")
    picker_ok $? || return
    uid=$(awk -F'|' -v n="$sel" '$1==n {print $2; exit}' "$RUN/contacts")
    [ -z "$uid" ] && return
    mode=$(LIST_PICKER "Message $sel" "Quick message" "Type message" "Quick message")
    picker_ok $? || return
    if [ "$mode" = "Type message" ]; then msg=$(type_msg "Message to $sel") || return
    else msg=$(pick_quick) || return; fi
    send_chat "$msg" "$uid" "$sel"
}

# Reply to whoever sent the last message: a DM goes back as a DM, a room message to All
# (or to the sender directly)
reply_last() {
    local suid cs label mode msg r
    [ -s "$RUN/lastfrom" ] || { LOG "No message to reply to yet"; return; }
    IFS='|' read -r suid cs label < "$RUN/lastfrom"
    chat_mark_read
    if [ "$label" != DM ] && [ -n "$suid" ]; then
        r=$(LIST_PICKER "Reply to $cs" "Reply in $label" "Reply to $cs only" "Reply in $label"); picker_ok $? || return
        [ "$r" = "Reply to $cs only" ] && label=DM
    fi
    mode=$(LIST_PICKER "Reply to $cs" "Quick message" "Type message" "Quick message"); picker_ok $? || return
    if [ "$mode" = "Type message" ]; then msg=$(type_msg "Reply to $cs") || return
    else msg=$(pick_quick "Reply to $cs") || return; fi
    if [ "$label" = DM ] && [ -n "$suid" ]; then send_chat "$msg" "$suid" "$cs"; else send_chat "$msg"; fi
}

# Deletes the chat history on this Pager (logs, unread count, reply target, receipt status).
# Messages already delivered to other TAK devices stay there.
chat_clear() {
    rm -f "$LOOT_DIR"/chat_*.log "$RUN/unread" "$RUN/lastfrom" "$RUN/lastchat"
    rm -rf "$RUN/sent.d"
    LOG green "Chat history cleared"
}

show_history() {
    local f="$LOOT_DIR/chat_$(date +%Y%m%d).log" line
    chat_mark_read
    if [ ! -s "$f" ]; then LOG "No chat today"; return; fi
    LOG white "---- last messages ----"
    while IFS= read -r line; do LOG white "${line:11}"; done < <(tail -n 10 "$f")
    LOG white "-----------------------"
}

show_status() {
    local st="" lastsa="" err="" n=0 q=0
    [ -f "$RUN/status" ] && IFS='|' read -r st lastsa err < "$RUN/status"
    [ -s "$RUN/contacts" ] && n=$(wc -l < "$RUN/contacts")
    q=$(ls "$RUN"/outbox/*.cot 2>/dev/null | wc -l)
    LOG white "---- PagerTAK status ----"
    LOG white "$C_CALLSIGN  ($C_TEAM / $C_ROLE)"
    LOG white "$C_PROTO://$C_HOST:$C_PORT"
    LOG white "Link: ${st:-starting}  Last SA: ${lastsa:-never}"
    [ -n "$err" ] && LOG yellow "Last error: $err"
    if read_gps; then LOG green "GPS: $G_LAT, $G_LON  sats $G_SATS"
    else LOG yellow "GPS: no fix"; fi
    LOG white "Contacts: $n   Queued: $q   Unread chat: $(unread_count)"
    [ -f "$RUN/emergency" ] && { emerg_read; LOG red "EMERGENCY ACTIVE: $E_LABEL"; }
    [ "${WEB_LOADED:-0}" = 1 ] && web_running && LOG white "Web: $(web_urls | head -n1)"
    if [ "$C_PROTO" = tls ] && [ "${SETUP_LOADED:-0}" = 1 ]; then
        local d; d=$(cert_days) && LOG white "Client cert: $(cert_cn), $d days left"
    fi
}

emergency_menu() {
    local r kind label="" dest="" c
    if [ -f "$RUN/emergency" ]; then
        emerg_read
        r=$(CONFIRMATION_DIALOG "Cancel your $E_LABEL alert?")
        [ "$r" = "$DUCKYSCRIPT_USER_CONFIRMED" ] || return
        emergency_cancel
        return
    fi
    r=$(LIST_PICKER "Alert type" "911 Alert" "Ring The Bell" "Geo-fence Breached" "Troops In Contact" "Custom..." "911 Alert"); picker_ok $? || return
    case "$r" in
        "Ring The Bell") kind=bell ;; "Geo-fence Breached") kind=geo ;; "Troops In Contact") kind=contact ;;
        Custom*) kind=custom; label=$(TEXT_PICKER "Alert name" ""); picker_ok $? || return; label=${label:0:30}; [ -n "$label" ] || return ;;
        *) kind=911 ;;
    esac
    if [ -s "$RUN/contacts" ]; then
        r=$(LIST_PICKER "Send to" "Everyone" "Choose contacts" "Everyone"); picker_ok $? || return
        if [ "$r" = "Choose contacts" ]; then
            mapfile -t c < <(cut -d'|' -f1 "$RUN/contacts")
            r=$(toggle_menu "Send to" "${c[@]}") || return
            [ -n "$r" ] && [ "$r" != None ] || { LOG yellow "Nobody chosen - not sent"; return; }
            dest=$(tr ',' '\n' <<< "${r//, /,}" | while read -r cs; do grep -m1 "^$cs|" "$RUN/contacts" | awk -F'|' '{print $2":"$1}'; done | tr '\n' ',' | sed 's/,$//')
        fi
    fi
    local to="all TAK users"; [ -n "$dest" ] && to="$(tr ',' '\n' <<< "$dest" | cut -d: -f2- | tr '\n' ',' | sed 's/,$//; s/,/, /g')"
    r=$(CONFIRMATION_DIALOG "Send $(emerg_label "$kind" "$label") to $to?")
    [ "$r" = "$DUCKYSCRIPT_USER_CONFIRMED" ] || return
    emergency_send "$kind" "$label" "$dest" ""
}

#############################################################################
# Contacts view (distance / bearing) and map
#############################################################################

# Prints "dist_m|label|uid_file|kind|lat|lon|callsign" for every live track, nearest first
nearby_tracks() {
    best_position || return 1
    local now f
    now=$(date +%s)
    for f in "$RUN"/tracks.d/*; do
        [ -f "$f" ] || continue
        printf '%s|%s\n' "${f##*/}" "$(head -n1 "$f")"
    done | awk -F'|' -v la="$P_LAT" -v lo="$P_LON" -v now="$now" -v maxage="$TRACK_MAX_AGE" '
        function rad(d) { return d * 3.14159265358979 / 180 }
        BEGIN { split("N NE E SE S SW W NW", D, " ") }
        {
            if (now - $7 > maxage) next
            p1 = rad(la); p2 = rad($2); dp = p2 - p1; dl = rad($3 - lo)
            a = sin(dp/2)^2 + cos(p1)*cos(p2)*sin(dl/2)^2
            d = 2 * 6371000 * atan2(sqrt(a), sqrt(1-a))
            b = atan2(sin(dl)*cos(p2), cos(p1)*sin(p2) - sin(p1)*cos(p2)*cos(dl)) * 180 / 3.14159265358979
            b = (b + 360) % 360
            dir = D[int((b + 22.5) / 45) % 8 + 1]
            if (d < 1000) ds = sprintf("%dm", d); else if (d < 10000) ds = sprintf("%.1fkm", d/1000); else ds = sprintf("%dkm", d/1000)
            age = now - $7; as = (age < 60) ? sprintf("%ds", age) : sprintf("%dm", age/60)
            tag = ($8 == "client") ? "" : "*"
            printf "%d|%s%s %s %s %s|%s|%s|%s|%s|%s\n", d, tag, $4, ds, dir, as, $1, $8, $2, $3, $4
        }' | sort -t'|' -k1,1n
}

contacts_view() {
    local rows=() labels=() i sel n act row cs kind lat lon uid
    if ! best_position; then PROMPT "No position yet - need a GPS fix or a manual position."; return; fi
    mapfile -t rows < <(nearby_tracks | head -n 25)
    if [ ${#rows[@]} -eq 0 ]; then PROMPT "No TAK contacts or markers in the last $((TRACK_MAX_AGE / 60)) min."; return; fi
    for i in "${!rows[@]}"; do labels+=("$((i + 1)). $(cut -d'|' -f2 <<< "${rows[$i]}")"); done
    sel=$(LIST_PICKER "Nearest (* = marker)" "${labels[@]}" "Back" "${labels[0]}")
    picker_ok $? || return
    [ "$sel" = "Back" ] && return
    n=${sel%%.*}; [[ $n =~ ^[0-9]+$ ]] || return
    row=${rows[$((n - 1))]}
    IFS='|' read -r _ _ _ kind lat lon cs <<< "$row"
    local tfile; tfile=$(cut -d'|' -f3 <<< "$row")
    if [ "$kind" = "client" ]; then
        act=$(LIST_PICKER "$cs" "Navigate to" "Show on map" "Direct message" "Geofence alert" "Back" "Navigate to")
    else
        act=$(LIST_PICKER "$cs" "Navigate to" "Show on map" "Back" "Navigate to")
    fi
    picker_ok $? || return
    case "$act" in
        "Navigate to") map_view "" --nav "$tfile" ;;
        "Show on map") map_view "$lat,$lon" ;;
        "Geofence alert")
            if [ "${GEO_LOADED:-0}" = 1 ]; then geo_quick "$tfile" "$cs"; else ERROR_DIALOG "Geofence module missing: include/geofence.sh"; fi ;;
        "Direct message")
            uid=$(awk -F'|' -v n="$cs" '$1==n {print $2; exit}' "$RUN/contacts")
            [ -z "$uid" ] && { LOG yellow "No UID known for $cs"; return; }
            local mode msg
            mode=$(LIST_PICKER "Message $cs" "Quick message" "Type message" "Quick message")
            picker_ok $? || return
            if [ "$mode" = "Type message" ]; then msg=$(type_msg "Message to $cs") || return
            else msg=$(pick_quick) || return; fi
            send_chat "$msg" "$uid" "$cs" ;;
    esac
}

# Python for the map and the web console (python3-light; the screen driver is map/pagerfb.py)
configure_python() {
    PYTHON_BIN=""
    local c v
    for c in /usr/bin/python3 /mmc/usr/bin/python3; do
        [ -x "$c" ] || continue
        [ "$c" = /mmc/usr/bin/python3 ] && export LD_LIBRARY_PATH="/mmc/usr/lib:/mmc/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        v=$("$c" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null) || continue
        PYTHON_BIN=$c
        [ -d "/mmc/usr/lib/python$v" ] && export PYTHONPATH="/mmc/usr/lib/python$v:/mmc/usr/lib/python$v/lib-dynload${PYTHONPATH:+:$PYTHONPATH}"
        return 0
    done
    return 1
}

map_ready() {
    configure_python || return 1
    "$PYTHON_BIN" -B "$MAP_DIR/pagertak_map.py" --self-check >/dev/null 2>&1
}

install_map() {
    local r id log="${LOG_TMP:-/tmp/pagertak}-map-install.log"
    r=$(CONFIRMATION_DIALOG "The map needs python3-light (about 5 MB, internet). Install now?")
    [ "$r" = "$DUCKYSCRIPT_USER_CONFIRMED" ] || return 1
    id=$(START_SPINNER "Installing map")
    {
        opkg update
        if ! configure_python; then opkg -d mmc install python3-light || opkg install python3-light; fi
    } > "$log" 2>&1
    STOP_SPINNER "$id"
    if map_ready; then LOG green "Map installed"; return 0; fi
    ERROR_DIALOG "Map install failed. See $log"
    return 1
}

map_view() {  # map_view [lat,lon] [extra map args...]
    local args rc center=$1; shift
    if ! map_ready; then install_map || return; fi
    args=(--run "$RUN" --tiles "$TILE_DIR" --tile-url "$C_TILE_URL"
          --sources "$MAP_DIR/sources" --source "$C_MAP_SOURCE"
          --zoom "$MAP_ZOOM" --callsign "$C_CALLSIGN" --max-age "$TRACK_MAX_AGE" --radius-km "$(cfg_get cot_radius "$COT_RADIUS_KM")" --hide "$(cfg_get cot_hide "")")
    rm -f "$RUN/map_source"
    [ -n "$center" ] && args+=(--center "$center")
    args+=("$@")
    [ -n "$C_MANUAL" ] && args+=(--manual "${C_MANUAL// /}")
    if ! UI_TAKEOVER >/dev/null 2>&1; then
        ERROR_DIALOG "Could not take over the display (UI_TAKEOVER). Update the Pager firmware."
        return
    fi
    PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -B "$MAP_DIR/pagertak_map.py" "${args[@]}" 2> ${LOG_TMP:-/tmp/pagertak}-map.log
    rc=$?
    UI_RELEASE >/dev/null 2>&1
    [ "$rc" -ne 0 ] && LOG red "Map exited ($rc) - see ${LOG_TMP:-/tmp/pagertak}-map.log"
    # remember the basemap picked on the map (hold B + A)
    if [ -s "$RUN/map_source" ]; then
        cfg_set map_source "$(head -n1 "$RUN/map_source")"; load_config
    fi
}

cache_tiles() {
    local km r id out
    configure_python || { install_map || return; }
    best_position || { PROMPT "Need a GPS fix or manual position to cache around."; return; }
    km=$(NUMBER_PICKER "Cache radius (km)" 3); picker_ok $? || return
    [[ $km =~ ^[0-9]+$ ]] && [ "$km" -ge 1 ] || return
    r=$(CONFIRMATION_DIALOG "Download '$C_MAP_SOURCE' tiles (zoom 10-16) within ${km} km of $P_LAT,$P_LON ?")
    [ "$r" = "$DUCKYSCRIPT_USER_CONFIRMED" ] || return
    id=$(START_SPINNER "Caching tiles")
    out=$("$PYTHON_BIN" -B "$MAP_DIR/pagertak_map.py" --run "$RUN" --tiles "$TILE_DIR" --tile-url "$C_TILE_URL" \
          --sources "$MAP_DIR/sources" --source "$C_MAP_SOURCE" \
          --center "$P_LAT,$P_LON" --cache-km "$km" --cache-zoom 10-16 2>&1 | tail -n1)
    STOP_SPINNER "$id"
    LOG green "Tiles: ${out:-done}"
}

#############################################################################
# Setup / settings
#############################################################################

need_openssl() {
    command -v openssl >/dev/null 2>&1 && return 0
    local r
    r=$(CONFIRMATION_DIALOG "TLS needs openssl. Install openssl-util now? (needs internet)")
    [ "$r" = "$DUCKYSCRIPT_USER_CONFIRMED" ] || return 1
    local id; id=$(START_SPINNER "Installing")
    opkg update >/dev/null 2>&1; opkg install openssl-util >/dev/null 2>&1
    STOP_SPINNER "$id"
    command -v openssl >/dev/null 2>&1 && { LOG green "openssl installed"; return 0; }
    ERROR_DIALOG "openssl install failed. Run: opkg update && opkg install openssl-util"
    return 1
}

CERT_LOG="${LOG_TMP:-/tmp/pagertak}-cert.log"

# p12_to_pem in.p12 out.pem password [nokeys]
# Returns 0 ok, 2 wrong password, 3 legacy (RC2/3DES) support missing,
#         4 legacy module present but unusable on this firmware, 1 other error.
# TAK Server .p12 files use legacy RC2/3DES encryption; OpenSSL 3 needs the
# legacy provider (OpenWrt package libopenssl-legacy) to read them.
p12_to_pem() {
    local extra=(-nodes) err
    [ "$4" = "nokeys" ] && extra=(-nokeys)
    rm -f "$2"
    if openssl pkcs12 -legacy -in "$1" "${extra[@]}" -passin "pass:$3" -out "$2" 2> "$CERT_LOG.1"; then return 0; fi
    if openssl pkcs12 -in "$1" "${extra[@]}" -passin "pass:$3" -out "$2" 2> "$CERT_LOG.2"; then return 0; fi
    rm -f "$2"
    err=$(cat "$CERT_LOG.1" "$CERT_LOG.2" 2>/dev/null)
    { echo "== $(date '+%F %T') $1"; echo "$err"; } >> "$CERT_LOG"
    rm -f "$CERT_LOG.1" "$CERT_LOG.2"
    if grep -qi "invalid password\|mac verify" <<< "$err"; then return 2; fi
    # Pager firmware builds libcrypto without some legacy ciphers (e.g. IDEA), so the
    # stock OpenWrt legacy.so fails to load ("Error relocating ... symbol not found")
    if grep -qi "error relocating\|symbol not found" <<< "$err"; then return 4; fi
    if grep -qi "provider legacy\|unsupported\|RC2\|des-ede3\|legacy.so" <<< "$err"; then return 3; fi
    return 1
}

install_legacy_provider() {
    local r id
    r=$(CONFIRMATION_DIALOG "This .p12 uses older encryption (RC2/3DES) that needs the OpenSSL legacy module. Install libopenssl-legacy now? (internet)")
    [ "$r" = "$DUCKYSCRIPT_USER_CONFIRMED" ] || return 1
    id=$(START_SPINNER "Installing")
    { opkg update; opkg install libopenssl-legacy; } >> "$CERT_LOG" 2>&1
    STOP_SPINNER "$id"
    if opkg list-installed 2>/dev/null | grep -q '^libopenssl-legacy '; then
        LOG green "OpenSSL legacy module installed"; return 0
    fi
    ERROR_DIALOG "Could not install libopenssl-legacy. See $CERT_LOG, or convert the .p12 on a PC (README)."
    return 1
}

legacy_unusable() {
    ERROR_DIALOG "This $DEVICE_WORD's OpenSSL can't read $1 (old RC2/3DES encryption). Convert it once on your TAK server or a PC to client.pem / ca.pem and copy those into certs/ - see README."
    LOG yellow "Tip: opkg remove libopenssl-legacy (it can't load on this firmware)"
}

# convert_p12 file.p12 out.pem title [nokeys] - asks for the password, handles retries
convert_p12() {
    local pw tries=0 rc
    while [ $tries -lt 3 ]; do
        pw=$(TEXT_PICKER "Password for $3" "atakatak"); picker_ok $? || return 1
        p12_to_pem "$1" "$2" "$pw" "$4"; rc=$?
        case $rc in
            0) return 0 ;;
            2) tries=$((tries + 1)); LOG yellow "Wrong password for $3 (try $tries/3)" ;;
            3) install_legacy_provider || return 1
               p12_to_pem "$1" "$2" "$pw" "$4" && return 0
               rc=$?; [ $rc = 2 ] && { tries=$((tries + 1)); LOG yellow "Wrong password for $3"; continue; }
               [ $rc = 4 ] && { legacy_unusable "$3"; return 1; }
               ERROR_DIALOG "Still could not read $3. See $CERT_LOG"; return 1 ;;
            4) legacy_unusable "$3"; return 1 ;;
            *) ERROR_DIALOG "Could not read $3 - is it a valid .p12? See $CERT_LOG"; return 1 ;;
        esac
    done
    ERROR_DIALOG "Wrong password for $3 (3 tries)."
    return 1
}

setup_certs() {  # setup_certs [force]   force = re-convert from .p12 if any are present
    mkdir -p "$CERT_DIR"
    local client="$CERT_DIR/$C_CLIENT_PEM" ca="$CERT_DIR/$C_CA_PEM" p12s=() sel pw
    need_openssl || return 1
    mapfile -t p12s < <(cd "$CERT_DIR" && ls *.p12 2>/dev/null)
    if [ -s "$client" ] && grep -q "ENCRYPTED PRIVATE KEY\|Proc-Type: 4,ENCRYPTED" "$client"; then
        ERROR_DIALOG "$C_CLIENT_PEM has a password-protected key. Re-export it with -nodes (see README) and copy it again."
        return 1
    fi
    if [ -s "$client" ] && grep -q "PRIVATE KEY" "$client" && { [ "$1" != "force" ] || [ ${#p12s[@]} -eq 0 ]; }; then
        [ -s "$ca" ] || LOG yellow "No $C_CA_PEM - server certificate will NOT be verified"
        [ "$1" = "force" ] && LOG green "Using existing $C_CLIENT_PEM"
        return 0
    fi
    if [ ${#p12s[@]} -eq 0 ]; then
        [ "${SETUP_LOADED:-0}" = 1 ] && cert_menu && return 0
        ERROR_DIALOG "No client cert. Enroll with your TAK username, set up in a browser, or copy $C_CLIENT_PEM (or your .p12 files) into
$CERT_DIR
then run PagerTAK again."
        return 1
    fi
    sel=$(LIST_PICKER "Client cert (.p12)" "${p12s[@]}" "${p12s[0]}")
    picker_ok $? || return 1
    convert_p12 "$CERT_DIR/$sel" "$client" "$sel" || { rm -f "$client"; return 1; }
    if ! grep -q "PRIVATE KEY" "$client"; then
        rm -f "$client"
        ERROR_DIALOG "$sel has no private key - pick the client cert, not the truststore."
        return 1
    fi
    chmod 600 "$client"
    LOG green "Client cert ready"
    if [ ! -s "$ca" ] && [ ${#p12s[@]} -gt 1 ]; then
        sel=$(LIST_PICKER "Server truststore (.p12)" "${p12s[@]}" "Skip" "Skip")
        if picker_ok $? && [ "$sel" != "Skip" ]; then
            if convert_p12 "$CERT_DIR/$sel" "$ca" "$sel" nokeys && grep -q "CERTIFICATE" "$ca"; then
                LOG green "Server CA ready"
            else
                rm -f "$ca"; LOG yellow "Truststore not converted - server will not be verified"
            fi
        fi
    fi
    return 0
}

# No certificate yet: enroll with a TAK username, or finish in a browser
cert_menu() {
    local r u pw id st
    r=$(LIST_PICKER "No client certificate" "Enroll (TAK username)" "Set up in a web browser" "Cancel" "Enroll (TAK username)"); picker_ok $? || return 1
    case "$r" in
        "Enroll"*)
            u=$(TEXT_PICKER "TAK username" ""); picker_ok $? || return 1
            pw=$(TEXT_PICKER "TAK password" ""); picker_ok $? || return 1
            id=$(START_SPINNER "Enrolling")
            tak_enroll "$C_HOST" "$u" "$pw" "$(cfg_get enroll_port 8446)"
            STOP_SPINNER "$id"
            st=$(cat "$RUN/enroll.status" 2>/dev/null)
            if [ "${st%%|*}" = ok ]; then LOG green "${st#*|}"; return 0; fi
            ERROR_DIALOG "${st#*|}"; return 1 ;;
        "Set up in a web browser") setup_in_browser ;;
        *) return 1 ;;
    esac
}

set_host() {
    local r; r=$(TEXT_PICKER "TAK Server host / IP" "$C_HOST"); picker_ok $? || return 1
    [ -n "$r" ] && cfg_set host "$r"
    return 0
}
set_proto() {
    local r; r=$(LIST_PICKER "Protocol" "tls" "tcp" "udp" "$C_PROTO"); picker_ok $? || return 1
    cfg_set proto "$r"
    case "$r" in tls) cfg_set port 8089 ;; tcp|udp) cfg_set port 8087 ;; esac
}
set_port() {
    local r; r=$(NUMBER_PICKER "TAK Server port" "$C_PORT"); picker_ok $? || return 1
    [ -n "$r" ] && cfg_set port "$r"
    return 0
}
set_callsign() {
    local r; r=$(TEXT_PICKER "Callsign" "$C_CALLSIGN"); picker_ok $? || return 1
    [ -n "$r" ] && cfg_set callsign "$r"
    return 0
}
set_team() {
    local r; r=$(LIST_PICKER "Team color" White Yellow Orange Magenta Red Maroon Purple "Dark Blue" Blue Cyan Teal Green "Dark Green" Brown "$C_TEAM")
    picker_ok $? || return 1; cfg_set team "$r"
}
set_role() {
    local r; r=$(LIST_PICKER "Role" "Team Member" "Team Lead" HQ Sniper Medic "Forward Observer" RTO K9 "$C_ROLE")
    picker_ok $? || return 1; cfg_set role "$r"
}
set_interval() {
    local r; r=$(NUMBER_PICKER "Position interval (sec)" "$C_INTERVAL"); picker_ok $? || return 1
    [[ "$r" =~ ^[0-9]+$ ]] && [ "$r" -ge 5 ] && cfg_set interval "$r"
    return 0
}
set_manual() {
    local r; r=$(TEXT_PICKER "Manual position lat,lon (blank=off)" "$C_MANUAL"); picker_ok $? || return 1
    if [ -z "$r" ]; then PAYLOAD_DEL_CONFIG "$CFG_NS" manual_pos >/dev/null 2>&1; else cfg_set manual_pos "$r"; fi
}
set_map_source() {
    local names=() r
    mapfile -t names < <(sed -n 's:.*<name>\(.*\)</name>.*:\1:p' "$MAP_DIR"/sources/*.xml 2>/dev/null | sort -u)
    [[ -n "$C_TILE_URL" && "$C_TILE_URL" != *example.com* ]] && names+=("Custom")
    [ ${#names[@]} -eq 0 ] && { ERROR_DIALOG "No map sources in $MAP_DIR/sources"; return 1; }
    r=$(LIST_PICKER "Map source" "${names[@]}" "$C_MAP_SOURCE"); picker_ok $? || return 1
    cfg_set map_source "$r"
}
set_tile_url() {
    local r; r=$(TEXT_PICKER "Custom tile URL ({z}/{x}/{y})" "$C_TILE_URL"); picker_ok $? || return 1
    [ -n "$r" ] && cfg_set tile_url "$r"
    return 0
}
set_recon() {
    local r; r=$(LIST_PICKER "Sensor stats in reports" "On" "Off" "$([ "$C_RECON" = 1 ] && echo On || echo Off)"); picker_ok $? || return 1
    if [ "$r" = "On" ]; then
        cfg_set recon 1
        command -v sqlite3 >/dev/null 2>&1 || LOG yellow "Needs sqlite3: opkg update && opkg install sqlite3-cli"
    else
        cfg_set recon 0
    fi
}
set_ringtone() {
    local r; r=$(LIST_PICKER "Chat sound" bonus success alert warning none "${C_RINGTONE:-none}"); picker_ok $? || return 1
    cfg_set ringtone "$r"
}

first_run_setup() {
    LED MAGENTA
    PROMPT "PagerTAK setup
Enter your TAK Server details. Change them later under Menu > Settings."
    set_host || return 1
    set_proto || return 1
    load_config
    set_port || return 1
    set_callsign || return 1
    set_team || return 1
    set_role || return 1
    cfg_set configured 1
    load_config
}

# ---------------------------------------------------------------------------
# Menus. "X >" opens a submenu, "< Back" goes up one level. Each menu reopens
# on the item you picked last time.
# ---------------------------------------------------------------------------
settings_apply() {  # settings_apply [reconnect]
    load_config
    [ "$1" = reconnect ] && : > "$RUN/reconnect"
    : > "$RUN/reload"
    [ "${WEB_LOADED:-0}" = 1 ] && web_cfg_write
    return 0
}

menu_settings_server() {
    local r st last="Server host"
    while :; do
        r=$(LIST_PICKER "TAK server" "Server host" "Protocol" "Port" "Certificates" "Enroll" "Test connection" "< Back" "$last"); picker_ok $? || return
        last=$r
        case "$r" in
            "Server host")  set_host && settings_apply reconnect ;;
            "Protocol")     set_proto && settings_apply reconnect ;;
            "Port")         set_port && settings_apply reconnect ;;
            "Certificates") setup_certs force && settings_apply reconnect ;;
            "Enroll")       [ "${SETUP_LOADED:-0}" = 1 ] && cert_menu && settings_apply reconnect ;;
            "Test connection")
                if [ "${SETUP_LOADED:-0}" = 1 ]; then
                    local id; id=$(START_SPINNER "Testing"); tak_test; STOP_SPINNER "$id"
                    st=$(cat "$RUN/test.status"); if [ "${st%%|*}" = ok ]; then LOG green "${st#*|}"; else ERROR_DIALOG "${st#*|}"; fi
                fi ;;
            *) return ;;
        esac
    done
}

menu_settings_identity() {
    local r last="Callsign"
    while :; do
        r=$(LIST_PICKER "Identity" "Callsign" "Team color" "Role" "< Back" "$last"); picker_ok $? || return
        last=$r
        case "$r" in
            "Callsign")   set_callsign; settings_apply ;;
            "Team color") set_team; settings_apply ;;
            "Role")       set_role; settings_apply ;;
            *) return ;;
        esac
    done
}

menu_settings_position() {
    local r last="Manual position"
    while :; do
        r=$(LIST_PICKER "Position" "Manual position" "Report interval" "< Back" "$last"); picker_ok $? || return
        last=$r
        case "$r" in
            "Manual position") set_manual; settings_apply ;;
            "Report interval") set_interval; settings_apply ;;
            *) return ;;
        esac
    done
}

menu_settings_map() {
    local r last="Map source"
    while :; do
        r=$(LIST_PICKER "Map" "Map source" "Custom tile URL" "Cache map tiles" "< Back" "$last"); picker_ok $? || return
        last=$r
        case "$r" in
            "Map source")      set_map_source; settings_apply ;;
            "Custom tile URL") set_tile_url; settings_apply ;;
            "Cache map tiles") cache_tiles ;;
            *) return ;;
        esac
    done
}

settings_menu() {
    local r last="TAK server >"
    while :; do
        r=$(LIST_PICKER "Settings" "TAK server >" "Identity >" "Position >" "Map >" "Web console >" "Chat sound" "Clear received items" "Reset all settings" "< Back" "$last")
        picker_ok $? || return
        last=$r
        case "$r" in
            "TAK server >") menu_settings_server ;;
            "Identity >")   menu_settings_identity ;;
            "Position >")   menu_settings_position ;;
            "Map >")        menu_settings_map ;;
            "Clear received items")
                [ "$(CONFIRMATION_DIALOG "Clear everything received from TAK (users, markers, aircraft...)? Your own markers and zones stay.")" = "$DUCKYSCRIPT_USER_CONFIRMED" ] && clear_received > /dev/null ;;
            "Web console >")
                if [ "$WEB_LOADED" = 1 ]; then menu_web; else ERROR_DIALOG "Web console files missing: include/web.sh, web/"; fi ;;
            "Chat sound")   set_ringtone; settings_apply ;;
            "Reset all settings")
                if [ "$(CONFIRMATION_DIALOG "Erase all PagerTAK settings?")" = "$DUCKYSCRIPT_USER_CONFIRMED" ]; then
                    for k in host proto port callsign team role interval manual_pos ringtone tile_url map_source recon medevac_freq watch watch_profile watch_new_open watch_any_new trk trk_follow trk_any trk_flockaxon trk_send rid rid_channel rid_chat survey_share api_port web web_port web_listen web_https md md_min md_me md_who md_chat cot_radius cot_hide configured; do
                        PAYLOAD_DEL_CONFIG "$CFG_NS" "$k" >/dev/null 2>&1
                    done
                    LOG yellow "Settings erased - restart PagerTAK"
                fi ;;
            *) return ;;
        esac
    done
}

menu_chat() {
    local r msg last="Message All" reply=() cs label
    if [ -s "$RUN/lastfrom" ]; then
        IFS='|' read -r _ cs label < "$RUN/lastfrom"; reply=("Reply to $cs")
        [ -s "$RUN/unread" ] && last="Reply to $cs"
    fi
    chat_mark_read                            # opening Chat = read (sends read receipts)
    while :; do
        r=$(LIST_PICKER "Chat" "${reply[@]}" "Message All" "Quick message All" "Direct message" "Chat history" "Clear chat history" "< Back" "$last"); picker_ok $? || return
        last=$r
        case "$r" in
            "Reply to "*)        reply_last ;;
            "Message All")       msg=$(type_msg "Message to All") && send_chat "$msg" ;;
            "Quick message All") msg=$(pick_quick) && send_chat "$msg" ;;
            "Direct message")    direct_message ;;
            "Chat history")      show_history ;;
            "Clear chat history")
                [ "$(CONFIRMATION_DIALOG "Delete all chat history on this Pager? Other TAK devices keep their copies.")" = "$DUCKYSCRIPT_USER_CONFIRMED" ] || continue
                chat_clear; reply=(); last="Message All" ;;
            *) return ;;
        esac
    done
}

menu_reports() {
    local r last="SALUTE"
    if [ "$REPORTS_LOADED" != 1 ]; then ERROR_DIALOG "Reports module missing: $PAYLOAD_DIR/include/reports.sh"; return; fi
    while :; do
        r=$(LIST_PICKER "Reports" "SALUTE" "SITREP" "MEDEVAC 9-line" "Damage assessment" "Report history" "< Back" "$last")
        picker_ok $? || return
        last=$r
        case "$r" in
            "SALUTE")            report_salute ;;
            "SITREP")            report_sitrep ;;
            "MEDEVAC 9-line")    report_medevac ;;
            "Damage assessment") report_damage ;;
            "Report history")    report_history ;;
            *) return ;;
        esac
    done
}

menu_sensors() {
    local r stats deauth
    while :; do
        stats="Sensor stats in reports: $([ "$C_RECON" = 1 ] && echo On || echo Off)"
        if [ -f /root/payloads/alerts/deauth_flood_detected/PagerTAK_Deauth_Alert/payload.sh ] \
           || [ -f /mmc/root/payloads/alerts/deauth_flood_detected/PagerTAK_Deauth_Alert/payload.sh ]; then
            deauth="Deauth alerts: installed"
        else
            deauth="Deauth alerts: not installed"
        fi
        r=$(LIST_PICKER "Sensors" "Geofences >" "Evil-twin watch >" "Trackers / counter-surv >" "Drone Remote ID >" "Site survey >" "Man-down watchdog >" "$stats" "$deauth" "< Back" "Evil-twin watch >"); picker_ok $? || return
        case "$r" in
            "Geofences >")
                if [ "${GEO_LOADED:-0}" = 1 ]; then menu_geofence; else ERROR_DIALOG "Geofence module missing: include/geofence.sh"; fi ;;
            "Man-down watchdog >")
                if [ "${MD_LOADED:-0}" = 1 ]; then menu_mandown; else ERROR_DIALOG "Watchdog module missing: include/watchdog.sh"; fi ;;
            "Site survey >")
                if [ "$SURVEY_LOADED" = 1 ] && [ "$WATCH_LOADED" = 1 ]; then menu_survey; else ERROR_DIALOG "Survey module missing: include/survey.sh"; fi ;;
            "Drone Remote ID >")
                if [ "$RID_LOADED" = 1 ]; then menu_remoteid; else ERROR_DIALOG "Remote ID module missing: include/remoteid.sh"; fi ;;
            "Trackers / counter-surv >")
                if [ "$TRK_LOADED" = 1 ]; then menu_trackers; else ERROR_DIALOG "Tracker module missing: include/trackers.sh"; fi ;;
            "Evil-twin watch >")
                if [ "$WATCH_LOADED" = 1 ]; then menu_watch; else ERROR_DIALOG "Watch module missing: include/watch.sh"; fi ;;
            "Sensor stats"*) set_recon; settings_apply ;;
            "Deauth alerts: installed") LOG green "PagerTAK Deauth Alert is installed. Enable it under Alerts > Deauth Flood Detected." ;;
            "Deauth alerts"*) LOG yellow "Copy PagerTAK_Deauth_Alert to /root/payloads/alerts/deauth_flood_detected/ (see README)" ;;
            *) return ;;
        esac
    done
}

# Returns 10 when the user chose to exit PagerTAK
main_menu() {
    local r e911
    while :; do
        if [ -f "$RUN/emergency" ]; then e911="CANCEL ALERT (active)"; else e911="SEND ALERT"; fi
        local chat="Chat >" n; n=$(unread_count); [ "$n" -gt 0 ] && chat="Chat > ($n new)"
        r=$(LIST_PICKER "PagerTAK" "Map" "Contacts" "$chat" "Reports >" "Sensors >" "$e911" "Send position now" \
            "Status" "Settings >" "Exit PagerTAK" "< Back" "$([ "${MENU_LAST:-Map}" = "Chat >" ] && echo "$chat" || echo "${MENU_LAST:-Map}")")
        picker_ok $? || return 0
        MENU_LAST=$r; [[ $r == "Chat >"* ]] && MENU_LAST="Chat >"
        case "$r" in
            "Map")               map_view ;;
            "Contacts")          contacts_view ;;
            "Chat >"*)           menu_chat ;;
            "Reports >")         menu_reports ;;
            "Sensors >")         menu_sensors ;;
            "SEND ALERT"|"CANCEL ALERT"*) emergency_menu ;;
            "Send position now") : > "$RUN/sa_now"; LOG "Position report queued" ;;
            "Status")            show_status ;;
            "Settings >")        settings_menu ;;
            "Exit PagerTAK")
                [ "$(CONFIRMATION_DIALOG "Exit PagerTAK? You will drop off the TAK map.")" = "$DUCKYSCRIPT_USER_CONFIRMED" ] && return 10 ;;
            *) return 0 ;;
        esac
        MENU_LAST=$r; [[ $r == "Chat >"* ]] && MENU_LAST="Chat >"
    done
}

cleanup() {
    : > "$RUN/stop" 2>/dev/null
    [ -n "$ENGINE_PID" ] && kill "$ENGINE_PID" 2>/dev/null
    [ -n "$GPS_PID" ] && kill "$GPS_PID" 2>/dev/null
    [ -f "$RUN/watch.pid" ] && kill "$(cat "$RUN/watch.pid")" 2>/dev/null
    [ -f "$RUN/trk.pid" ] && kill "$(cat "$RUN/trk.pid")" 2>/dev/null
    for f in "$RUN/rid_bridge.pid" "$RUN/rid_worker.pid" "$RUN/web.pid" "$RUN/webcmd.pid" "$RUN/geo.pid" "$RUN/md.pid" "$RUN/prune.pid"; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; done
    [ "${SIGINT_LOADED:-0}" = 1 ] && [ -f "$RUN/fox.pid" ] && fox_stop quiet
    if [ -f "$RUN/survey.dir" ]; then
        sd=$(cat "$RUN/survey.dir"); rm -f "$sd/active"; kill "$(cat "$RUN/survey.pid" 2>/dev/null)" 2>/dev/null
        IFS='|' read -r sn ss _ sc < "$sd/meta" 2>/dev/null && printf '%s|%s|%s|%s\n' "$sn" "$ss" "$(date +%s)" "$sc" > "$sd/meta"
    fi
    pkill -f "hcitool -i .* lescan --passive" 2>/dev/null
    pkill -f "s_client -quiet -connect $C_HOST:$C_PORT" 2>/dev/null
    sleep 1
    rm -rf "$RUN"
    LED OFF
}

#############################################################################
# Main
#############################################################################

rm -rf "$RUN"; mkdir -p "$RUN/outbox" "$RUN/tracks.d" "$LOOT_DIR"
load_config

# Web console and setup helpers are loaded first: setup can happen in a browser
WEB_LOADED=0
if [ -f "$PAYLOAD_DIR/include/web.sh" ] && [ -f "$PAYLOAD_DIR/web/pagertak_web.py" ]; then
    # shellcheck source=include/web.sh
    . "$PAYLOAD_DIR/include/web.sh" && WEB_LOADED=1
fi
SETUP_LOADED=0
if [ -f "$PAYLOAD_DIR/include/setup.sh" ]; then
    # shellcheck source=include/setup.sh
    . "$PAYLOAD_DIR/include/setup.sh" && SETUP_LOADED=1
fi

if [ "$(cfg_get configured 0)" != 1 ] || [ "$C_HOST" = "tak.example.com" ]; then
    r=""
    if [ "$WEB_LOADED" = 1 ] && [ "$SETUP_LOADED" = 1 ]; then
        r=$(LIST_PICKER "PagerTAK setup" "On the Pager" "In a web browser" "On the Pager"); picker_ok $? || { LOG red "Setup cancelled"; exit 0; }
    fi
    if [ "$r" = "In a web browser" ]; then
        setup_in_browser || { LOG red "Setup cancelled"; exit 0; }
    else
        first_run_setup || { LOG red "Setup cancelled"; exit 0; }
    fi
fi

if [ "$C_PROTO" = "tls" ]; then
    setup_certs || { LED FAIL; exit 0; }   # setup_certs already showed why
    [ "$SETUP_LOADED" = 1 ] && cert_expiry_check
fi

trap cleanup EXIT

# Optional modules
REPORTS_LOADED=0
if [ -f "$PAYLOAD_DIR/include/reports.sh" ] && [ -f "$PAYLOAD_DIR/include/geo.awk" ]; then
    # shellcheck source=include/reports.sh
    . "$PAYLOAD_DIR/include/reports.sh" && REPORTS_LOADED=1
fi
WATCH_LOADED=0
if [ -f "$PAYLOAD_DIR/include/watch.sh" ]; then
    # shellcheck source=include/watch.sh
    . "$PAYLOAD_DIR/include/watch.sh" && WATCH_LOADED=1
fi
TRK_LOADED=0
if [ -f "$PAYLOAD_DIR/include/trackers.sh" ]; then
    # shellcheck source=include/trackers.sh
    . "$PAYLOAD_DIR/include/trackers.sh" && TRK_LOADED=1
fi
RID_LOADED=0
if [ -f "$PAYLOAD_DIR/include/remoteid.sh" ]; then
    # shellcheck source=include/remoteid.sh
    . "$PAYLOAD_DIR/include/remoteid.sh" && RID_LOADED=1
fi
SURVEY_LOADED=0
if [ -f "$PAYLOAD_DIR/include/survey.sh" ]; then
    # shellcheck source=include/survey.sh
    . "$PAYLOAD_DIR/include/survey.sh" && SURVEY_LOADED=1
    # a survey left "active" by a crash or power loss is closed out
    for d in "$SURVEY_ROOT"/*/active; do [ -e "$d" ] && rm -f "$d"; done
fi
SIGINT_LOADED=0
if [ -f "$PAYLOAD_DIR/include/sigint.sh" ]; then
    # shellcheck source=include/sigint.sh
    . "$PAYLOAD_DIR/include/sigint.sh" && SIGINT_LOADED=1
fi
MD_LOADED=0
if [ -f "$PAYLOAD_DIR/include/watchdog.sh" ]; then
    # shellcheck source=include/watchdog.sh
    . "$PAYLOAD_DIR/include/watchdog.sh" && MD_LOADED=1
fi
GEO_LOADED=0
if [ -f "$PAYLOAD_DIR/include/geofence.sh" ]; then
    # shellcheck source=include/geofence.sh
    . "$PAYLOAD_DIR/include/geofence.sh" && GEO_LOADED=1
fi

gps_loop &
GPS_PID=$!
engine &
ENGINE_PID=$!
echo "$ENGINE_PID" > "$RUN/engine.pid"
# resume the evil-twin watch if it was on
if [ "$WATCH_LOADED" = 1 ] && [ "$(cfg_get watch 0)" = 1 ]; then
    watch_start || LOG yellow "Evil-twin watch is ON but recon/sqlite3 is not available"
fi
if [ "$TRK_LOADED" = 1 ] && [ "$(cfg_get trk 0)" = 1 ]; then
    trk_start || LOG yellow "Tracker watch is ON but Bluetooth tools are missing"
fi
if [ "$RID_LOADED" = 1 ] && [ "$(cfg_get rid 0)" = 1 ]; then
    rid_start || LOG yellow "Drone watch is ON but Python / the decoder is missing"
fi

if [ "$GEO_LOADED" = 1 ] && [ -s "$GEO_FILE" ]; then
    geo_start
fi
prune_loop > /dev/null 2>&1 &
echo $! > "$RUN/prune.pid"
if [ "$MD_LOADED" = 1 ] && [ "$(cfg_get md 0)" = 1 ]; then
    : > "$RUN/activity"; md_start; LOG green "Man-down watchdog ON"
fi
if [ "$WEB_LOADED" = 1 ] && [ "$(cfg_get web 0)" = 1 ]; then
    if web_start; then web_show_urls; else LOG yellow "Web console is ON but did not start (Settings > Web console)"; fi
fi

LOG green "PagerTAK $PAYLOAD_VERSION - $C_CALLSIGN"
LOG white "A=Menu (Map, Chat, Reports, Send Alert...)"
LOG white "UP=Quick msg DOWN=Type msg"
LOG white "RIGHT=Send pos LEFT=Status B=Exit"

while :; do
    BUTTON=$(WAIT_FOR_INPUT 1)
    [ -z "$BUTTON" ] && continue
    : > "$RUN/activity"            # any button = "I'm OK" for the man-down watchdog
    case "$BUTTON" in
        A)     main_menu; [ $? -eq 10 ] && { LOG red "Exiting PagerTAK..."; break; } ;;
        UP)    msg=$(pick_quick) && send_chat "$msg" ;;
        DOWN)  msg=$(type_msg "Message to All") && send_chat "$msg" ;;
        RIGHT) : > "$RUN/sa_now"; LOG "Position report queued" ;;
        LEFT)  show_status ;;
        B)
            if [ "$(CONFIRMATION_DIALOG "Exit PagerTAK? You will drop off the TAK map.")" = "$DUCKYSCRIPT_USER_CONFIRMED" ]; then
                LOG red "Exiting PagerTAK..."
                break
            fi ;;
    esac
done

exit 0
