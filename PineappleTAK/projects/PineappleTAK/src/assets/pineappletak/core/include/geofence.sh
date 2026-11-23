#!/bin/bash
# PagerTAK geofences - sourced by payload.sh.
#
# Zones (circle or polygon) are drawn in the web console and saved in
# $PAYLOAD_DIR/geofences.txt:
#   id|name|circle|lat,lon,radius_m|who|chat|sent
#   id|name|poly|lat,lon;lat,lon;...|who|chat|sent
#   sent: "" (only on this Pager) | all | dm:UID:CALLSIGN
#   8th field (optional) alert: who gets a TAK "Geo-fence Breached" alert on enter (same values)
#   who: people (TAK users) | drones | me | all | u:<track> (one contact)     chat: 1 = also GeoChat the alert
#
# geo_loop checks every 10 s (one awk pass) which tracked positions are inside
# which zone and alerts on enter / leave. Optionally the zone is shared to TAK
# as a drawing (circle u-d-c-c / shape u-d-f).

GEO_FILE="$PAYLOAD_DIR/geofences.txt"
GEO_EVERY=10
GEO_HOLDOFF=30     # seconds between alerts for the same zone + track (stops edge flapping)

geo_running() { kill -0 "$(cat "$RUN/geo.pid" 2>/dev/null)" 2>/dev/null; }
geo_start() { geo_running && return 0; geo_loop > /dev/null 2>&1 & echo $! > "$RUN/geo.pid"; }

# prints: fence_id|track_id|inside(0/1)|fence_name|callsign|kind|chat|alert|lat|lon
geo_eval() {
    {
        cat "$GEO_FILE"
        echo "@@"
        if best_position; then printf 'self|%s|%s|%s|a-f-G-U-C|self\n' "$P_LAT" "$P_LON" "$C_CALLSIGN"; fi
        local f l now; now=$(date +%s)
        for f in "$RUN"/tracks.d/*; do
            [ -f "$f" ] || continue
            IFS= read -r l < "$f" || continue
            printf '%s|%s\n' "$(basename "$f")" "$l"
        done | awk -F'|' -v now="$now" -v max="${TRACK_MAX_AGE:-1800}" 'now - $7 <= max {print $1"|"$2"|"$3"|"$4"|"$5"|"$8}'
    } | awk -F'|' '
        function rad(d) { return d * 3.14159265358979 / 180 }
        function dist(a1, o1, a2, o2,   x, y) {   # equirectangular, fine for geofence sizes
            x = rad(o2 - o1) * cos(rad((a1 + a2) / 2)); y = rad(a2 - a1); return sqrt(x * x + y * y) * 6371008.8
        }
        function inpoly(lat, lon, pts,   n, i, j, a, b, c, inside, yi, xi, yj, xj) {
            n = split(pts, a, ";"); inside = 0; j = n
            for (i = 1; i <= n; i++) {
                split(a[i], b, ","); split(a[j], c, ",")
                yi = b[1] + 0; xi = b[2] + 0; yj = c[1] + 0; xj = c[2] + 0
                if (((yi > lat) != (yj > lat)) && (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi)) inside = !inside
                j = i
            }
            return inside
        }
        $0 == "@@" { pos = 1; next }
        !pos { if (NF >= 6) { nf++; id[nf] = $1; nm[nf] = $2; sh[nf] = $3; dt[nf] = $4; who[nf] = $5; ch[nf] = $6; ga[nf] = $8 }; next }
        {
            tid = $1; lat = $2 + 0; lon = $3 + 0; cs = $4; type = $5; kind = $6
            if (kind == "marker") next
            drone = (type ~ /^a-.-A/); person = (kind == "client")
            for (k = 1; k <= nf; k++) {
                if (who[k] == "people" && !person) continue
                if (who[k] == "drones" && !drone) continue
                if (who[k] == "me" && tid != "self") continue
                if (who[k] ~ /^u:/ && tid != substr(who[k], 3)) continue
                if (sh[k] == "circle") { split(dt[k], c, ","); ins = (dist(lat, lon, c[1] + 0, c[2] + 0) <= c[3] + 0) }
                else ins = inpoly(lat, lon, dt[k])
                print id[k] "|" tid "|" ins "|" nm[k] "|" cs "|" (drone ? "drone" : kind) "|" ch[k] "|" ga[k] "|" lat "|" lon
            }
        }'
}

geo_loop() {
    local -A was last
    local fid tid ins name cs kind chat key now ev line
    if [ -f "$RUN/geo_state" ]; then
        while IFS='|' read -r key ins; do was[$key]=$ins; done < "$RUN/geo_state"
    fi
    while [ ! -f "$RUN/stop" ]; do
        if [ -s "$GEO_FILE" ]; then
            now=$(date +%s)
            while IFS='|' read -r fid tid ins name cs kind chat galert plat plon; do
                key="$fid|$tid"
                if [ -z "${was[$key]}" ]; then
                    was[$key]=$ins                      # first look: baseline, no alert
                elif [ "${was[$key]}" != "$ins" ] && [ $((now - ${last[$key]:-0})) -ge $GEO_HOLDOFF ]; then
                    was[$key]=$ins; last[$key]=$now
                    if [ "$ins" = 1 ]; then ev=ENTER; line="GEOFENCE: $cs entered $name"; else ev=LEAVE; line="GEOFENCE: $cs left $name"; fi
                    echo "$now|$ev|$name|$cs|$kind" >> "$RUN/geo_alerts"
                    if [ "$ins" = 1 ]; then LOG red "$line"; RINGTONE alert >/dev/null 2>&1 & else LOG yellow "$line"; fi
                    [ "$chat" = 1 ] && send_chat "$line" > /dev/null
                    [ "$ins" = 1 ] && [ -n "$galert" ] && queue_cot "$(cot_to "$(geo_alert_cot "$fid" "$name" "$cs" "$plat" "$plon")" "$galert")"
                fi
            done < <(geo_eval)
            for key in "${!was[@]}"; do printf '%s|%s\n' "$key" "${was[$key]}"; done > "$RUN/geo_state"
        fi
        sleep "$GEO_EVERY"
    done
}

geo_valid_pts() {  # "lat,lon;lat,lon;..." with 3-40 points
    local IFS=';' p n=0
    for p in $1; do
        valid_coord "${p%%,*}" && valid_coord "${p#*,}" || return 1
        n=$((n + 1))
    done
    [ "$n" -ge 3 ] && [ "$n" -le 40 ]
}

# geo_add name circle|poly data who chat target [alert_target]  -> prints result line   (targets: "" | all | dm:UID:CS)
geo_add() {
    local name=${1//|//} shape=$2 data=$3 who=$4 chat=$5 share=$6 galert=$7 id lat lon r
    [ -n "$name" ] || { echo "err|Name the zone"; return; }
    case "$who" in people|drones|me|all) ;; u:*) [[ $who =~ ^u:[A-Za-z0-9._-]{1,120}$ ]] || who=all ;; *) who=all ;; esac
    [ "$chat" = 1 ] || chat=0
    case "$share" in 1) share=all ;; all|dm:*) ;; *) share="" ;; esac
    if [ "$shape" = circle ]; then
        IFS=, read -r lat lon r <<< "$data"
        valid_coord "$lat" && valid_coord "$lon" && [[ $r =~ ^[0-9]+(\.[0-9]+)?$ ]] || { echo "err|Bad circle"; return; }
        r=${r%.*}; [ "$r" -ge 10 ] && [ "$r" -le 50000 ] || { echo "err|Radius must be 10 m to 50 km"; return; }
        data="$lat,$lon,$r"
    elif [ "$shape" = poly ]; then
        geo_valid_pts "$data" || { echo "err|A zone needs 3-40 points"; return; }
    else
        echo "err|Unknown shape"; return
    fi
    id=$(head -c 6 /proc/sys/kernel/random/uuid)
    case "$galert" in all|dm:*) ;; *) galert="" ;; esac
    echo "$id|$name|$shape|$data|$who|$chat|$share|$galert" >> "$GEO_FILE"
    [ -n "$share" ] && queue_cot "$(cot_to "$(geo_cot "$id" "$name" "$shape" "$data")" "$share")"
    geo_start
    LOG green "Geofence '$name' added"
    echo "ok|Geofence '$name' added$([ -n "$share" ] && echo " and sent to $(target_label "$share")")"
}

geo_del() {
    local id=$1 line
    [[ $id =~ ^[0-9a-f]{6}$ ]] || { echo "err|Bad id"; return; }
    line=$(grep "^$id|" "$GEO_FILE" 2>/dev/null) || { echo "err|No such zone"; return; }
    grep -v "^$id|" "$GEO_FILE" > "$GEO_FILE.tmp"; mv "$GEO_FILE.tmp" "$GEO_FILE"
    local sent; sent=$(cut -d'|' -f7 <<< "$line"); [ "$sent" = 1 ] && sent=all; [ "$sent" = 0 ] && sent=""
    [ -n "$sent" ] && queue_cot "$(cot_to "$(geo_delete_cot "$id")" "$sent")"
    sed -i "/^$id|/d" "$RUN/geo_state" 2>/dev/null
    echo "ok|Geofence '$(cut -d'|' -f2 <<< "$line")' deleted$([ -n "$sent" ] && echo " here and in TAK")"
}

# TAK drawing for a zone (red outline, light red fill)
geo_cot() {
    local id=$1 name shape=$3 data=$4 now uid lat lon r p detail style
    name=$(xml_esc "$2"); now=$(date +%s); uid="$PRODUCT_NAME-GF-$id"
    style="<strokeColor value=\"-65536\"/><strokeWeight value=\"3.0\"/><fillColor value=\"1090453504\"/><contact callsign=\"$name\"/><remarks>Geofence from $(xml_esc "$C_CALLSIGN")</remarks><labels_on value=\"true\"/><archive/>"
    if [ "$shape" = circle ]; then
        IFS=, read -r lat lon r <<< "$data"
        detail="<shape><ellipse major=\"$r\" minor=\"$r\" angle=\"360\"/><link uid=\"$uid.Style\" type=\"b-x-KmlStyle\" relation=\"p-c\"><Style><LineStyle><color>ff0000ff</color><width>3.0</width></LineStyle><PolyStyle><color>400000ff</color></PolyStyle></Style></link></shape>$style"
        printf '%s' "<event version=\"2.0\" uid=\"$uid\" type=\"u-d-c-c\" how=\"h-e\" time=\"$(iso_time "$now")\" start=\"$(iso_time "$now")\" stale=\"$(iso_time $((now + 604800)))\"><point lat=\"$lat\" lon=\"$lon\" hae=\"9999999.0\" ce=\"9999999.0\" le=\"9999999.0\"/><detail>$detail</detail></event>"
    else
        detail=""
        local IFS=';' first=""
        for p in $data; do detail+="<link point=\"$p\"/>"; [ -z "$first" ] && first=$p; done
        detail+="<link point=\"$first\"/>"
        lat=${first%%,*}; lon=${first#*,}
        printf '%s' "<event version=\"2.0\" uid=\"$uid\" type=\"u-d-f\" how=\"h-e\" time=\"$(iso_time "$now")\" start=\"$(iso_time "$now")\" stale=\"$(iso_time $((now + 604800)))\"><point lat=\"$lat\" lon=\"$lon\" hae=\"9999999.0\" ce=\"9999999.0\" le=\"9999999.0\"/><detail>$detail$style</detail></event>"
    fi
}

# TAK "Geo-fence Breached" alert at the position of whoever entered
geo_alert_cot() {
    local id=$1 zone cs now
    zone=$(xml_esc "$2"); cs=$(xml_esc "$3"); now=$(date +%s)
    printf '%s' "<event version=\"2.0\" uid=\"$PRODUCT_NAME-GF-$id-alert\" type=\"b-a-g\" how=\"h-e\" time=\"$(iso_time "$now")\" start=\"$(iso_time "$now")\" stale=\"$(iso_time $((now + 600)))\"><point lat=\"$4\" lon=\"$5\" hae=\"0\" ce=\"9999999.0\" le=\"9999999.0\"/><detail><link uid=\"$C_UID\" type=\"a-f-G-U-C\" relation=\"p-p\"/><contact callsign=\"$zone-Alert\"/><emergency type=\"Geo-fence Breached\">$cs in $zone</emergency><remarks>$cs entered $zone (PagerTAK geofence, $(xml_esc "$C_CALLSIGN"))</remarks></detail></event>"
}

geo_delete_cot() {
    local now; now=$(date +%s)
    printf '%s' "<event version=\"2.0\" uid=\"$PRODUCT_NAME-del-$1-$now\" type=\"t-x-d-d\" how=\"h-e\" time=\"$(iso_time "$now")\" start=\"$(iso_time "$now")\" stale=\"$(iso_time $((now + 120)))\"><point lat=\"0\" lon=\"0\" hae=\"0\" ce=\"9999999.0\" le=\"9999999.0\"/><detail><link uid=\"PagerTAK-GF-$1\" relation=\"none\" type=\"none\"/><__forcedelete/></detail></event>"
}

# ---------------------------------------------------------------- on the Pager
# geo_quick [track_file callsign] - a circle zone around your position, for one contact or all TAK users
# shellcheck disable=SC2120  # payload.sh (Contacts) calls it with a contact; the Geofences menu without
geo_quick() {
    local tf=$1 cs=$2 m r who name
    best_position || { PROMPT "Need a GPS fix or a manual position for the zone centre."; return; }
    m=$(NUMBER_PICKER "Zone radius (m)" 200); picker_ok $? || return
    [[ $m =~ ^[0-9]+$ ]] && [ "$m" -ge 10 ] && [ "$m" -le 50000 ] || { LOG yellow "Radius must be 10 m to 50 km"; return; }
    if [ -n "$tf" ]; then who="u:$tf"; name="${cs:0:20} ${m}m"
    else who=people; name="Zone ${m}m"
    fi
    r=$(CONFIRMATION_DIALOG "Alert when ${cs:-a TAK user} enters or leaves ${m} m around your position?")
    [ "$r" = "$DUCKYSCRIPT_USER_CONFIRMED" ] || return
    r=$(geo_add "$name" circle "$P_LAT,$P_LON,$m" "$who" 0 "" "")
    if [ "${r%%|*}" = ok ]; then LOG green "${r#*|}"; else LOG red "${r#*|}"; fi
}

menu_geofence() {
    local r rows=() names=() i id
    while :; do
        r=$(LIST_PICKER "Geofences" "New zone here (TAK users)" "Delete a zone" "< Back" "New zone here (TAK users)"); picker_ok $? || return
        case "$r" in
            "New zone here"*) geo_quick ;;
            "Delete a zone")
                [ -s "$GEO_FILE" ] || { LOG "No zones yet (draw them in the web console or add one here)"; continue; }
                mapfile -t rows < "$GEO_FILE"; names=()
                for i in "${!rows[@]}"; do names+=("$((i + 1)). $(cut -d'|' -f2 <<< "${rows[$i]}")"); done
                r=$(LIST_PICKER "Delete zone" "${names[@]}" "< Back" "< Back"); picker_ok $? || continue
                [ "$r" = "< Back" ] && continue
                i=${r%%.*}; id=$(cut -d'|' -f1 <<< "${rows[$((i - 1))]}")
                [ "$(CONFIRMATION_DIALOG "Delete zone ${r#*. }?")" = "$DUCKYSCRIPT_USER_CONFIRMED" ] || continue
                r=$(geo_del "$id"); LOG "${r#*|}" ;;
            *) return ;;
        esac
    done
}
