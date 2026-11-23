#!/bin/bash
# PagerTAK web console - sourced by payload.sh.
#
# Starts web/pagertak_web.py (a small stdlib-only Python web server) and a
# command loop. The browser gets the map, chat, 911, reports, sensors and
# settings. The web server never talks to TAK itself: it reads $RUN and drops
# commands into $RUN/webcmd/*.req, which web_cmd_loop below turns into the same
# CoT the Pager menus send (one code path, one writer to the TAK socket).
#
# Security: password login; listens on every interface by default, so the
# console opens by host name, IP or the USB address (Listen on can narrow it to
# the USB address, or USB + NetBird / WireGuard VPN); optional HTTPS with a
# self-signed certificate.

WEB_DIR="$PAYLOAD_DIR/web"
WEB_AUTH="$WEB_DIR/auth"
WEB_LOG="${LOG_TMP:-/tmp/pagertak}-web.log"
WEB_TLS_CERT="$WEB_DIR/tls/cert.pem"
WEB_TLS_KEY="$WEB_DIR/tls/key.pem"
# Leaflet 1.9.4 (BSD-2-Clause), downloaded pinned + SHA-256 verified on first use
WEB_LEAFLET_DIR="$WEB_DIR/static/leaflet"
ITEMS_FILE="$PAYLOAD_DIR/items.txt"     # markers made in the web console

web_running() { kill -0 "$(cat "$RUN/web.pid" 2>/dev/null)" 2>/dev/null; }
web_port() { cfg_get web_port "${WEB_PORT:-8484}"; }
web_scheme() { [ "$(cfg_get web_https 0)" = 1 ] && echo https || echo http; }

# Snapshot of the settings the browser shows (the web server cannot call PAYLOAD_GET_CONFIG)
web_cfg_write() {
    local mods="" q
    [ "${WATCH_LOADED:-0}" = 1 ] && mods+="watch,"
    [ "${TRK_LOADED:-0}" = 1 ] && mods+="trk,"
    [ "${RID_LOADED:-0}" = 1 ] && mods+="rid,"
    [ "${SURVEY_LOADED:-0}" = 1 ] && [ "${WATCH_LOADED:-0}" = 1 ] && mods+="survey,"
    q=$(IFS='|'; printf '%s' "${QUICK_MESSAGES[*]}")
    {
        printf 'version=%s\ndevice=%s\ncallsign=%s\nuid=%s\nteam=%s\nrole=%s\n' \
            "$PAYLOAD_VERSION" "$DEVICE_NAME" "$C_CALLSIGN" "$C_UID" "$C_TEAM" "$C_ROLE"
        printf 'host=%s\nport=%s\nproto=%s\ninterval=%s\nmanual_pos=%s\nmap_source=%s\nrecon=%s\n' \
            "$C_HOST" "$C_PORT" "$C_PROTO" "$C_INTERVAL" "$C_MANUAL" "$C_MAP_SOURCE" "$C_RECON"
        printf 'watch=%s\nwatch_profile=%s\ntrk=%s\nrid=%s\nrid_channel=%s\nquick=%s\nmodules=%s\n' \
            "$(cfg_get watch 0)" "$(cfg_get watch_profile Site)" "$(cfg_get trk 0)" "$(cfg_get rid 0)" \
            "$(cfg_get rid_channel 6)" "$q" "${mods%,}"
        printf 'recon_db=%s\n' "$(declare -F recon_db >/dev/null && recon_db 2>/dev/null)"
        printf 'md=%s\nmd_min=%s\nmd_me=%s\nmd_who=%s\nmd_chat=%s\ncot_radius=%s\n' "$(cfg_get md 0)" "$(cfg_get md_min "$MANDOWN_MINUTES")" \
            "$(cfg_get md_me 1)" "$(cfg_get md_who "")" "$(cfg_get md_chat 0)" "$(cfg_get cot_radius "$COT_RADIUS_KM")"
        printf 'cot_hide=%s\nreceipts=%s\n' "$(cfg_get cot_hide "")" "$C_RECEIPTS"
        printf 'setup=%s\n' "$([ -f "$RUN/setup_mode" ] && echo 1 || echo 0)"
        printf 'web_listen=%s\nweb_urls=%s\n' "$(cfg_get web_listen all)" "$(web_urls | tr '\n' ' ')"
        if [ "${SETUP_LOADED:-0}" = 1 ] && [ "$C_PROTO" = tls ]; then
            printf 'cert_days=%s\ncert_cn=%s\n' "$(cert_days 2>/dev/null)" "$(cert_cn 2>/dev/null)"
        fi
    } > "$RUN/web_cfg.tmp" 2>/dev/null && mv "$RUN/web_cfg.tmp" "$RUN/web_cfg"
}

# "iface address" for every IPv4 address (ip if present, else busybox ifconfig)
web_addrs() {
    if command -v ip >/dev/null 2>&1; then
        ip -4 -o addr show 2>/dev/null | awk '{split($4, a, "/"); print $2, a[1]}'
    else
        ifconfig 2>/dev/null | awk '/^[^ \t]/ {i=$1} /inet addr:/ {sub("addr:", "", $2); print i, $2}'
    fi
}

# Addresses to listen on: all (default) | vpn (USB + NetBird/WireGuard) | usb
web_lan_ip() {
    local ip
    ip=$(uci -q get network.lan.ipaddr 2>/dev/null); ip=${ip%%/*}
    if [ -n "$ip" ] && web_addrs | grep -q " $ip\$"; then printf '%s' "$ip"; return; fi
    ip=$(web_addrs | awk '$1=="br-lan" {print $2; exit}')
    printf '%s' "${ip:-172.16.52.1}"
}
web_vpn_ips() { web_addrs | awk '$1=="wt0" || $1=="wg0" || $1=="tun0" {print $2}'; }
web_bind_list() {
    local mode list
    mode=$(cfg_get web_listen all)
    case "$mode" in
        all) printf '0.0.0.0'; return ;;
        vpn) list="$(web_lan_ip),$(web_vpn_ips | tr '\n' ',')" ;;
        *)   list=$(web_lan_ip) ;;
    esac
    printf '%s' "${list%,}"
}
web_urls() {
    local a port; port=$(web_port)
    if [ "$(cfg_get web_listen all)" = all ]; then
        a=$(cat /proc/sys/kernel/hostname 2>/dev/null)
        [ -n "$a" ] && [ "$a" != OpenWrt ] && printf '%s://%s:%s\n' "$(web_scheme)" "$a" "$port"
        for a in $(web_addrs | awk '$1!="lo" {print $2}'); do printf '%s://%s:%s\n' "$(web_scheme)" "$a" "$port"; done
    else
        tr ',' '\n' <<< "$(web_bind_list)" | while read -r a; do [ -n "$a" ] && printf '%s://%s:%s\n' "$(web_scheme)" "$a" "$port"; done
    fi
}

# Leaflet 1.9.4 (BSD-2-Clause) is included in web/static/leaflet
web_leaflet_ok() { [ -s "$WEB_LEAFLET_DIR/leaflet.js" ] && [ -s "$WEB_LEAFLET_DIR/leaflet.css" ]; }
web_ready() { configure_python && web_leaflet_ok; }

# Installs python3-light if needed. Asks first.
web_install() {
    local r id
    web_leaflet_ok || { ERROR_DIALOG "web/static/leaflet is missing - copy the full $PRODUCT_NAME folder again."; return 1; }
    configure_python && return 0
    r=$(CONFIRMATION_DIALOG "The web console needs python3-light. Install it now? (internet)")
    [ "$r" = "$DUCKYSCRIPT_USER_CONFIRMED" ] || return 1
    id=$(START_SPINNER "Installing Python")
    { opkg update; opkg -d mmc install python3-light || opkg install python3-light; } > ${LOG_TMP:-/tmp/pagertak}-web-install.log 2>&1
    STOP_SPINNER "$id"
    web_ready && { LOG green "Web console ready"; return 0; }
    ERROR_DIALOG "Python install failed. See ${LOG_TMP:-/tmp/pagertak}-web-install.log"
    return 1
}

# web_set_password PASSWORD -> writes the salted hash to web/auth
web_set_password() {
    local line
    configure_python || return 1
    line=$(printf '%s\n' "$1" | "$PYTHON_BIN" -B "$WEB_DIR/pagertak_web.py" --hash-password 2>/dev/null) || return 1
    [ -n "$line" ] || return 1
    mkdir -p "$WEB_DIR"
    ( umask 077; printf '%s\n' "$line" > "$WEB_AUTH.tmp" ) && mv "$WEB_AUTH.tmp" "$WEB_AUTH"
}

web_tls_ready() {
    [ -s "$WEB_TLS_CERT" ] && [ -s "$WEB_TLS_KEY" ] && return 0
    command -v openssl >/dev/null 2>&1 || return 1
    mkdir -p "$(dirname "$WEB_TLS_CERT")"
    ( umask 077
      openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 3650 \
          -subj "/CN=$PRODUCT_NAME $C_CALLSIGN" -keyout "$WEB_TLS_KEY" -out "$WEB_TLS_CERT" >/dev/null 2>&1 )
    [ -s "$WEB_TLS_CERT" ] && [ -s "$WEB_TLS_KEY" ]
}

# web_start -> 0 ok, 1 not installed, 2 no password, 3 HTTPS not possible, 4 server failed
web_start() {
    local args=() binds
    web_stop
    web_ready || return 1
    [ -s "$WEB_AUTH" ] || return 2
    binds=$(web_bind_list)
    args=(--run "$RUN" --loot "$LOOT_DIR" --bind "$binds" --port "$(web_port)" --auth "$WEB_AUTH"
          --static "$WEB_DIR/static" --map-dir "$MAP_DIR" --tiles "$TILE_DIR" --tile-url "$C_TILE_URL"
          --items "$ITEMS_FILE" --geofences "$PAYLOAD_DIR/geofences.txt"
          --max-age "$TRACK_MAX_AGE" --product "${PRODUCT_NAME:-PagerTAK}")
    if [ "$(cfg_get web_https 0)" = 1 ]; then
        "$PYTHON_BIN" -c 'import ssl' 2>/dev/null && web_tls_ready || return 3
        args+=(--tls-cert "$WEB_TLS_CERT" --tls-key "$WEB_TLS_KEY")
    fi
    web_cfg_write
    mkdir -p "$RUN/webcmd"
    PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -B "$WEB_DIR/pagertak_web.py" "${args[@]}" > "$WEB_LOG" 2>&1 &
    echo $! > "$RUN/web.pid"
    web_cmd_loop &
    echo $! > "$RUN/webcmd.pid"
    sleep 2
    web_running || { web_stop; return 4; }
    return 0
}

web_stop() {
    local f p
    for f in "$RUN/web.pid" "$RUN/webcmd.pid"; do
        p=$(cat "$f" 2>/dev/null); [ -n "$p" ] && kill "$p" 2>/dev/null
        rm -f "$f"
    done
}

#############################################################################
# Command loop (background): $RUN/webcmd/<id>.req -> action -> <id>.res
#############################################################################
web_cmd_loop() {
    local f n=0
    # never pop dialogs on the Pager for work started from the browser
    ERROR_DIALOG() { LOG red "$*"; WEB_ERR="$*"; }
    START_SPINNER() { :; }
    STOP_SPINNER() { :; }
    while [ ! -f "$RUN/stop" ]; do
        for f in "$RUN"/webcmd/*.req; do
            [ -e "$f" ] || break
            web_handle "$f"
        done
        if [ $((n % 10)) -eq 0 ]; then
            [ -f "$RUN/reload" ] || load_config
            web_cfg_write
            local b; b=$(BATTERY_PERCENT 2>/dev/null); b=${b//[^0-9]/}; [ -n "$b" ] && printf '%s\n' "$b" > "$RUN/battery"
        fi
        n=$((n + 1))
        sleep 1
    done
}

# web_call FUNC ARGS... -> runs FUNC in this shell, last output line in WEB_RES.
# Not $(...): a background loop started inside a command substitution would keep
# its pipe open (bash saves stdout on fd 10+) and hang this command loop.
web_call() {
    "$@" > "$RUN/webcmd/.out" 2>/dev/null
    WEB_RES=$(tail -n 1 "$RUN/webcmd/.out")
}

web_num() { [[ $1 =~ ^[0-9]{1,3}$ ]] && printf '%s' "$((10#$1))" || printf '0'; }
web_text() { local v=${1//|//}; printf '%s' "${v:0:${2:-200}}"; }   # '|' would break our pipe-separated files
web_in() { local v=$1 x; shift; for x in "$@"; do [ "$v" = "$x" ] && return 0; done; return 1; }

web_handle() {
    local req=$1 id line k v res="err|Unknown command" ok
    local -A Q=()
    id=$(basename "$req" .req)
    while IFS= read -r line; do
        k=${line%%=*}; v=${line#*=}
        [[ $k =~ ^[a-z][a-z0-9_]*$ ]] && Q[$k]=$v
    done < "$req"
    rm -f "$req"
    load_config
    WEB_ERR=""
    case "${Q[cmd]}" in
        chat)
            local text; text=$(web_text "${Q[text]}" 400)
            if [ -z "$text" ]; then res="err|Empty message"
            elif [ -n "${Q[to_uid]}" ]; then send_chat "$text" "${Q[to_uid]}" "$(web_text "${Q[to_cs]}" 60)"; res="ok|Sent to ${Q[to_cs]}"
            else send_chat "$text"; res="ok|Sent to All Chat Rooms"
            fi ;;
        chat_read)
            chat_mark_read; res="ok|Read" ;;
        chat_clear)
            chat_clear; res="ok|Chat history deleted from the $DEVICE_WORD" ;;
        sa_now)
            : > "$RUN/sa_now"; res="ok|Position report queued" ;;
        emergency)
            local kind=${Q[kind]:-911} label="" dest="" d tos=()
            web_in "$kind" "${EMERG_KINDS[@]}" || kind=911
            if [ "$kind" = custom ]; then label=$(web_text "${Q[label]}" 30); [ -n "$label" ] || label=Custom; label=${label//:/ }; fi
            IFS=',' read -ra tos <<< "${Q[to]}"
            for d in "${tos[@]}"; do
                [[ $d =~ ^[A-Za-z0-9._@-]{1,100}:.{1,40}$ ]] && dest+="${dest:+,}${d//|//}"
            done
            emergency_send "$kind" "$label" "$dest" ""
            res="ok|$(emerg_label "$kind" "$label") sent to $([ -n "$dest" ] && echo "chosen contacts" || echo everyone)" ;;
        cancel_emergency)
            if emergency_cancel; then res="ok|Emergency cancelled"; else res="err|No alert is active"; fi ;;
        clear_received)
            web_call clear_received; res=$WEB_RES ;;
        imok)
            : > "$RUN/activity"; res="ok|Thanks - man-down timer reset" ;;
        report)   web_call web_report Q; res=$WEB_RES ;;
        sensor)   web_call web_sensor "${Q[name]}" "${Q[on]}"; res=$WEB_RES ;;
        sensor_install) web_call sensor_install "${Q[name]}"; res=$WEB_RES ;;
        watch_scan)
            if [ "${WATCH_LOADED:-0}" != 1 ]; then res="err|Watch module missing"
            else local m; m=$(web_num "${Q[mins]}"); [ "$m" -ge 1 ] || m=15; web_call watch_scan "$m"; res=$WEB_RES; fi ;;
        watch_save)
            if [ "${WATCH_LOADED:-0}" != 1 ]; then res="err|Watch module missing"
            else web_call watch_save "$(web_text "${Q[profile]}" 40)" "${Q[ssids]}"; res=$WEB_RES; fi ;;
        settings) web_call web_settings Q; res=$WEB_RES ;;
        web_listen) web_call web_set_listen "${Q[mode]}"; res=$WEB_RES ;;
        survey_start)
            if [ "${SURVEY_LOADED:-0}" != 1 ]; then res="err|Survey module missing"
            elif survey_running; then res="err|A survey is already running"
            elif ! command -v sqlite3 >/dev/null 2>&1; then res="err|Needs sqlite3 (opkg install sqlite3-cli)"
            elif ! recon_db >/dev/null; then res="err|No recon database yet - start Recon first"
            else
                local name; name=$(web_text "${Q[name]:-Site}" 40); [ -z "$name" ] && name=Site
                survey_begin "$name" > /dev/null; LOG green "Survey '$name' started (web console)"; res="ok|Survey '$name' started"
            fi ;;
        survey_stop)
            if [ "${SURVEY_LOADED:-0}" != 1 ] || [ -z "$(survey_dir_active)" ]; then res="err|No survey running"
            else
                survey_end > /dev/null
                if [ "${Q[upload]}" = 1 ]; then
                    ( survey_build "$SV_DIR" && survey_upload && { [ "$(cfg_get survey_share 1)" = 1 ] && survey_share; } ) > /dev/null 2>&1 &
                    res="ok|Survey stopped - building and uploading the data package"
                else
                    res="ok|Survey stopped"
                fi
            fi ;;
        cert)     web_call web_cert "${Q[kind]}" "${Q[upload]}"; res=$WEB_RES ;;
        certfile)
            if [ "${SETUP_LOADED:-0}" = 1 ] && web_in "${Q[kind]}" client ca; then
                web_call cert_import "${Q[kind]}" "${Q[upload]}" "${Q[password]}"; res=$WEB_RES
            else res="err|Setup module missing"; fi
            rm -f "${Q[upload]}" ;;
        import_pkg)
            local cf="" af=""
            [[ ${Q[client_file]} =~ ^[0-9a-f-]+-client\.p12$ ]] && cf="$RUN/webcmd/${Q[client_file]}"
            [[ ${Q[ca_file]} =~ ^[0-9a-f-]+-ca\.p12$ ]] && af="$RUN/webcmd/${Q[ca_file]}"
            web_call pkg_import "${Q[host]}" "${Q[port]}" "${Q[proto]}" "$cf" "${Q[client_pw]}" "$af" "${Q[ca_pw]}"; res=$WEB_RES ;;
        enroll)
            if [ "${SETUP_LOADED:-0}" != 1 ]; then res="err|Setup module missing"
            elif [ "$(cut -d'|' -f1 "$RUN/enroll.status" 2>/dev/null)" = busy ] && [ -n "$(find "$RUN/enroll.status" -mmin -2 2>/dev/null)" ]; then res="err|Enrollment already running"
            else
                job_status enroll "busy|Starting..."
                local eport=${Q[port]:-8446}; [[ $eport =~ ^[0-9]{1,5}$ ]] || eport=8446
                cfg_set enroll_port "$eport"
                ( tak_enroll "$(web_text "${Q[host]}" 200)" "${Q[user]}" "${Q[password]}" "$eport" ) > /dev/null 2>&1 &
                res="ok|Enrolling - this takes up to a minute"
            fi ;;
        tak_test)
            if [ "${SETUP_LOADED:-0}" = 1 ]; then
                job_status test "busy|Testing..."; ( load_config; tak_test ) > /dev/null 2>&1 &
                res="ok|Testing the connection..."
            else res="err|Setup module missing"; fi ;;
        setup_done)
            if [ "${SETUP_LOADED:-0}" = 1 ]; then web_call setup_finish; res=$WEB_RES; else res="err|Setup module missing"; fi ;;
        share)
            local tgt; tgt=$(web_target "${Q[send]}" "${Q[to_uid]}" "${Q[to_cs]}")
            if [ -z "$tgt" ]; then res="err|Pick who to send it to"
            else
                mv "${Q[upload]}" "$RUN/share.zip"
                echo "busy|Uploading ${Q[name]}..." > "$RUN/share.status"
                chat_log "FILE Sending ${Q[name]} to $(target_label "$tgt")..."
                ( share_send "$RUN/share.zip" "${Q[name]}" "$tgt" ) > /dev/null 2>&1 &
                res="ok|Uploading ${Q[name]} - it is sent when the upload finishes"
            fi ;;
        channels_get) web_call web_channels get; res=$WEB_RES ;;
        channels_set) web_call web_channels set "${Q[upload]}"; res=$WEB_RES ;;
        marker)   web_call web_marker Q; res=$WEB_RES ;;
        item_send) web_call item_send "${Q[id]}" "$(web_target "${Q[send]}" "${Q[to_uid]}" "${Q[to_cs]}")"; res=$WEB_RES ;;
        item_del)  web_call item_del "${Q[id]}"; res=$WEB_RES ;;
        geofence_add)
            if [ "${GEO_LOADED:-0}" = 1 ]; then
                web_call geo_add "$(web_text "${Q[name]}" 40)" "${Q[shape]}" "${Q[data]}" "${Q[who]}" "${Q[chat]}" \
                      "$(web_target "${Q[send]}" "${Q[to_uid]}" "${Q[to_cs]}")" \
                      "$(web_target "${Q[alert]}" "${Q[alert_uid]}" "${Q[alert_cs]}")"; res=$WEB_RES
                geo_start
            else res="err|Geofence module missing"; fi ;;
        geofence_del)
            if [ "${GEO_LOADED:-0}" = 1 ]; then web_call geo_del "${Q[id]}"; res=$WEB_RES; else res="err|Geofence module missing"; fi ;;
        radio)
            if [ "${SIGINT_LOADED:-0}" = 1 ]; then web_call radio_set "${Q[action]}" "${Q[channel]}"; res=$WEB_RES; else res="err|SIGINT module missing"; fi ;;
        fox_start)
            if [ "${SIGINT_LOADED:-0}" = 1 ]; then
                fox_start "${Q[mac]}" "$(web_text "${Q[label]}" 40)" "${Q[lock]}" "${Q[channel]}" > "$RUN/fox.res" 2>/dev/null
                res=$(tail -n 1 "$RUN/fox.res")
            else res="err|SIGINT module missing"; fi ;;
        fox_stop)
            if [ "${SIGINT_LOADED:-0}" = 1 ]; then web_call fox_stop; res=$WEB_RES; else res="err|SIGINT module missing"; fi ;;
    esac
    [ -n "${Q[upload]}" ] && rm -f "${Q[upload]}"
    printf '%s\n' "$res" > "$RUN/webcmd/$id.res.tmp" && mv "$RUN/webcmd/$id.res.tmp" "$RUN/webcmd/$id.res"
}

# web_report ARRAYNAME -> prints result line
web_report() {
    local -n R=$1
    [ "${REPORTS_LOADED:-0}" = 1 ] || { echo "err|Reports module missing"; return; }
    local kind=${R[kind]}
    if [ "$kind" != sitrep ]; then
        if valid_coord "${R[lat]}" && valid_coord "${R[lon]}"; then
            R_LAT=${R[lat]}; R_LON=${R[lon]}; R_LOCDESC=$(web_text "${R[locdesc]:-picked on map}" 40)
        elif best_position; then
            R_LAT=$P_LAT; R_LON=$P_LON; R_LOCDESC="at $C_CALLSIGN"
        else
            echo "err|No position - pick the location on the map"; return
        fi
        R_MGRS=$(to_mgrs "$R_LAT" "$R_LON")
    elif ! best_position; then
        echo "err|No position - need a GPS fix or a manual position"; return
    fi
    REPORT_NOCONFIRM=1
    case "$kind" in
        salute)
            local aff=${R[affiliation]}; web_in "$aff" Suspect Hostile Unknown Neutral || aff=Suspect
            report_salute_send "$(web_num "${R[size]}")" "$(web_text "${R[what]:-Persons}" 40)" "$(web_text "${R[activity]}" 40)" \
                "$(web_text "${R[unit]}" 40)" "$(web_text "${R[time]}" 30)" "$(web_text "${R[equipment]}" 60)" "$aff" "$(web_text "${R[notes]}" 200)" ;;
        sitrep)
            local st=${R[status]}; web_in "$st" "All OK" "Minor issues" "Need support" "Under threat" || st="All OK"
            report_sitrep_send "$st" "$(web_text "${R[situation]}" 60)" "$(web_num "${R[pax]}")" "$(web_text "${R[needs]:-None}" 120)" ;;
        medevac)
            local sec=${R[sec]} mark=${R[mark]} equip=${R[equip]} terr=${R[terrain]} freq
            [[ $sec =~ ^[0-3]$ ]] || sec=0; [[ $mark =~ ^[0-4]$ ]] || mark=2
            web_in "$equip" None Hoist "Extraction equipment" Ventilator Other || equip=None
            web_in "$terr" None Slope Rough Loose Other || terr=None
            freq=$(web_text "${R[freq]:-$C_CALLSIGN}" 40)
            report_medevac_send "$freq" \
                "$(web_num "${R[urg]}") $(web_num "${R[urgs]}") $(web_num "${R[pri]}") $(web_num "${R[rou]}") $(web_num "${R[con]}")" \
                "$equip" "$(web_num "${R[lit]}") $(web_num "${R[amb]}")" "$sec" "$mark" "$([ "$mark" = 4 ] && web_text "${R[mark_other]}" 40)" \
                "$(web_num "${R[usm]}") $(web_num "${R[usc]}") $(web_num "${R[num]}") $(web_num "${R[nuc]}") $(web_num "${R[epw]}") $(web_num "${R[chi]}")" \
                "$terr" ;;
        damage)
            local dmg=${R[damage]} acc=${R[access]}
            web_in "$dmg" Destroyed Major Minor Affected "No damage" || dmg=Major
            web_in "$acc" Open Limited Blocked || acc=Open
            report_damage_send "$(web_text "${R[structure]}" 40)" "$dmg" "$(web_text "${R[hazards]:-None}" 160)" \
                "$(web_num "${R[injured]}")" "$(web_num "${R[trapped]}")" "$acc" "$(web_text "${R[notes]}" 200)" ;;
        *) echo "err|Unknown report"; return ;;
    esac > /dev/null 2>&1
    echo "ok|${kind^^} sent"
}

# sensor_install trk - installs what a sensor needs, in the background (internet)
sensor_install() {
    local pkgs log what
    case "$1" in
        trk) pkgs=${BT_PACKAGES:-bluez-utils}; log=${LOG_TMP:-/tmp/pagertak}-bt-install.log; what="Bluetooth tools" ;;
        *) echo "err|Unknown sensor"; return ;;
    esac
    if kill -0 "$(cat "$RUN/install.pid" 2>/dev/null)" 2>/dev/null; then echo "err|An install is already running"; return; fi
    (
        # shellcheck disable=SC2086
        { echo "== $(date) opkg install $pkgs"; opkg update; opkg install $pkgs; } >> "$log" 2>&1
        rm -f "$RUN/install.pid"
        if command -v btmon >/dev/null 2>&1 && command -v hcitool >/dev/null 2>&1; then LOG green "$what installed"
        else LOG red "$what install failed - see $log"; fi
    ) > /dev/null 2>&1 &
    echo $! > "$RUN/install.pid"
    echo "ok|Installing $what - this takes a minute or two"
}

web_sensor() {  # web_sensor name 1|0
    local name=$1 on=$2
    case "$name" in
        watch)
            [ "${WATCH_LOADED:-0}" = 1 ] || { echo "err|Watch module missing"; return; }
            if [ "$on" = 1 ]; then
                command -v sqlite3 >/dev/null 2>&1 || { echo "err|Needs sqlite3 (opkg install sqlite3-cli)"; return; }
                recon_db >/dev/null || { echo "err|No recon database yet - start Recon first"; return; }
                watch_files; [ -s "$W_APPROVED" ] || { echo "err|Learn the site first: Find networks, tick yours, Save"; return; }
                cfg_set watch 1; watch_start > /dev/null; echo "ok|Evil-twin watch ON"
            else cfg_set watch 0; watch_stop; echo "ok|Evil-twin watch OFF"; fi ;;
        trk)
            [ "${TRK_LOADED:-0}" = 1 ] || { echo "err|Tracker module missing"; return; }
            if [ "$on" = 1 ]; then
                command -v btmon >/dev/null 2>&1 && command -v hcitool >/dev/null 2>&1 || { echo "err|Install the Bluetooth tools first (button below)"; return; }
                cfg_set trk 1; trk_start > /dev/null; echo "ok|Tracker watch ON"
            else cfg_set trk 0; trk_stop; echo "ok|Tracker watch OFF"; fi ;;
        rid)
            [ "${RID_LOADED:-0}" = 1 ] || { echo "err|Remote ID module missing"; return; }
            if [ "$on" = 1 ]; then
                command -v tcpdump >/dev/null 2>&1 || { echo "err|tcpdump is missing (opkg install tcpdump)"; return; }
                configure_python || { echo "err|Install Python first (button below)"; return; }
                cfg_set rid 1; rid_start > /dev/null; echo "ok|Drone watch ON"
            else cfg_set rid 0; rid_stop; echo "ok|Drone watch OFF (Wi-Fi channel restored)"; fi ;;
        recon)
            if [ "$on" = 1 ]; then cfg_set recon 1; else cfg_set recon 0; fi
            : > "$RUN/reload"; echo "ok|Sensor stats $([ "$on" = 1 ] && echo ON || echo OFF)" ;;
        *) echo "err|Unknown sensor" ;;
    esac
}

web_settings() {
    local -n W=$1
    local changed=0 reconnect=0 v t lat lon
    if [ -n "${W[callsign]+x}" ]; then
        v=$(web_text "${W[callsign]}" 40)
        [ -n "$v" ] || { echo "err|Callsign is empty"; return; }
        cfg_set callsign "$v"; changed=1
    fi
    if [ -n "${W[team]+x}" ]; then
        web_in "${W[team]}" White Yellow Orange Magenta Red Maroon Purple "Dark Blue" Blue Cyan Teal Green "Dark Green" Brown || { echo "err|Unknown team"; return; }
        cfg_set team "${W[team]}"; changed=1
    fi
    if [ -n "${W[role]+x}" ]; then
        web_in "${W[role]}" "Team Member" "Team Lead" HQ Sniper Medic "Forward Observer" RTO K9 || { echo "err|Unknown role"; return; }
        cfg_set role "${W[role]}"; changed=1
    fi
    if [ -n "${W[interval]+x}" ]; then
        v=${W[interval]}; [[ $v =~ ^[0-9]+$ ]] && [ "$v" -ge 5 ] && [ "$v" -le 3600 ] || { echo "err|Interval must be 5-3600 seconds"; return; }
        cfg_set interval "$v"; changed=1
    fi
    if [ -n "${W[manual_pos]+x}" ]; then
        v=${W[manual_pos]// /}
        if [ -n "$v" ]; then
            lat=${v%%,*}; lon=${v##*,}
            valid_coord "$lat" && valid_coord "$lon" && [ "$v" != "$lat" ] || { echo "err|Manual position must be lat,lon"; return; }
            cfg_set manual_pos "$lat,$lon"
        else
            PAYLOAD_DEL_CONFIG "$CFG_NS" manual_pos >/dev/null 2>&1
        fi
        changed=1
    fi
    if [ -n "${W[host]+x}" ]; then
        v=${W[host]}; v=${v#*://}; v=${v%%/*}                   # accept a pasted https://name/ too
        [[ $v =~ ^[A-Za-z0-9.:_-]{1,200}$ ]] || { echo "err|Bad host name"; return; }
        [ "$v" != "$C_HOST" ] && reconnect=1; cfg_set host "$v"; changed=1
    fi
    if [ -n "${W[proto]+x}" ]; then
        web_in "${W[proto]}" tls tcp udp || { echo "err|Unknown protocol"; return; }
        [ "${W[proto]}" != "$C_PROTO" ] && reconnect=1; cfg_set proto "${W[proto]}"; changed=1
    fi
    if [ -n "${W[port]+x}" ]; then
        v=${W[port]}; [[ $v =~ ^[0-9]+$ ]] && [ "$v" -ge 1 ] && [ "$v" -le 65535 ] || { echo "err|Bad port"; return; }
        [ "$v" != "$C_PORT" ] && reconnect=1; cfg_set port "$v"; changed=1
    fi
    if [ -n "${W[cot_hide]+x}" ]; then
        v=${W[cot_hide]}; [[ $v =~ ^[a-z,]{0,80}$ ]] || { echo "err|Bad filter"; return; }
        cfg_set cot_hide "$v"; changed=1
    fi
    if [ -n "${W[cot_radius]+x}" ]; then
        v=${W[cot_radius]}; [[ $v =~ ^[0-9]{1,4}$ ]] || { echo "err|Radius in whole km (0 = everything)"; return; }
        cfg_set cot_radius "$v"; changed=1
    fi
    local mdc=0
    for v in md md_me md_chat; do
        if [ -n "${W[$v]+x}" ]; then [ "${W[$v]}" = 1 ] && cfg_set "$v" 1 || cfg_set "$v" 0; changed=1; mdc=1; fi
    done
    if [ -n "${W[md_min]+x}" ]; then
        v=${W[md_min]}; [[ $v =~ ^[0-9]+$ ]] && [ "$v" -ge 1 ] && [ "$v" -le 240 ] || { echo "err|Minutes 1-240"; return; }
        cfg_set md_min "$v"; changed=1; mdc=1
    fi
    if [ -n "${W[md_who]+x}" ]; then
        v=${W[md_who]}; [[ $v =~ ^[A-Za-z0-9._@,-]{0,2000}$ ]] || { echo "err|Bad contact list"; return; }
        cfg_set md_who "$v"; changed=1; mdc=1
    fi
    if [ "$mdc" = 1 ] && [ "${MD_LOADED:-0}" = 1 ]; then : > "$RUN/activity"; md_apply > /dev/null; fi
    if [ -n "${W[quick]+x}" ]; then
        local qs=() qi
        IFS='|' read -r -a qs <<< "${W[quick]}"
        v=""
        for qi in "${qs[@]}"; do
            qi=${qi:0:36}; qi=${qi#"${qi%%[![:space:]]*}"}; qi=${qi%"${qi##*[![:space:]]}"}
            [ -n "$qi" ] && v+="${v:+|}$qi"
        done
        if [ -z "$v" ]; then PAYLOAD_DEL_CONFIG "$CFG_NS" quick_msgs >/dev/null 2>&1; else cfg_set quick_msgs "$v"; fi
        changed=1
    fi
    if [ -n "${W[receipts]+x}" ]; then
        [ "${W[receipts]}" = 1 ] && cfg_set receipts 1 || cfg_set receipts 0; changed=1
    fi
    if [ -n "${W[rid_channel]+x}" ]; then
        v=${W[rid_channel]}; [[ $v =~ ^([1-9]|1[0-3])$ ]] || { echo "err|Channel 1-13"; return; }
        cfg_set rid_channel "$v"; changed=1
        [ "${RID_LOADED:-0}" = 1 ] && rid_running && rid_start > /dev/null
    fi
    [ "$changed" = 1 ] || { echo "err|Nothing to save"; return; }
    [ "$reconnect" = 1 ] && : > "$RUN/reconnect"
    : > "$RUN/reload"
    load_config; web_cfg_write
    t="Saved"
    [ "$reconnect" = 1 ] && t="Saved - reconnecting to $C_HOST:$C_PORT"
    [ "$C_PROTO" = tls ] && [ ! -s "$CERT_DIR/$C_CLIENT_PEM" ] && t="$t (no client certificate yet - upload one)"
    echo "ok|$t"
}

# Marti API (port 8443 with the client cert for TLS, 8080 otherwise): sets MARTI_BASE and MARTI_TLS
marti_setup() {
    MARTI_TLS=()
    if [ "$C_PROTO" = tls ]; then
        MARTI_BASE="https://$C_HOST:$(cfg_get api_port 8443)"
        MARTI_TLS=(--cert "$CERT_DIR/$C_CLIENT_PEM" --key "$CERT_DIR/$C_CLIENT_PEM")
        if [ -f "$CERT_DIR/$C_CA_PEM" ]; then MARTI_TLS+=(--cacert "$CERT_DIR/$C_CA_PEM"); else MARTI_TLS+=(-k); fi
    else
        MARTI_BASE="http://$C_HOST:$(cfg_get api_port 8080)"
    fi
}

# marti_curl CURL_ARGS... - curl to the TAK server API with the client cert.
# If the API port's certificate does not verify against the TAK CA (some
# servers put a public certificate on 8443, or the name does not match the
# address you connect to), it tries the system CAs, then without checking.
marti_curl() {
    local rc
    curl --connect-timeout 15 "${MARTI_TLS[@]}" "$@"; rc=$?
    [ "$C_PROTO" = tls ] || return $rc
    case $rc in 35|51|58|60|77|83) ;; *) return $rc ;; esac
    echo "[pagertak] TLS verify failed (curl $rc) - retrying with system CAs" >&2
    curl --connect-timeout 15 --cert "$CERT_DIR/$C_CLIENT_PEM" --key "$CERT_DIR/$C_CLIENT_PEM" "$@"; rc=$?
    case $rc in 35|51|60|77|83) ;; *) return $rc ;; esac
    echo "[pagertak] retrying without certificate check" >&2
    curl --connect-timeout 15 --cert "$CERT_DIR/$C_CLIENT_PEM" --key "$CERT_DIR/$C_CLIENT_PEM" -k "$@"
}

# curl exit code -> short reason for the page
curl_reason() {
    case $1 in
        6) echo "cannot resolve $C_HOST" ;; 7) echo "cannot connect to ${MARTI_BASE#*//}" ;;
        28) echo "timed out talking to ${MARTI_BASE#*//}" ;; 35|58) echo "TLS handshake failed (client cert?)" ;;
        22) echo "server answered HTTP ${2:-error}" ;; 52) echo "empty reply (wrong port or protocol?)" ;;
        *) echo "curl error $1" ;;
    esac
}

# TAK channels (server groups): web_channels get | set FILE(json list from the web server)
web_channels() {
    local code
    marti_setup
    if [ "$1" = set ]; then
        [ -s "$2" ] || { echo "err|Nothing to save"; return; }
        code=$(marti_curl -s -o ${LOG_TMP:-/tmp/pagertak}-channels.log -w '%{http_code}' --max-time 20 -X PUT \
               -H "Content-Type: application/json" --data-binary @"$2" \
               "$MARTI_BASE/Marti/api/groups/active?clientUid=$C_UID")
        code=${code: -3}
        case "$code" in
            2*) LOG green "TAK channels updated (web console)"; echo "ok|Channels saved" ;;
            000) echo "err|Cannot reach $MARTI_BASE" ;;
            *) echo "err|TAK Server answered HTTP $code" ;;
        esac
        return
    fi
    code=$(marti_curl -s -o "$RUN/channels.json.tmp" -w '%{http_code}' --max-time 20 \
           "$MARTI_BASE/Marti/api/groups/all?useCache=true")
    code=${code: -3}
    if [ "${code:0:1}" = 2 ] && grep -q '"name"' "$RUN/channels.json.tmp"; then
        mv "$RUN/channels.json.tmp" "$RUN/channels.json"; echo "ok|Loaded"
    else
        rm -f "$RUN/channels.json.tmp"
        case "$code" in
            000) echo "err|Cannot reach $MARTI_BASE" ;;
            401|403) echo "err|TAK Server refused the certificate (HTTP $code)" ;;
            *) echo "err|No channel list from the TAK Server (HTTP $code)" ;;
        esac
    fi
}

#############################################################################
# Markers and drawings you make: keep local, send to everyone, or to one contact
#############################################################################
# web_target send to_uid to_cs -> "" (keep local) | all | dm:UID:CALLSIGN
web_target() {
    case "$1" in
        all) echo all ;;
        dm)  [[ $2 =~ ^[A-Za-z0-9._@-]{1,100}$ ]] && echo "dm:$2:$(web_text "${3//:/ }" 40)" ;;
        *)   echo "" ;;
    esac
}
target_label() { case "$1" in all) echo "everyone" ;; dm:*) echo "${1#dm:*:}" ;; *) echo "nobody (local)" ;; esac; }

# cot_to XML TARGET -> the event, addressed to one callsign when TARGET is dm:...
cot_to() {
    local x=$1 cs
    if [[ $2 == dm:* ]]; then
        cs=$(xml_esc "${2#dm:*:}")
        x=${x/<detail>/<detail><marti><dest callsign=\"$cs\"/></marti>}
    fi
    printf '%s' "$x"
}

delete_cot() {  # delete_cot UID -> TAK delete event for an item
    local now; now=$(date +%s)
    printf '%s' "<event version=\"2.0\" uid=\"$PRODUCT_NAME-del-$now-$RANDOM\" type=\"t-x-d-d\" how=\"h-e\" time=\"$(iso_time "$now")\" start=\"$(iso_time "$now")\" stale=\"$(iso_time $((now + 120)))\"><point lat=\"0\" lon=\"0\" hae=\"0\" ce=\"9999999.0\" le=\"9999999.0\"/><detail><link uid=\"$1\" relation=\"none\" type=\"none\"/><__forcedelete/></detail></event>"
}

marker_cot() {  # marker_cot id name type lat lon color remarks
    local extra=""
    [ "$3" = "b-m-p-s-m" ] && extra="<color argb=\"$6\"/><usericon iconsetpath=\"COT_MAPPING_SPOTMAP/b-m-p-s-m/$6\"/>"
    report_marker_xml "$PRODUCT_NAME-MK-$1" "$3" "$2" "$4" "$5" "${7:-Marker from $C_CALLSIGN}" "$extra" 86400
}

item_set_sent() {  # item_set_sent id target
    awk -F'|' -v OFS='|' -v id="$1" -v t="$2" '$1 == id {$9 = t} {print}' "$ITEMS_FILE" > "$ITEMS_FILE.tmp" && mv "$ITEMS_FILE.tmp" "$ITEMS_FILE"
}

# Drop a marker: kind spot|hostile|suspect|unknown|friendly|neutral
web_marker() {
    local -n M=$1
    local name kind=${M[kind]} color=${M[color]} rem type id target
    valid_coord "${M[lat]}" && valid_coord "${M[lon]}" || { echo "err|Bad position"; return; }
    name=$(web_text "${M[name]}" 40); [ -n "$name" ] || name="Marker"
    rem=$(web_text "${M[remarks]}" 300)
    case "$kind" in
        hostile) type="a-h-G" ;; suspect) type="a-s-G" ;; unknown) type="a-u-G" ;;
        friendly) type="a-f-G" ;; neutral) type="a-n-G" ;;
        *) kind=spot; type="b-m-p-s-m" ;;
    esac
    [[ $color =~ ^-?[0-9]{1,10}$ ]] || color=-65536
    target=$(web_target "${M[send]}" "${M[to_uid]}" "${M[to_cs]}")
    id=$(head -c 8 /proc/sys/kernel/random/uuid)
    echo "$id|marker|$name|$type|${M[lat]}|${M[lon]}|$color|$rem|$target|$(date +%s)" >> "$ITEMS_FILE"
    track_seen "$PRODUCT_NAME-MK-$id" "${M[lat]}" "${M[lon]}" "$name" "$type" "" "mine"      # Pager map
    if [ -n "$target" ]; then
        queue_cot "$(cot_to "$(marker_cot "$id" "$name" "$type" "${M[lat]}" "${M[lon]}" "$color" "$rem")" "$target")"
        LOG green "Marker '$name' sent to $(target_label "$target")"
        echo "ok|Marker '$name' sent to $(target_label "$target")"
    else
        echo "ok|Marker '$name' saved on this map (not sent)"
    fi
}

# item_send ID TARGET - (re)send a marker or zone you made
item_send() {
    local id=$1 target=$2 line f
    [ -n "$target" ] || { echo "err|Pick who to send it to"; return; }
    if line=$(grep "^$id|" "$ITEMS_FILE" 2>/dev/null); then
        IFS='|' read -r _ _ n t la lo c r _ _ <<< "$line"
        queue_cot "$(cot_to "$(marker_cot "$id" "$n" "$t" "$la" "$lo" "$c" "$r")" "$target")"
        item_set_sent "$id" "$target"
    elif [ "${GEO_LOADED:-0}" = 1 ] && line=$(grep "^$id|" "$GEO_FILE" 2>/dev/null); then
        IFS='|' read -r _ n sh d _ _ _ <<< "$line"
        queue_cot "$(cot_to "$(geo_cot "$id" "$n" "$sh" "$d")" "$target")"
        f=$GEO_FILE
        awk -F'|' -v OFS='|' -v id="$id" -v t="$target" '$1 == id {$7 = t} {print}' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    else
        echo "err|No such item"; return
    fi
    echo "ok|'$n' sent to $(target_label "$target")"
}

# item_del ID - deletes a marker you made (and from TAK, if it was sent)
item_del() {
    local id=$1 line n sent
    [[ $id =~ ^[0-9a-f]{6,8}$ ]] || { echo "err|Bad id"; return; }
    if line=$(grep "^$id|" "$ITEMS_FILE" 2>/dev/null); then
        n=$(cut -d'|' -f3 <<< "$line"); sent=$(cut -d'|' -f9 <<< "$line")
        grep -v "^$id|" "$ITEMS_FILE" > "$ITEMS_FILE.tmp"; mv "$ITEMS_FILE.tmp" "$ITEMS_FILE"
        rm -f "$RUN/tracks.d/$PRODUCT_NAME-MK-$id"
        [ -n "$sent" ] && queue_cot "$(cot_to "$(delete_cot "$PRODUCT_NAME-MK-$id")" "$sent")"
        echo "ok|'$n' deleted$([ -n "$sent" ] && echo " here and in TAK")"
    elif [ "${GEO_LOADED:-0}" = 1 ]; then
        geo_del "$id"
    else
        echo "err|No such item"
    fi
}

# share_send ZIP NAME TARGET - data package to the TAK Server, then a file-share message (background)
share_send() {
    local zip=$1 name=$2 target=$3 hash size url now xml pkg
    pkg="${name%.*}"; pkg="${pkg// /_}.zip"      # safe_name() already limited it to A-Za-z0-9 ._-
    marti_setup
    hash=$(sha256sum "$zip" | awk '{print $1}'); size=$(wc -c < "$zip")
    local rc code body="$RUN/share.resp"
    {
        echo "== $(date) upload $pkg ($size bytes) to $MARTI_BASE"
        code=$(marti_curl -sS -o "$body" -w '%{http_code}' --max-time 300 \
            -F "assetfile=@$zip;filename=$pkg;type=application/x-zip-compressed" \
            "$MARTI_BASE/Marti/sync/missionupload?hash=$hash&filename=$pkg&creatorUid=$C_UID")
        rc=$?; code=${code: -3}             # retries print a code each; keep the last
        echo "curl exit $rc, HTTP $code"; head -c 400 "$body" 2>/dev/null; echo
    } > ${LOG_TMP:-/tmp/pagertak}-share.log 2>&1
    url=$(head -c 2000 "$body" 2>/dev/null); rm -f "$body"
    if [ "$rc" != 0 ] || [ "${code:0:1}" != 2 ]; then
        [ "$rc" = 0 ] && rc=22
        echo "err|Upload of $name failed: $(curl_reason "$rc" "$code")" > "$RUN/share.status"
        LOG red "File upload failed: $name ($(curl_reason "$rc" "$code"))"
        chat_log "FILE Not sent: $name - upload to the TAK Server failed ($(curl_reason "$rc" "$code"))"
        rm -f "$zip"; return 1
    fi
    url=$(tr -d '\r\n' <<< "$url"); [[ $url == http* ]] || url="$MARTI_BASE/Marti/sync/content?hash=$hash"
    now=$(date +%s); best_position || { P_LAT=0; P_LON=0; }
    xml="<event version=\"2.0\" uid=\"$(new_id)\" type=\"b-f-t-r\" how=\"h-e\" time=\"$(iso_time "$now")\" start=\"$(iso_time "$now")\" stale=\"$(iso_time $((now + 600)))\">"
    xml+="<point lat=\"$P_LAT\" lon=\"$P_LON\" hae=\"0\" ce=\"9999999.0\" le=\"9999999.0\"/><detail>"
    xml+="<fileshare filename=\"$(xml_esc "$pkg")\" senderUrl=\"$(xml_esc "$url")\" sizeInBytes=\"$size\" sha256=\"$hash\""
    xml+=" senderUid=\"$C_UID\" senderCallsign=\"$(xml_esc "$C_CALLSIGN")\" name=\"$(xml_esc "${name}")\"/>"
    xml+="<ackrequest uid=\"$(new_id)\" ackrequested=\"true\" tag=\"$(xml_esc "$name")\"/></detail></event>"
    queue_cot "$(cot_to "$xml" "$target")"
    echo "ok|$name sent to $(target_label "$target")" > "$RUN/share.status"
    LOG green "File sent: $name to $(target_label "$target")"
    chat_log "OUT [file] $C_CALLSIGN: $name to $(target_label "$target")"
    rm -f "$zip"
}

# QR code of the web address on the Pager screen (needs qrencode + python3-light)
web_qr() {
    local url r
    url=$(web_urls | grep -F "://$(web_lan_ip):" | head -n1)       # an IP works on any phone; a bare host name may not
    [ -n "$url" ] || url=$(web_urls | grep -E '://[0-9]' | head -n1)
    web_running && [ -n "$url" ] || { ERROR_DIALOG "Turn the web console on first."; return; }
    if ! command -v qrencode >/dev/null 2>&1; then
        r=$(CONFIRMATION_DIALOG "Install qrencode (about 40 KB) to draw the QR code? (internet)")
        [ "$r" = "$DUCKYSCRIPT_USER_CONFIRMED" ] || { LOG white "$url"; return; }
        local id; id=$(START_SPINNER "Installing qrencode")
        { opkg update; opkg install qrencode || opkg -d mmc install qrencode; } > ${LOG_TMP:-/tmp/pagertak}-qr-install.log 2>&1
        STOP_SPINNER "$id"
        command -v qrencode >/dev/null 2>&1 || { ERROR_DIALOG "Install failed. See ${LOG_TMP:-/tmp/pagertak}-qr-install.log"; LOG white "$url"; return; }
    fi
    if ! configure_python; then
        ERROR_DIALOG "The QR screen needs python3-light. Open Map once to install it."; LOG white "$url"; return
    fi
    UI_TAKEOVER >/dev/null 2>&1
    PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -B "$MAP_DIR/qr_show.py" --url "$url" > ${LOG_TMP:-/tmp/pagertak}-qr.log 2>&1
    UI_RELEASE >/dev/null 2>&1
}

web_cert() {  # web_cert client|ca FILE
    local kind=$1 f=$2 dest
    [ -s "$f" ] || { echo "err|Upload missing"; return; }
    grep -q -- "-----BEGIN CERTIFICATE-----" "$f" || { echo "err|No certificate in that file"; return; }
    if [ "$kind" = client ]; then
        grep -q -- "PRIVATE KEY-----" "$f" || { echo "err|The client PEM must hold the certificate AND its private key"; return; }
        grep -q "ENCRYPTED" "$f" && { echo "err|The private key is encrypted - export it unencrypted"; return; }
        dest="client.pem"
    elif [ "$kind" = ca ]; then
        dest="ca.pem"
    else
        echo "err|Unknown certificate kind"; return
    fi
    if command -v openssl >/dev/null 2>&1 && ! openssl x509 -noout -in "$f" >/dev/null 2>&1; then
        echo "err|openssl cannot read that certificate"; return
    fi
    mkdir -p "$CERT_DIR"
    [ -f "$CERT_DIR/$dest" ] && cp -p "$CERT_DIR/$dest" "$CERT_DIR/$dest.bak"
    ( umask 077; cp "$f" "$CERT_DIR/$dest.tmp" ) && mv "$CERT_DIR/$dest.tmp" "$CERT_DIR/$dest"
    if [ "$kind" = client ]; then cfg_set client_pem "$dest"; else cfg_set ca_pem "$dest"; fi
    : > "$RUN/reconnect"; : > "$RUN/reload"
    LOG green "Certificate updated from the web console ($dest)"
    echo "ok|Saved certs/$dest - reconnecting"
}

#############################################################################
# Pager menu: Settings > Web console
#############################################################################
web_show_urls() {
    local u
    LOG white "---- Web console ----"
    while read -r u; do [ -n "$u" ] && LOG green "$u"; done < <(web_urls)
    [ "$(web_scheme)" = https ] && LOG white "(self-signed: accept the browser warning once)"
}

web_password_prompt() {
    local pw def
    def=$(tr -dc 'a-km-zA-HJ-NP-Z2-9' < /dev/urandom 2>/dev/null | head -c 10)
    pw=$(TEXT_PICKER "Web password (8+ chars)" "$def"); picker_ok $? || return 1
    [ ${#pw} -ge 8 ] || { ERROR_DIALOG "Use at least 8 characters."; return 1; }
    web_set_password "$pw" || { ERROR_DIALOG "Could not save the password (Python missing?)"; return 1; }
    LOG green "Web password set: $pw"
}

web_turn_on() {
    local rc
    web_ready || web_install || return 1
    [ -s "$WEB_AUTH" ] || web_password_prompt || return 1
    web_start; rc=$?
    case $rc in
        0) cfg_set web 1; LOG green "Web console ON"; web_show_urls ;;
        3) ERROR_DIALOG "HTTPS needs openssl-util and python3-openssl: opkg install openssl-util python3-openssl" ;;
        4) ERROR_DIALOG "Web server did not start. See $WEB_LOG" ;;
        *) ERROR_DIALOG "Web console not ready (code $rc)" ;;
    esac
}

# web_set_listen all|vpn|usb -> saves it and restarts the console a moment
# later, after this reply has gone out. The restart runs detached because it
# also replaces this command loop.
web_set_listen() {
    case "$1" in
        all|vpn|usb) ;;
        *) echo "err|Unknown choice"; return ;;
    esac
    cfg_set web_listen "$1"
    ( sleep 2; web_start >/dev/null 2>&1 ) </dev/null >/dev/null 2>&1 &
    case "$1" in
        all) echo "ok|Listening on all interfaces (host name, IP and USB). Restarting the console..." ;;
        vpn) echo "ok|Listening on USB + VPN only. Restarting the console..." ;;
        usb) echo "ok|Listening on the USB address only. Restarting the console..." ;;
    esac
}

menu_web() {
    local r st listen https last
    while :; do
        if web_running; then st="Web console: ON"; else st="Web console: OFF"; fi
        case "$(cfg_get web_listen all)" in
            usb) listen="Listen on: USB only" ;; vpn) listen="Listen on: USB + VPN" ;; *) listen="Listen on: all interfaces" ;;
        esac
        https="HTTPS: $([ "$(cfg_get web_https 0)" = 1 ] && echo On || echo Off)"
        r=$(LIST_PICKER "Web console" "$st" "Show address" "Show QR code" "Set password" "$listen" "Port: $(web_port)" "$https" "< Back" "${last:-$st}")
        picker_ok $? || return
        last=$r
        case "$r" in
            "Web console: ON")  web_stop; cfg_set web 0; LOG yellow "Web console OFF" ;;
            "Web console: OFF") web_turn_on ;;
            "Show address")     if web_running; then web_show_urls; else LOG yellow "Web console is off"; fi ;;
            "Show QR code")     web_qr ;;
            "Set password")     web_password_prompt && web_running && web_start >/dev/null ;;
            "Listen on"*)
                case "$(cfg_get web_listen all)" in usb) r="USB only" ;; vpn) r="USB + VPN (NetBird/WireGuard)" ;; *) r="All interfaces" ;; esac
                r=$(LIST_PICKER "Listen on" "All interfaces" "USB + VPN (NetBird/WireGuard)" "USB only" "$r"); picker_ok $? || continue
                case "$r" in
                    "All interfaces") cfg_set web_listen all ;;
                    USB+*|"USB + VPN"*) cfg_set web_listen vpn ;;
                    *) cfg_set web_listen usb ;;
                esac
                web_running && { web_start >/dev/null; web_show_urls; } ;;
            "Port:"*)
                r=$(NUMBER_PICKER "Web console port" "$(web_port)"); picker_ok $? || continue
                [[ $r =~ ^[0-9]+$ ]] && [ "$r" -ge 1024 ] && [ "$r" -le 65535 ] && [ "$r" != 1471 ] || { ERROR_DIALOG "Use 1024-65535 (not 1471)"; continue; }
                cfg_set web_port "$r"; web_running && { web_start >/dev/null; web_show_urls; } ;;
            "HTTPS"*)
                if [ "$(cfg_get web_https 0)" = 1 ]; then cfg_set web_https 0; else cfg_set web_https 1; fi
                if web_running; then
                    web_start; case $? in
                        0) web_show_urls ;;
                        3) cfg_set web_https 0; web_start >/dev/null; ERROR_DIALOG "HTTPS needs openssl-util and python3-openssl: opkg install openssl-util python3-openssl" ;;
                        *) ERROR_DIALOG "Web server did not start. See $WEB_LOG" ;;
                    esac
                fi ;;
            *) return ;;
        esac
    done
}
