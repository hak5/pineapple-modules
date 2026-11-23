#!/bin/bash
# PagerTAK site survey -> ATAK data package - sourced by payload.sh.
#
# While a survey runs, every SURVEY_EVERY seconds the Pager records which
# access points recon heard (signal, security, channel) together with its GPS
# position, plus a GPS track. "Build" turns that into an ATAK data package
# (map/survey_build.py): KML overlay with APs color-coded by security, your
# approved (evil-twin profile) networks highlighted, the walk track, CSV and a
# summary. "Upload" sends it to the TAK Server's Marti API with the Pager's
# client cert; "share" also sends a b-f-t-r file-share so every TAK user gets
# a one-tap download.
# Detection only: reads the recon database, transmits nothing over the air.

SURVEY_EVERY=${SURVEY_EVERY:-15}
SURVEY_ROOT="$LOOT_DIR/surveys"

survey_dir_active() { cat "$RUN/survey.dir" 2>/dev/null; }
survey_running() { kill -0 "$(cat "$RUN/survey.pid" 2>/dev/null)" 2>/dev/null; }

survey_loop() {  # survey_loop DIR
    local dir=$1 now lat lon line
    trap 'exit 0' TERM INT
    while [ ! -f "$RUN/stop" ] && [ -f "$dir/active" ]; do
        now=$(date +%s)
        if best_position && [ "$P_HOW" = "m-g" ]; then lat=$P_LAT; lon=$P_LON; else lat="-"; lon="-"; fi
        echo "$now $lat $lon" >> "$dir/track"
        recon_aps $((now - SURVEY_EVERY - 5)) | while IFS=$'\t' read -r b h e c s; do
            [ -n "$b" ] && echo "$now $lat $lon $b $h $e $c $s"
        done >> "$dir/samples"
        sleep "$SURVEY_EVERY"
    done
}

survey_start() {
    local name
    command -v sqlite3 >/dev/null 2>&1 || { ERROR_DIALOG "Needs sqlite3: opkg update && opkg install sqlite3-cli"; return; }
    recon_db >/dev/null || { ERROR_DIALOG "No recon database. Start Recon first."; return; }
    name=$(TEXT_PICKER "Survey name (site)" "$(cfg_get watch_profile Site)"); picker_ok $? || return
    [ -z "$name" ] && return
    survey_begin "$name"
    LOG green "Survey '$name' started - walk the site. Sensors > Site survey to stop."
}

# survey_begin NAME - starts recording (no dialogs; used by the menu and the web console)
survey_begin() {
    local name=$1 dir
    dir="$SURVEY_ROOT/$(tr -c 'A-Za-z0-9_-' '_' <<< "$name" | sed 's/_$//')_$(date +%Y%m%d_%H%M)"
    mkdir -p "$dir"; : > "$dir/active"; : > "$dir/samples"; : > "$dir/track"
    printf '%s|%s||%s\n' "$name" "$(date +%s)" "$C_CALLSIGN" > "$dir/meta"
    echo "$dir" > "$RUN/survey.dir"
    survey_loop "$dir" &
    echo $! > "$RUN/survey.pid"
    best_position && [ "$P_HOW" = "m-g" ] || LOG yellow "No live GPS fix - APs can't be placed until you have one"
}

survey_stop() {
    local dir; dir=$(survey_dir_active)
    [ -n "$dir" ] || return
    survey_end
    if [ "$(CONFIRMATION_DIALOG "Build the data package and upload it to the TAK server now?")" = "$DUCKYSCRIPT_USER_CONFIRMED" ]; then
        survey_build_upload "$dir"
    fi
}

# survey_end - stops recording and closes the survey (no dialogs). Sets SV_DIR.
survey_end() {
    local dir n s c; dir=$(survey_dir_active)
    [ -n "$dir" ] || return 1
    rm -f "$dir/active"
    kill "$(cat "$RUN/survey.pid" 2>/dev/null)" 2>/dev/null
    rm -f "$RUN/survey.pid" "$RUN/survey.dir"
    IFS='|' read -r n s _ c < "$dir/meta"; printf '%s|%s|%s|%s\n' "$n" "$s" "$(date +%s)" "$c" > "$dir/meta"
    SV_DIR=$dir
    LOG green "Survey stopped: $(cut -d' ' -f4 "$dir/samples" | sort -u | grep -c .) APs recorded"
}

# survey_build DIR -> sets SV_ZIP SV_NAME SV_STATS
survey_build() {
    local dir=$1 out approved=""
    configure_python || { rid_install >/dev/null 2>&1 && configure_python; } || { ERROR_DIALOG "Needs Python 3 (python3-light)."; return 1; }
    watch_files 2>/dev/null; [ -s "$W_APPROVED" ] && approved=$W_APPROVED
    out=$("$PYTHON_BIN" -B "$MAP_DIR/survey_build.py" "$dir" --out "$dir/package" ${approved:+--approved "$approved"} 2>&1)
    SV_ZIP=$(sed -n 's/^ZIP //p' <<< "$out"); SV_NAME=$(sed -n 's/^NAME //p' <<< "$out"); SV_STATS=$(sed -n 's/^STATS //p' <<< "$out")
    [ -s "$SV_ZIP" ] || { ERROR_DIALOG "Package build failed: $(tail -n1 <<< "$out" | cut -c1-80)"; return 1; }
    LOG green "Package: $SV_STATS"
    LOG white "Saved: $SV_ZIP"
}

# Upload SV_ZIP to the TAK Server Marti API. Sets SV_URL SV_HASH SV_SIZE
survey_upload() {
    local port scheme base url tls=() hash
    hash=$(sha256sum "$SV_ZIP" | awk '{print $1}'); SV_HASH=$hash; SV_SIZE=$(wc -c < "$SV_ZIP")
    if [ "$C_PROTO" = "tls" ]; then
        scheme=https; port=$(cfg_get api_port 8443)
        tls=(--cert "$CERT_DIR/$C_CLIENT_PEM" --key "$CERT_DIR/$C_CLIENT_PEM")
        if [ -f "$CERT_DIR/$C_CA_PEM" ]; then tls+=(--cacert "$CERT_DIR/$C_CA_PEM"); else tls+=(-k); fi
    else
        scheme=http; port=$(cfg_get api_port 8080)
    fi
    base="$scheme://$C_HOST:$port"
    url=$(curl -sS --fail --max-time 120 "${tls[@]}" \
          -F "assetfile=@$SV_ZIP;filename=$SV_NAME;type=application/x-zip-compressed" \
          "$base/Marti/sync/missionupload?hash=$hash&filename=$SV_NAME&creatorUid=$C_UID" 2> ${LOG_TMP:-/tmp/pagertak}-upload.log)
    if [ $? -ne 0 ] || [ -z "$url" ]; then
        ERROR_DIALOG "Upload failed ($base). See ${LOG_TMP:-/tmp/pagertak}-upload.log - package is saved in loot."
        return 1
    fi
    SV_URL=$(tr -d '\r\n' <<< "$url")
    [[ $SV_URL == http* ]] || SV_URL="$base/Marti/api/sync/metadata/$hash/tool"
    # make it visible in the server's Data Packages list
    curl -sS --max-time 30 "${tls[@]}" -X PUT -H "Content-Type: text/plain" --data "public" \
        "$base/Marti/api/sync/metadata/$hash/tool" >> ${LOG_TMP:-/tmp/pagertak}-upload.log 2>&1
    LOG green "Uploaded to TAK server ($((SV_SIZE / 1024)) KB)"
    return 0
}

# File-share notice: every TAK user gets a one-tap download of the package
survey_share() {
    local now xml id
    now=$(date +%s); id=$(new_id)
    best_position || { P_LAT=0; P_LON=0; }
    xml="<event version=\"2.0\" uid=\"$id\" type=\"b-f-t-r\" how=\"h-e\" time=\"$(iso_time "$now")\" start=\"$(iso_time "$now")\" stale=\"$(iso_time $((now + 600)))\">"
    xml+="<point lat=\"$P_LAT\" lon=\"$P_LON\" hae=\"0\" ce=\"9999999.0\" le=\"9999999.0\"/><detail>"
    xml+="<fileshare filename=\"$(xml_esc "$SV_NAME")\" senderUrl=\"$(xml_esc "$SV_URL")\" sizeInBytes=\"$SV_SIZE\" sha256=\"$SV_HASH\""
    xml+=" senderUid=\"$C_UID\" senderCallsign=\"$(xml_esc "$C_CALLSIGN")\" name=\"$(xml_esc "${SV_NAME%.zip}")\"/>"
    xml+="<ackrequest uid=\"$(new_id)\" ackrequested=\"true\" tag=\"$(xml_esc "${SV_NAME%.zip}")\"/></detail></event>"
    queue_cot "$xml"
    send_chat "Site survey uploaded: ${SV_NAME%.zip} - $SV_STATS. Accept the data package to load the overlay."
    LOG green "Shared with all TAK users"
}

survey_build_upload() {  # survey_build_upload DIR
    survey_build "$1" || return
    if [ "$(CONFIRMATION_DIALOG "Upload ${SV_NAME} to the TAK server?")" = "$DUCKYSCRIPT_USER_CONFIRMED" ]; then
        local id; id=$(START_SPINNER "Uploading")
        survey_upload; local rc=$?
        STOP_SPINNER "$id"
        [ $rc -eq 0 ] || return
        [ "$(cfg_get survey_share 1)" = 1 ] && survey_share
    fi
}

survey_past() {
    local dirs=() items=() i r d n s
    mapfile -t dirs < <(ls -1dt "$SURVEY_ROOT"/*/ 2>/dev/null | head -n 12)
    [ ${#dirs[@]} -eq 0 ] && { LOG "No surveys yet"; return; }
    for d in "${dirs[@]}"; do
        d=${d%/}; IFS='|' read -r n s _ _ < "$d/meta"
        items+=("$n $(date -d "@$s" '+%m-%d %H:%M' 2>/dev/null) ($(cut -d' ' -f4 "$d/samples" | sort -u | grep -c .) AP)")
    done
    r=$(LIST_PICKER "Past surveys" "${items[@]}" "< Back" "${items[0]}"); picker_ok $? || return
    for i in "${!items[@]}"; do
        if [ "${items[$i]}" = "$r" ]; then
            d=${dirs[$i]%/}
            [ -f "$d/active" ] && { LOG yellow "That survey is still running - stop it first"; return; }
            survey_build_upload "$d"
        fi
    done
}

menu_survey() {
    local r st share port last
    while :; do
        if survey_running; then st="Stop survey ($(( ($(date +%s) - $(cut -d'|' -f2 "$(survey_dir_active)/meta")) / 60 ))m, $(cut -d' ' -f4 "$(survey_dir_active)/samples" | sort -u | grep -c .) AP)"
        else st="Start survey"; fi
        share="Share with all TAK users: $([ "$(cfg_get survey_share 1)" = 1 ] && echo On || echo Off)"
        port="TAK API port: $(cfg_get api_port "$([ "$C_PROTO" = tls ] && echo 8443 || echo 8080)")"
        r=$(LIST_PICKER "Site survey" "$st" "Past surveys (build/upload)" "$share" "$port" "< Back" "${last:-$st}"); picker_ok $? || return
        last=$r
        case "$r" in
            "Start survey")   survey_start; last="Stop survey" ;;
            "Stop survey"*)   survey_stop; last="Start survey" ;;
            "Past surveys"*)  survey_past ;;
            "Share with"*)    cfg_set survey_share "$([ "$(cfg_get survey_share 1)" = 1 ] && echo 0 || echo 1)" ;;
            "TAK API port"*)
                r=$(NUMBER_PICKER "TAK API port (8443 cert, 8080 http)" "$(cfg_get api_port 8443)"); picker_ok $? || continue
                [[ $r =~ ^[0-9]+$ ]] && cfg_set api_port "$r" ;;
            *) return ;;
        esac
    done
}
