#!/bin/bash
# PagerTAK man-down watchdog - sourced by payload.sh.
#
#   You:      no movement (25 m) and no button press for N minutes -> warning
#             (ringtone, screen, web banner) -> 60 s later a 911 alert is sent
#             automatically. Any Pager button or "I'm OK" in the web console resets it.
#   Others:   TAK users you pick: no position update, or no movement, for N minutes
#             -> alert here (+ optional GeoChat "check on ..."). Clears when they move.
#
# Settings (PAYLOAD config): md (0/1), md_min (minutes), md_me (0/1),
#   md_who (uid list, comma separated), md_chat (0/1)
# Runtime: $RUN/mandown ("" | warn|deadline | sent), $RUN/md_alerts, $RUN/activity

MD_MOVE_M=25
MD_GRACE=60

md_running() { kill -0 "$(cat "$RUN/md.pid" 2>/dev/null)" 2>/dev/null; }
md_start() { md_running && return 0; md_loop > /dev/null 2>&1 & echo $! > "$RUN/md.pid"; }
md_stop() { kill "$(cat "$RUN/md.pid" 2>/dev/null)" 2>/dev/null; rm -f "$RUN/md.pid" "$RUN/mandown"; }

md_dist() { awk -v a="$1" -v b="$2" -v c="$3" -v d="$4" 'BEGIN { r = 3.14159265358979 / 180; x = (d - b) * r * cos((a + c) / 2 * r); y = (c - a) * r; printf "%d", sqrt(x * x + y * y) * 6371008.8 }'; }
md_mtime() { date -r "$1" +%s 2>/dev/null || echo 0; }

md_loop() {
    local -A al ao am aw acs
    local now mins lim me_lat="" me_lon="" me_moved idle act st dl uid f lat lon cs tcs ts reason start
    start=$(date +%s); me_moved=$start
    while [ ! -f "$RUN/stop" ]; do
        now=$(date +%s)
        mins=$(cfg_get md_min "$MANDOWN_MINUTES"); [[ $mins =~ ^[0-9]+$ ]] && [ "$mins" -ge 1 ] || mins=${MANDOWN_MINUTES:-10}
        lim=$((mins * 60))
        # ---- me
        if [ "$(cfg_get md_me 1)" = 1 ]; then
            if read_gps; then
                if [ -z "$me_lat" ] || [ "$(md_dist "$me_lat" "$me_lon" "$G_LAT" "$G_LON")" -gt $MD_MOVE_M ]; then
                    me_lat=$G_LAT; me_lon=$G_LON; me_moved=$now
                fi
            fi
            act=$(md_mtime "$RUN/activity"); [ "$act" -gt "$me_moved" ] && me_moved=$act
            idle=$((now - me_moved))
            IFS='|' read -r st dl < "$RUN/mandown" 2>/dev/null || st=""
            case "$st" in
                warn)
                    if [ "$me_moved" -gt $((dl - MD_GRACE)) ]; then
                        rm -f "$RUN/mandown"; LOG green "Man-down check cleared"
                    elif [ "$now" -ge "$dl" ]; then
                        echo "sent" > "$RUN/mandown"
                        emergency_send 911 "" "" "Man down: no movement for $mins min (automatic)"
                        echo "$now|MAN-DOWN|$C_CALLSIGN|911 sent automatically" >> "$RUN/md_alerts"
                    else
                        RINGTONE alert >/dev/null 2>&1 &
                        LOG red "MAN-DOWN in $((dl - now))s - press any button"
                    fi ;;
                sent)
                    [ -f "$RUN/emergency" ] || rm -f "$RUN/mandown" ;;
                *)
                    if [ "$idle" -ge "$lim" ]; then
                        echo "warn|$((now + MD_GRACE))" > "$RUN/mandown"
                        echo "$now|MAN-DOWN|$C_CALLSIGN|no movement for $mins min - 911 in ${MD_GRACE}s" >> "$RUN/md_alerts"
                        LOG red "MAN-DOWN CHECK: no movement for $mins min. Press any button or a 911 alert is sent in ${MD_GRACE}s"
                        RINGTONE alert >/dev/null 2>&1 &
                    fi ;;
            esac
        fi
        # ---- others
        for uid in $(cfg_get md_who "" | tr ',' ' '); do
            f="$RUN/tracks.d/$(printf '%s' "$uid" | tr -c 'A-Za-z0-9._-' '_')"
            reason=""; cs=$(grep -m1 "|$uid\$" "$RUN/contacts" 2>/dev/null | cut -d'|' -f1); cs=${cs:-$uid}
            if [ -f "$f" ]; then
                IFS='|' read -r lat lon tcs _ _ ts _ < "$f"
                [ "$cs" = "$uid" ] && [ -n "$tcs" ] && cs=$tcs
                if [ -z "${al[$uid]}" ] || [ "$(md_dist "${al[$uid]}" "${ao[$uid]}" "$lat" "$lon")" -gt $MD_MOVE_M ]; then
                    al[$uid]=$lat; ao[$uid]=$lon; am[$uid]=$now
                fi
                [ -z "${am[$uid]}" ] && am[$uid]=$now
                if [ $((now - ts)) -ge "$lim" ]; then reason="no position update for $mins min"
                elif [ $((now - ${am[$uid]})) -ge "$lim" ]; then reason="no movement for $mins min"; fi
            elif [ $((now - start)) -ge "$lim" ]; then
                reason="not seen for $mins min"
            fi
            if [ -n "$reason" ] && [ -z "${aw[$uid]}" ]; then
                aw[$uid]=1
                echo "$now|CHECK|$cs|$reason" >> "$RUN/md_alerts"
                LOG red "CHECK ON $cs: $reason"
                RINGTONE alert >/dev/null 2>&1 &
                [ "$(cfg_get md_chat 0)" = 1 ] && send_chat "CHECK ON $cs: $reason" > /dev/null
            elif [ -z "$reason" ] && [ -n "${aw[$uid]}" ]; then
                unset "aw[$uid]"; LOG green "$cs is moving again"
                echo "$now|OK|$cs|moving again" >> "$RUN/md_alerts"
            fi
        done
        sleep 15
    done
}

md_apply() { if [ "$(cfg_get md 0)" = 1 ]; then md_start; else md_stop; fi; }

menu_mandown() {
    local r st last who n
    while :; do
        if md_running; then st="Watchdog: ON"; else st="Watchdog: OFF"; fi
        n=$(cfg_get md_who "" | tr ',' '\n' | grep -c .)
        r=$(LIST_PICKER "Man-down" "$st" "Minutes: $(cfg_get md_min "$MANDOWN_MINUTES")" "Watch me: $([ "$(cfg_get md_me 1)" = 1 ] && echo On || echo Off)" \
            "Watch TAK users ($n)" "GeoChat check-ons: $([ "$(cfg_get md_chat 0)" = 1 ] && echo On || echo Off)" "< Back" "${last:-$st}")
        picker_ok $? || return
        last=$r
        case "$r" in
            "Watchdog: ON")  cfg_set md 0; md_stop; LOG yellow "Man-down watchdog OFF" ;;
            "Watchdog: OFF") cfg_set md 1; md_start; LOG green "Man-down watchdog ON - any button resets your timer" ;;
            Minutes*) r=$(NUMBER_PICKER "Minutes without movement" "$(cfg_get md_min "$MANDOWN_MINUTES")"); picker_ok $? || continue
                      [[ $r =~ ^[0-9]+$ ]] && [ "$r" -ge 1 ] && [ "$r" -le 240 ] && cfg_set md_min "$r" ;;
            "Watch me"*) if [ "$(cfg_get md_me 1)" = 1 ]; then cfg_set md_me 0; else cfg_set md_me 1; fi ;;
            "GeoChat"*)  if [ "$(cfg_get md_chat 0)" = 1 ]; then cfg_set md_chat 0; else cfg_set md_chat 1; fi ;;
            "Watch TAK users"*)
                [ -s "$RUN/contacts" ] || { ERROR_DIALOG "No TAK users seen yet."; continue; }
                local cs=() picked
                mapfile -t cs < <(cut -d'|' -f1 "$RUN/contacts")
                picked=$(toggle_menu "Watch who" "${cs[@]}") || continue
                who=""
                if [ "$picked" != None ]; then
                    while read -r r; do
                        [ -n "$r" ] && who+="${who:+,}$(grep -m1 "^$r|" "$RUN/contacts" | cut -d'|' -f2)"
                    done < <(sed 's/, /\n/g' <<< "$picked")
                fi
                cfg_set md_who "$who" ;;
            *) return ;;
        esac
    done
}
