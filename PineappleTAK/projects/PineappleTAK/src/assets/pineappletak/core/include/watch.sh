#!/bin/bash
# PagerTAK evil-twin / rogue AP watch - sourced by payload.sh (not run on its own).
#
# Learn mode records every access point the Pager's recon engine sees while you
# stand at / walk the site, then you approve which networks (SSIDs) are yours.
# Watch mode then checks recon every WATCH_INTERVAL seconds and alerts TAK on:
#   EVIL TWIN   one of your SSIDs from a BSSID that is not approved
#   DOWNGRADE   one of your SSIDs seen open / weaker than approved
#   NEW OPEN    an open network that was not there when the site was learned (optional)
#   NEW AP      any access point not seen when learned (optional, noisy)
#
# Detection only: it reads the recon database, it transmits nothing over the air.
# Needs recon running and sqlite3 (opkg install sqlite3-cli).
#
# Site profiles live in $PAYLOAD_DIR/watch/<profile>.approved / .known
#   .approved  ssid_hex<TAB>bssid<TAB>enc     (your networks)
#   .known     bssid                           (everything seen while learning)

WATCH_DIR="$PAYLOAD_DIR/watch"
WATCH_INTERVAL=${WATCH_INTERVAL:-30}          # seconds between checks
WATCH_WINDOW=90            # look at APs heard in the last N seconds
WATCH_DEDUPE=1800          # re-alert the same BSSID after this many seconds
WATCH_LOG="$LOOT_DIR/watch.log"
WATCH_PID=""

recon_db() {
    local d
    for d in /root/recon/recon.db /mmc/root/recon/recon.db; do [ -f "$d" ] && { printf '%s' "$d"; return 0; }; done
    return 1
}

hex_to_str() { local h=$1; [ -z "$h" ] || [ "$h" = "-" ] && return; printf '%b' "$(sed 's/../\\x&/g' <<< "$h")" | tr -d '\000-\037'; }
fmt_mac() { sed 's/../&:/g; s/:$//' <<< "$1" | tr 'a-f' 'A-F'; }
enc_name() {
    local e=${1:-0}
    if [ "$e" = 0 ]; then echo Open
    elif (( (e & 16) || (e & 64) )) && (( e & 8 )); then echo WPA2/WPA3
    elif (( (e & 16) || (e & 64) )); then echo WPA3
    elif (( e & 8 )); then echo WPA2
    elif (( e & 4 )); then echo WPA
    elif (( e & 2 )); then echo WEP
    else echo "enc:$e"; fi
}
enc_rank() {  # higher = stronger
    case "$(enc_name "$1")" in Open) echo 0 ;; WEP) echo 1 ;; WPA) echo 2 ;; WPA2) echo 3 ;; WPA2/WPA3) echo 4 ;; WPA3) echo 5 ;; *) echo 3 ;; esac
}

# recon_aps SINCE_EPOCH -> lines: bssid<TAB>ssid_hex<TAB>enc<TAB>channel<TAB>signal
# Hidden SSIDs come back as "-" (never an empty field: bash `read` with a tab IFS
# merges empty fields, which would shift every later column).
recon_aps() {
    local db; db=$(recon_db) || return 1
    timeout 8 sqlite3 -readonly -separator "$(printf '\t')" -cmd ".timeout 2000" "$db" \
        "SELECT lower(bssid), CASE WHEN ssid IS NULL OR hex(ssid) = '' THEN '-' ELSE hex(ssid) END, IFNULL(encryption,0), IFNULL(channel,0), IFNULL(MAX(signal),0)
           FROM ssid WHERE type=8 AND bssid != '' AND time >= $1 GROUP BY lower(bssid), hex(IFNULL(ssid,''));" 2>/dev/null
}

watch_profile() { cfg_get watch_profile "Site"; }
watch_files() { local p; p=$(tr -c 'A-Za-z0-9_-' '_' <<< "$(watch_profile)" | sed 's/_$//'); W_APPROVED="$WATCH_DIR/$p.approved"; W_KNOWN="$WATCH_DIR/$p.known"; }

watch_requirements() {
    command -v sqlite3 >/dev/null 2>&1 || { ERROR_DIALOG "Needs sqlite3: opkg update && opkg install sqlite3-cli"; return 1; }
    recon_db >/dev/null || { ERROR_DIALOG "No recon database yet. Start Recon first."; return 1; }
    return 0
}

#############################################################################
# Learn
#############################################################################
watch_learn() {
    local name mins start end now btn n_ap n_net lines=() ssids=() counts=() encs=() sel=() items=() i r h tmp
    watch_requirements || return
    name=$(TEXT_PICKER "Site profile name" "$(watch_profile)"); picker_ok $? || return
    [ -z "$name" ] && return
    mins=$(NUMBER_PICKER "Learn for how many minutes?" 5); picker_ok $? || return
    [[ $mins =~ ^[0-9]+$ ]] && [ "$mins" -ge 1 ] || return
    cfg_set watch_profile "$name"; watch_files; mkdir -p "$WATCH_DIR"
    PROMPT "Learning '$name' for $mins min.
Walk the site so the $DEVICE_WORD hears every access point.
Press B to stop early."
    start=$(( $(date +%s) - 120 )); end=$(( $(date +%s) + mins * 60 ))
    while :; do
        now=$(date +%s); [ "$now" -ge "$end" ] && break
        mapfile -t lines < <(recon_aps "$start")
        n_ap=${#lines[@]}; n_net=$(printf '%s\n' "${lines[@]}" | cut -f2 | sort -u | grep -c .)
        LOG white "Learning: $n_ap APs, $n_net networks, $(( (end - now + 59) / 60 )) min left"
        btn=$(WAIT_FOR_INPUT 15)
        [ "$btn" = "B" ] && break
    done
    mapfile -t lines < <(recon_aps "$start")
    if [ ${#lines[@]} -eq 0 ]; then ERROR_DIALOG "No access points recorded. Is Recon running?"; return; fi

    # one entry per network name (hidden networks grouped as one)
    tmp=$(printf '%s\n' "${lines[@]}" | awk -F'\t' '{c[$2]++; e[$2]=$3} END {for (k in c) printf "%s\t%d\t%s\n", k, c[k], e[k]}' | sort -t$'\t' -k2,2nr)
    while IFS=$'\t' read -r h n r; do
        ssids+=("$h"); counts+=("$n"); encs+=("$r"); sel+=(0)
    done <<< "$tmp"

    # approval: toggle which networks are yours
    while :; do
        items=()
        for i in "${!ssids[@]}"; do
            name=$(hex_to_str "${ssids[$i]}"); [ -z "$name" ] && name="(hidden)"
            items+=("$([ "${sel[$i]}" = 1 ] && echo "[x]" || echo "[ ]") $name - ${counts[$i]} AP $(enc_name "${encs[$i]}")")
        done
        r=$(LIST_PICKER "Which networks are YOURS?" "Save" "${items[@]}" "Cancel" "Save"); picker_ok $? || return
        [ "$r" = "Cancel" ] && { LOG yellow "Learn cancelled - nothing saved"; return; }
        [ "$r" = "Save" ] && break
        for i in "${!items[@]}"; do [ "${items[$i]}" = "$r" ] && sel[$i]=$((1 - sel[$i])); done
    done

    : > "$W_APPROVED.tmp"
    for i in "${!ssids[@]}"; do
        [ "${sel[$i]}" = 1 ] || continue
        [ "${ssids[$i]}" = "-" ] && continue       # hidden SSIDs can't be protected by name
        printf '%s\n' "${lines[@]}" | awk -F'\t' -v s="${ssids[$i]}" '$2==s {printf "%s\t%s\t%s\n", $2, $1, $3}' >> "$W_APPROVED.tmp"
    done
    printf '%s\n' "${lines[@]}" | cut -f1 | sort -u > "$W_KNOWN"
    sort -u "$W_APPROVED.tmp" > "$W_APPROVED"; rm -f "$W_APPROVED.tmp"
    LOG green "Saved '$(watch_profile)': $(cut -f1 "$W_APPROVED" | sort -u | grep -c .) protected networks, $(grep -c . "$W_APPROVED") approved APs, $(grep -c . "$W_KNOWN") known APs"
    [ -s "$W_APPROVED" ] || LOG yellow "No networks approved - evil-twin checks need at least one"
}

# Web console learning: the networks recon heard in the last MINUTES
#   $RUN/watch_scan.raw   the access points (as recon_aps)
#   $RUN/watch_scan.tsv   one line per network: ssid_hex<TAB>APs<TAB>security
watch_scan() {
    local mins=${1:-15} raw="$RUN/watch_scan.raw"
    command -v sqlite3 >/dev/null 2>&1 || { echo "err|Needs sqlite3 (opkg install sqlite3-cli)"; return 1; }
    recon_db >/dev/null || { echo "err|No recon database yet - start Recon first"; return 1; }
    recon_aps $(( $(date +%s) - mins * 60 )) > "$raw"
    if [ ! -s "$raw" ]; then rm -f "$RUN/watch_scan.tsv"; echo "err|No access points heard in the last $mins min - is Recon running?"; return 1; fi
    awk -F'\t' '{c[$2]++; e[$2]=$3} END {for (k in c) printf "%s\t%d\t%s\n", k, c[k], e[k]}' "$raw" | sort -t"$(printf '\t')" -k2,2nr |
        while IFS=$'\t' read -r h n e; do printf '%s\t%s\t%s\n' "$h" "$n" "$(enc_name "$e")"; done > "$RUN/watch_scan.tsv"
    echo "ok|$(grep -c . "$RUN/watch_scan.tsv") networks, $(grep -c . "$raw") access points heard"
}

# watch_save PROFILE HEX,HEX... - your networks from the last watch_scan
watch_save() {
    local name=$1 raw="$RUN/watch_scan.raw" h n=0
    [ -s "$raw" ] || { echo "err|Find the networks first"; return 1; }
    [ -n "$name" ] || name=Site
    cfg_set watch_profile "$name"; watch_files; mkdir -p "$WATCH_DIR"
    : > "$W_APPROVED.tmp"
    for h in ${2//,/ }; do
        [[ $h =~ ^[0-9A-Fa-f]{2,64}$ ]] || continue      # hidden SSIDs can't be protected by name
        awk -F'\t' -v s="$h" '$2==s {printf "%s\t%s\t%s\n", $2, $1, $3}' "$raw" >> "$W_APPROVED.tmp"
        n=$((n + 1))
    done
    cut -f1 "$raw" | sort -u > "$W_KNOWN"
    sort -u "$W_APPROVED.tmp" > "$W_APPROVED"; rm -f "$W_APPROVED.tmp"
    LOG green "Saved '$name': $n protected networks, $(grep -c . "$W_APPROVED") approved APs, $(grep -c . "$W_KNOWN") known APs"
    if [ "$n" -eq 0 ]; then echo "ok|Saved '$name' with no networks of yours - evil-twin checks need at least one"
    else echo "ok|Saved '$name': $n networks, $(grep -c . "$W_APPROVED") access points"; fi
}

#############################################################################
# Watch loop (background)
#############################################################################
watch_alert() {  # watch_alert KIND SEVERITY ssid bssid enc channel signal ssid_hex
    local kind=$1 sev=$2 ssid=$3 bssid=$4 enc=$5 ch=$6 sig=$7 h=$8 mac uid type cs rem chat
    mac=$(fmt_mac "$bssid")
    best_position || { P_LAT=0; P_LON=0; }
    case "$sev" in high) type="a-h-G" ;; *) type="a-s-G" ;; esac
    cs="$kind ${ssid:-hidden}"; cs=${cs:0:28}
    uid="$PRODUCT_NAME-watch-$bssid"
    rem="$kind detected by $C_CALLSIGN at $(date '+%F %T')
SSID: ${ssid:-(hidden)}
BSSID: $mac
Security: $(enc_name "$enc")  Channel: $ch  Signal: ${sig} dBm
Site profile: $(watch_profile)
Marker = where $C_CALLSIGN heard it (AP is within Wi-Fi range)."
    chat="ALERT $kind near $C_CALLSIGN: '${ssid:-hidden}' $mac $(enc_name "$enc") ch$ch ${sig}dBm"
    if [ "$P_LAT" != 0 ]; then
        queue_cot "$(report_marker_xml "$uid" "$type" "$cs" "$P_LAT" "$P_LON" "$rem" "<color argb=\"-65536\"/>" 3600)"
        track_seen "$uid" "$P_LAT" "$P_LON" "$cs" "$type" "" "marker"
    fi
    queue_cot "$(cot_chat "$chat")"
    printf '%s\t%s\t%s\t%s\t%s\n' "$(date +%s)" "$kind" "$h" "$bssid" "$enc" >> "$RUN/watch_alerts"
    mkdir -p "$LOOT_DIR"; echo "$(date '+%F %T') $kind ssid='$ssid' bssid=$mac enc=$(enc_name "$enc") ch=$ch sig=$sig pos=$P_LAT,$P_LON" >> "$WATCH_LOG"
    LOG red "$kind: '${ssid:-hidden}' $mac"
    chat_log "OUT [All] $C_CALLSIGN: $chat"
    RINGTONE alert >/dev/null 2>&1 &
    [ "$sev" = high ] && ALERT "$kind
'${ssid:-hidden}'
$mac" >/dev/null 2>&1 &
}

watch_check_once() {
    local now line bssid h enc ch sig ssid last kind sev app_enc
    local -A appr_ssid=() appr_bssid=() appr_enc=() known=()
    watch_files
    [ -f "$W_APPROVED" ] || return 1
    while IFS=$'\t' read -r h bssid enc; do
        [ -z "$bssid" ] && continue
        appr_ssid[$h]=1; appr_bssid[$bssid]=1
        [ -z "${appr_enc[$h]}" ] || [ "$(enc_rank "$enc")" -lt "$(enc_rank "${appr_enc[$h]}")" ] && appr_enc[$h]=$enc
    done < "$W_APPROVED"
    [ -f "$W_KNOWN" ] && while read -r bssid; do [ -n "$bssid" ] && known[$bssid]=1; done < "$W_KNOWN"
    now=$(date +%s); mkdir -p "$RUN/watch_seen"
    while IFS=$'\t' read -r bssid h enc ch sig; do
        [ -z "$bssid" ] && continue
        kind=""; sev=""
        if [ "$h" != "-" ] && [ -n "${appr_ssid[$h]}" ]; then
            if [ -z "${appr_bssid[$bssid]}" ]; then kind="EVIL TWIN"; sev=high
            elif [ "$(enc_rank "$enc")" -lt "$(enc_rank "${appr_enc[$h]}")" ]; then kind="DOWNGRADE"; sev=high; fi
        elif [ -z "${known[$bssid]}" ] && [ -z "${appr_bssid[$bssid]}" ]; then
            if [ "$enc" = 0 ] && [ "$(cfg_get watch_new_open 1)" = 1 ]; then kind="NEW OPEN AP"; sev=med
            elif [ "$(cfg_get watch_any_new 0)" = 1 ]; then kind="NEW AP"; sev=low; fi
        fi
        [ -z "$kind" ] && continue
        last=$(cat "$RUN/watch_seen/$bssid" 2>/dev/null || echo 0)
        [ $((now - last)) -lt "$WATCH_DEDUPE" ] && continue
        echo "$now" > "$RUN/watch_seen/$bssid"
        ssid=$(hex_to_str "$h")
        watch_alert "$kind" "$sev" "$ssid" "$bssid" "$enc" "$ch" "$sig" "$h"
    done < <(recon_aps $((now - WATCH_WINDOW)))
    return 0
}

watch_loop() {
    trap 'exit 0' TERM INT
    LOG green "Evil-twin watch ON ($(watch_profile))"
    while [ ! -f "$RUN/stop" ] && [ "$(cfg_get watch 0)" = 1 ]; do
        watch_check_once || { LOG yellow "Watch: no site profile - use Learn site Wi-Fi"; break; }
        sleep "$WATCH_INTERVAL"
    done
}

watch_start() {
    watch_stop
    command -v sqlite3 >/dev/null 2>&1 && recon_db >/dev/null || return 1
    watch_loop &
    WATCH_PID=$!; echo "$WATCH_PID" > "$RUN/watch.pid"
}
watch_stop() {
    local p; p=$(cat "$RUN/watch.pid" 2>/dev/null)
    [ -n "$p" ] && kill "$p" 2>/dev/null
    rm -f "$RUN/watch.pid"; WATCH_PID=""
}
watch_running() { kill -0 "$(cat "$RUN/watch.pid" 2>/dev/null)" 2>/dev/null; }

#############################################################################
# Menu helpers
#############################################################################
watch_toggle() {
    if [ "$(cfg_get watch 0)" = 1 ]; then
        cfg_set watch 0; watch_stop; LOG yellow "Evil-twin watch OFF"
    else
        watch_requirements || return
        watch_files
        [ -s "$W_APPROVED" ] || { ERROR_DIALOG "No approved networks for '$(watch_profile)'. Run Learn site Wi-Fi first."; return; }
        cfg_set watch 1; watch_start
    fi
}

watch_review() {
    local nets
    watch_files
    [ -s "$W_APPROVED" ] || { LOG yellow "No approved networks for '$(watch_profile)'"; return; }
    LOG white "---- $(watch_profile): protected networks ----"
    cut -f1 "$W_APPROVED" | sort | uniq -c | while read -r n h; do LOG white "$(hex_to_str "$h") - $n AP"; done
    LOG white "Known APs at site: $(grep -c . "$W_KNOWN" 2>/dev/null || echo 0)"
}

# Approve an AP from a recent alert (e.g. a new legit AP was installed)
watch_approve_recent() {
    local rows=() items=() i r ts kind h bssid enc
    watch_files
    [ -s "$RUN/watch_alerts" ] || { LOG "No watch alerts this session"; return; }
    mapfile -t rows < <(tail -n 10 "$RUN/watch_alerts" | sed -n '1!G;h;$p')
    for i in "${!rows[@]}"; do
        IFS=$'\t' read -r ts kind h bssid enc <<< "${rows[$i]}"
        items+=("$((i + 1)). $kind '$(hex_to_str "$h")' $(fmt_mac "$bssid")")
    done
    r=$(LIST_PICKER "Approve which AP?" "${items[@]}" "< Back" "< Back"); picker_ok $? || return
    [ "$r" = "< Back" ] && return
    IFS=$'\t' read -r ts kind h bssid enc <<< "${rows[$(( ${r%%.*} - 1 ))]}"
    if [ "$(CONFIRMATION_DIALOG "Approve $(fmt_mac "$bssid") as one of YOUR access points?")" = "$DUCKYSCRIPT_USER_CONFIRMED" ]; then
        if [ "$h" != "-" ] && grep -q "^$h	" "$W_APPROVED" 2>/dev/null; then
            printf '%s\t%s\t%s\n' "$h" "$bssid" "$enc" >> "$W_APPROVED"
        fi
        echo "$bssid" >> "$W_KNOWN"
        LOG green "Approved $(fmt_mac "$bssid")"
    fi
}

watch_options() {
    local r o a
    while :; do
        o="New open APs: $([ "$(cfg_get watch_new_open 1)" = 1 ] && echo On || echo Off)"
        a="Any new AP: $([ "$(cfg_get watch_any_new 0)" = 1 ] && echo On || echo Off)"
        r=$(LIST_PICKER "Watch alerts" "$o" "$a" "< Back" "$o"); picker_ok $? || return
        case "$r" in
            "New open"*) cfg_set watch_new_open "$([ "$(cfg_get watch_new_open 1)" = 1 ] && echo 0 || echo 1)" ;;
            "Any new"*)  cfg_set watch_any_new "$([ "$(cfg_get watch_any_new 0)" = 1 ] && echo 0 || echo 1)" ;;
            *) return ;;
        esac
    done
}

menu_watch() {
    local r st last
    while :; do
        if [ "$(cfg_get watch 0)" = 1 ] && watch_running; then st="Watch: ON ($(watch_profile))"; else st="Watch: OFF"; fi
        r=$(LIST_PICKER "Evil-twin watch" "$st" "Learn site Wi-Fi" "Review protected networks" "Approve AP from alert" \
            "Alert options" "< Back" "${last:-$st}"); picker_ok $? || return
        last=$r
        case "$r" in
            "Watch:"*)                   watch_toggle ;;
            "Learn site Wi-Fi")          watch_learn ;;
            "Review protected networks") watch_review ;;
            "Approve AP from alert")     watch_approve_recent ;;
            "Alert options")             watch_options ;;
            *) return ;;
        esac
    done
}
