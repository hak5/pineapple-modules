#!/bin/bash
# PagerTAK reports module - sourced by payload.sh (not run on its own).
# SALUTE, SITREP, MEDEVAC 9-line and Damage assessment reports sent to TAK as
# CoT markers plus a GeoChat summary to All Chat Rooms.
#
# MEDEVAC uses ATAK's own <_medevac_> detail (CoT type b-r-f-h-c) so ATAK opens
# it in its 9-line MEDEVAC tool. Field names/encodings follow ATAK-CIV's
# MedicalDetailHandler / MedLineView: counts as numbers, line 6 security and
# line 7 marking as list positions (security 0=N 1=P 2=E 3=X;
# marking 0=Panels 1=Pyro 2=Smoke 3=None 4=Other).

GEO_AWK="$PAYLOAD_DIR/include/geo.awk"
REPORT_LOG="$LOOT_DIR/reports.log"

geo() { awk "$(cat "$GEO_AWK") BEGIN { print $1 }"; }
to_mgrs() { geo "mgrs($1, $2)"; }
dtg() { date -u '+%d%H%MZ %b %y' | tr 'a-z' 'A-Z'; }   # military date-time group, e.g. 201530Z NOV 26

# pick_or_type "title" opt1 opt2 ... -> prints choice; "Other (type)" asks for text
pick_or_type() {
    local title=$1 r; shift
    r=$(LIST_PICKER "$title" "$@" "Other (type)" "$1"); picker_ok $? || return 1
    if [ "$r" = "Other (type)" ]; then r=$(TEXT_PICKER "$title" ""); picker_ok $? || return 1; fi
    printf '%s' "$r"
}

# report_location "title" -> sets R_LAT R_LON R_MGRS R_LOCDESC
report_location() {
    local r brg m ll dirs=(N NE E SE S SW W NW) degs=(0 45 90 135 180 225 270 315) i
    best_position || { ERROR_DIALOG "No position. Need a GPS fix or a manual position."; return 1; }
    r=$(LIST_PICKER "${1:-Location}" "At my position" "Offset from me" "Enter lat,lon" "At my position"); picker_ok $? || return 1
    case "$r" in
        "Offset from me")
            brg=$(LIST_PICKER "Direction from me" "${dirs[@]}" "N"); picker_ok $? || return 1
            m=$(NUMBER_PICKER "Distance (meters)" 100); picker_ok $? || return 1
            [[ $m =~ ^[0-9]+$ ]] || return 1
            for i in "${!dirs[@]}"; do [ "${dirs[$i]}" = "$brg" ] && brg=${degs[$i]}; done
            read -r R_LAT R_LON <<< "$(geo "offset($P_LAT, $P_LON, $brg, $m)")"
            R_LOCDESC="${m}m ${dirs[$((brg / 45))]} of $C_CALLSIGN" ;;
        "Enter lat,lon")
            ll=$(TEXT_PICKER "lat,lon" "$P_LAT,$P_LON"); picker_ok $? || return 1
            R_LAT=${ll%%,*}; R_LON=${ll##*,}; R_LAT=${R_LAT// /}; R_LON=${R_LON// /}
            valid_coord "$R_LAT" && valid_coord "$R_LON" || { LOG red "Bad lat,lon"; return 1; }
            R_LOCDESC="entered position" ;;
        *)  R_LAT=$P_LAT; R_LON=$P_LON; R_LOCDESC="at $C_CALLSIGN" ;;
    esac
    R_MGRS=$(to_mgrs "$R_LAT" "$R_LON")
    return 0
}

# count_menu "title" "Label1" "Label2" ... -> fills COUNTS[] (one per label) via a Done-style loop
count_menu() {
    local title=$1 labels=() items=() i r n; shift
    labels=("$@"); COUNTS=()
    for i in "${!labels[@]}"; do COUNTS[$i]=0; done
    while :; do
        items=()
        for i in "${!labels[@]}"; do items+=("${labels[$i]}: ${COUNTS[$i]}"); done
        r=$(LIST_PICKER "$title" "${items[@]}" "Done" "Done"); picker_ok $? || return 1
        [ "$r" = "Done" ] && return 0
        for i in "${!labels[@]}"; do
            if [ "${r%%:*}" = "${labels[$i]}" ]; then
                n=$(NUMBER_PICKER "${labels[$i]}" "${COUNTS[$i]}"); picker_ok $? || continue
                [[ $n =~ ^[0-9]+$ ]] && COUNTS[$i]=$n
            fi
        done
    done
}

# toggle_menu "title" opt1 opt2 ... -> prints comma list of selected options
toggle_menu() {
    local title=$1 opts=() sel=() items=() i r out=""; shift
    opts=("$@"); for i in "${!opts[@]}"; do sel[$i]=0; done
    while :; do
        items=()
        for i in "${!opts[@]}"; do items+=("$([ "${sel[$i]}" = 1 ] && echo "[x]" || echo "[ ]") ${opts[$i]}"); done
        r=$(LIST_PICKER "$title" "${items[@]}" "Done" "Done"); picker_ok $? || return 1
        [ "$r" = "Done" ] && break
        for i in "${!opts[@]}"; do [ "${r:4}" = "${opts[$i]}" ] && sel[$i]=$((1 - sel[$i])); done
    done
    for i in "${!opts[@]}"; do [ "${sel[$i]}" = 1 ] && out+="${out:+, }${opts[$i]}"; done
    printf '%s' "${out:-None}"
}

# Build a marker event. send_report_marker uid type callsign lat lon remarks [extra-detail-xml] [stale-sec]
report_marker_xml() {
    local uid=$1 type=$2 cs lat=$4 lon=$5 rem extra=$7 stale=${8:-7200} now
    cs=$(xml_esc "$3"); rem=$(xml_esc "$6"); now=$(date +%s)
    printf '%s' "<event version=\"2.0\" uid=\"$uid\" type=\"$type\" how=\"h-g-i-g-o\" time=\"$(iso_time "$now")\" start=\"$(iso_time "$now")\" stale=\"$(iso_time $((now + stale)))\"><point lat=\"$lat\" lon=\"$lon\" hae=\"0\" ce=\"9999999.0\" le=\"9999999.0\"/><detail><contact callsign=\"$cs\"/><link uid=\"$C_UID\" type=\"a-f-G-U-C\" parent_callsign=\"$(xml_esc "$C_CALLSIGN")\" relation=\"p-p\"/>$extra<remarks>$rem</remarks><archive/></detail></event>"
}

# finish_report kind uid type callsign lat lon remarks chatline [extra] [stale]
finish_report() {
    local kind=$1 uid=$2 type=$3 cs=$4 lat=$5 lon=$6 rem=$7 chat=$8 extra=$9 stale=${10:-7200} r
    if [ "${REPORT_NOCONFIRM:-0}" != 1 ]; then
        r=$(CONFIRMATION_DIALOG "Send $kind?
$chat")
        [ "$r" = "$DUCKYSCRIPT_USER_CONFIRMED" ] || { LOG yellow "$kind not sent"; return 1; }
    fi
    queue_cot "$(report_marker_xml "$uid" "$type" "$cs" "$lat" "$lon" "$rem" "$extra" "$stale")"
    send_chat "$chat"
    track_seen "$uid" "$lat" "$lon" "$cs" "$type" "" "marker"
    mkdir -p "$LOOT_DIR"
    { echo "== $(date '+%F %T') $kind $uid"; echo "$rem"; } >> "$REPORT_LOG"
    LOG green "$kind sent"
    RINGTONE success >/dev/null 2>&1 &
}

# Each report is split in two: report_X asks on the Pager screen, then calls
# report_X_send with plain values. The web console calls report_X_send directly
# (REPORT_NOCONFIRM=1 skips the Pager's confirm dialog; the browser confirms).

#############################################################################
# SALUTE
#############################################################################
report_salute() {
    local n what act unit when equip aff notes t
    report_location "SALUTE - where?" || return
    n=$(NUMBER_PICKER "S - Size (how many)" 1); picker_ok $? || return
    what=$(pick_or_type "S - What" Persons Vehicles Vessels Aircraft Drones) || return
    act=$(pick_or_type "A - Activity" Stationary Moving Observing Loitering Digging/emplacing Looting Fighting Fleeing) || return
    unit=$(pick_or_type "U - Unit/uniform" Unknown "Civilian clothes" Uniformed "Law enforcement" Military "Gang colors") || return
    when=$(LIST_PICKER "T - Time" "Now" "Earlier (type)" "Now"); picker_ok $? || return
    if [ "$when" = "Now" ]; then t=$(dtg); else t=$(TEXT_PICKER "T - Time observed" "$(dtg)"); picker_ok $? || return; fi
    equip=$(pick_or_type "E - Equipment" "None seen" "Small arms" "Long guns" Vehicles Tools Drones Unknown) || return
    aff=$(LIST_PICKER "Mark as" Suspect Hostile Unknown Neutral Suspect); picker_ok $? || return
    notes=$(TEXT_PICKER "Notes (optional)" ""); picker_ok $? || notes=""
    report_salute_send "$n" "$what" "$act" "$unit" "$t" "$equip" "$aff" "$notes"
}

# report_salute_send size what activity unit time equipment affiliation notes  (needs R_LAT R_LON R_MGRS R_LOCDESC)
report_salute_send() {
    local n=$1 what=$2 act=$3 unit=$4 t=${5:-$(dtg)} equip=$6 aff=$7 notes=$8 type rem chat
    case "$aff" in Hostile) type="a-h-G" ;; Unknown) type="a-u-G" ;; Neutral) type="a-n-G" ;; *) type="a-s-G" ;; esac
    rem="SALUTE from $C_CALLSIGN
S: $n $what
A: $act
L: $R_MGRS ($R_LOCDESC)
U: $unit
T: $t
E: $equip${notes:+
Notes: $notes}"
    chat="SALUTE: $n $what, $act, $R_MGRS, $unit, $t, $equip${notes:+ - $notes}"
    finish_report "SALUTE" "$PRODUCT_NAME-SALUTE-$(head -c 8 /proc/sys/kernel/random/uuid)" "$type" \
        "SALUTE $n $what" "$R_LAT" "$R_LON" "$rem" "$chat"
}

#############################################################################
# SITREP
#############################################################################
report_sitrep() {
    local status sit pax needs
    status=$(LIST_PICKER "SITREP - Status" "All OK" "Minor issues" "Need support" "Under threat" "All OK"); picker_ok $? || return
    sit=$(pick_or_type "Situation" "Arrived on site" "Assessment underway" "Assessment complete" "Departing" "Road blocked" "Comms degraded" "Holding position") || return
    pax=$(NUMBER_PICKER "Personnel (PAX)" 1); picker_ok $? || return
    needs=$(toggle_menu "Needs" Water Food Fuel Medical Comms Transport Security Shelter) || return
    best_position || { ERROR_DIALOG "No position. Need a GPS fix or a manual position."; return; }
    report_sitrep_send "$status" "$sit" "$pax" "$needs"
}

# report_sitrep_send status situation pax needs   (at the device's own position)
report_sitrep_send() {
    local status=$1 sit=$2 pax=$3 needs=${4:-None} rem chat color
    best_position || return 1
    R_MGRS=$(to_mgrs "$P_LAT" "$P_LON")
    case "$status" in "All OK") color=-16711936 ;; "Minor issues") color=-256 ;; "Need support") color=-23296 ;; *) color=-65536 ;; esac
    rem="SITREP from $C_CALLSIGN at $(dtg)
Status: $status
Situation: $sit
Location: $R_MGRS
PAX: $pax
Needs: $needs"
    chat="SITREP: $status. $sit. PAX $pax. Needs: $needs. Loc $R_MGRS"
    finish_report "SITREP" "$PRODUCT_NAME-SITREP-$C_UID" "b-m-p-s-m" "SITREP $C_CALLSIGN" "$P_LAT" "$P_LON" "$rem" "$chat" \
        "<color argb=\"$color\"/><usericon iconsetpath=\"COT_MAPPING_SPOTMAP/b-m-p-s-m/$color\"/>" 3600
}

#############################################################################
# MEDEVAC 9-line (ATAK MedLine compatible)
#############################################################################
MEDEVAC_SECS=("N - No enemy" "P - Possible enemy" "E - Enemy, caution" "X - Armed escort req")
MEDEVAC_MARKS=(Panels Pyrotechnic Smoke None Other)

report_medevac() {
    local freq equip sec mark mark_other="" terr i sec_i=0 mark_i=2
    report_location "Line 1 - Pickup site" || return
    freq=$(TEXT_PICKER "Line 2 - Freq / callsign" "$(cfg_get medevac_freq "$C_CALLSIGN")"); picker_ok $? || return
    count_menu "Line 3 - Precedence" Urgent "Urgent surgical" Priority Routine Convenience || return
    local prec=("${COUNTS[@]}")
    equip=$(LIST_PICKER "Line 4 - Special equipment" None Hoist "Extraction equipment" Ventilator Other None); picker_ok $? || return
    count_menu "Line 5 - Patients by type" Litter Ambulatory || return
    local pat=("${COUNTS[@]}")
    sec=$(LIST_PICKER "Line 6 - Security at PZ" "${MEDEVAC_SECS[@]}" "${MEDEVAC_SECS[0]}"); picker_ok $? || return
    for i in "${!MEDEVAC_SECS[@]}"; do [ "${MEDEVAC_SECS[$i]}" = "$sec" ] && sec_i=$i; done
    mark=$(LIST_PICKER "Line 7 - PZ marking" "${MEDEVAC_MARKS[@]}" Smoke); picker_ok $? || return
    for i in "${!MEDEVAC_MARKS[@]}"; do [ "${MEDEVAC_MARKS[$i]}" = "$mark" ] && mark_i=$i; done
    [ "$mark" = "Other" ] && { mark_other=$(TEXT_PICKER "Marking (describe)" ""); picker_ok $? || return; }
    count_menu "Line 8 - Nationality/status" "US military" "US civilian" "Non-US military" "Non-US civilian" EPW Child || return
    local nat=("${COUNTS[@]}")
    terr=$(LIST_PICKER "Line 9 - Terrain / NBC" None Slope Rough Loose Other None); picker_ok $? || return
    report_medevac_send "$freq" "${prec[*]}" "$equip" "${pat[*]}" "$sec_i" "$mark_i" "$mark_other" "${nat[*]}" "$terr"
}

# report_medevac_send freq "urg urgs pri rou con" equip "litter amb" sec_index mark_index mark_other
#                     "usmil usciv nonusmil nonusciv epw child" terrain      (needs R_LAT R_LON R_MGRS R_LOCDESC)
report_medevac_send() {
    local freq=$1 equip=$3 sec_i=${5:-0} mark_i=${6:-2} mark_other=$7 terr=$9 title rem chat xml sec mark
    local urg urgs pri rou con lit amb usm usc num nuc epw chi
    read -r urg urgs pri rou con <<< "$2"
    read -r lit amb <<< "$4"
    read -r usm usc num nuc epw chi <<< "$8"
    urg=${urg:-0}; urgs=${urgs:-0}; pri=${pri:-0}; rou=${rou:-0}; con=${con:-0}; lit=${lit:-0}; amb=${amb:-0}
    usm=${usm:-0}; usc=${usc:-0}; num=${num:-0}; nuc=${nuc:-0}; epw=${epw:-0}; chi=${chi:-0}
    sec=${MEDEVAC_SECS[$sec_i]:-${MEDEVAC_SECS[0]}}; mark=${MEDEVAC_MARKS[$mark_i]:-Smoke}
    cfg_set medevac_freq "$freq"

    title="MED.$C_CALLSIGN.$(date +%H%M)"
    rem="MEDEVAC 9-LINE from $C_CALLSIGN $(dtg)
1. $R_MGRS ($R_LOCDESC)
2. $freq
3. A-$urg B-$urgs C-$pri D-$rou E-$con
4. $equip
5. L-$lit A-$amb
6. ${sec:0:1}
7. ${mark}${mark_other:+: $mark_other}
8. USMIL-$usm USCIV-$usc NONUSMIL-$num NONUSCIV-$nuc EPW-$epw CHILD-$chi
9. $terr"
    chat="MEDEVAC 9-line: PZ $R_MGRS, freq $freq, urgent $((urg + urgs)), priority $pri, routine $((rou + con)), litter $lit, ambulatory $amb, security ${sec:0:1}, marking $mark"

    xml="<_medevac_ title=\"$(xml_esc "$title")\" casevac=\"false\" freq=\"$(xml_esc "$freq")\""
    xml+=" urgent=\"$urg\" urgent_surgical=\"$urgs\" priority=\"$pri\" routine=\"$rou\" convenience=\"$con\""
    case "$equip" in
        None) xml+=" equipment_none=\"true\"" ;;
        Hoist) xml+=" hoist=\"true\"" ;;
        "Extraction equipment") xml+=" extraction_equipment=\"true\"" ;;
        Ventilator) xml+=" ventilator=\"true\"" ;;
        Other) xml+=" equipment_other=\"true\"" ;;
    esac
    xml+=" litter=\"$lit\" ambulatory=\"$amb\" security=\"$sec_i\" hlz_marking=\"$mark_i\""
    [ -n "$mark_other" ] && xml+=" hlz_other=\"$(xml_esc "$mark_other")\""
    xml+=" us_military=\"$usm\" us_civilian=\"$usc\" nonus_military=\"$num\" nonus_civilian=\"$nuc\" epw=\"$epw\" child=\"$chi\""
    case "$terr" in
        None) xml+=" terrain_none=\"true\"" ;;
        Slope) xml+=" terrain_slope=\"true\"" ;;
        Rough) xml+=" terrain_rough=\"true\"" ;;
        Loose) xml+=" terrain_loose=\"true\"" ;;
        Other) xml+=" terrain_other=\"true\"" ;;
    esac
    xml+=" medline_remarks=\"$(xml_esc "Sent from $DEVICE_NAME ($C_CALLSIGN)")\"/>"

    finish_report "MEDEVAC" "$PRODUCT_NAME-MED-$(head -c 8 /proc/sys/kernel/random/uuid)" "b-r-f-h-c" \
        "$title" "$R_LAT" "$R_LON" "$rem" "$chat" "$xml" 86400
}

#############################################################################
# Damage assessment (disaster sites)
#############################################################################
report_damage() {
    local struct dmg hazards inj trapped access notes
    report_location "Damage - where?" || return
    struct=$(pick_or_type "Structure" Residential Commercial "Public building" School Medical Utility Road Bridge) || return
    dmg=$(LIST_PICKER "Damage level" Destroyed Major Minor Affected "No damage" Major); picker_ok $? || return
    hazards=$(toggle_menu "Hazards" "Downed power lines" "Gas leak" Fire Flooding "Structural collapse" Hazmat "Debris on road") || return
    inj=$(NUMBER_PICKER "Injured" 0); picker_ok $? || return
    trapped=$(NUMBER_PICKER "Trapped / missing" 0); picker_ok $? || return
    access=$(LIST_PICKER "Access" Open Limited Blocked Open); picker_ok $? || return
    notes=$(TEXT_PICKER "Notes (optional)" ""); picker_ok $? || notes=""
    report_damage_send "$struct" "$dmg" "$hazards" "$inj" "$trapped" "$access" "$notes"
}

# report_damage_send structure damage hazards injured trapped access notes  (needs R_LAT R_LON R_MGRS R_LOCDESC)
report_damage_send() {
    local struct=$1 dmg=$2 hazards=${3:-None} inj=${4:-0} trapped=${5:-0} access=$6 notes=$7 color rem chat
    case "$dmg" in
        Destroyed) color=-16777216 ;; Major) color=-65536 ;; Minor) color=-23296 ;;
        Affected) color=-256 ;; *) color=-16711936 ;;
    esac
    rem="DAMAGE ASSESSMENT from $C_CALLSIGN $(dtg)
Location: $R_MGRS ($R_LOCDESC)
Structure: $struct
Damage: $dmg
Hazards: $hazards
Injured: $inj  Trapped/missing: $trapped
Access: $access${notes:+
Notes: $notes}"
    chat="DAMAGE: $struct - $dmg at $R_MGRS. Hazards: $hazards. Injured $inj, trapped $trapped. Access $access${notes:+. $notes}"
    finish_report "Damage report" "$PRODUCT_NAME-DA-$(head -c 8 /proc/sys/kernel/random/uuid)" "b-m-p-s-m" \
        "DA $struct $dmg" "$R_LAT" "$R_LON" "$rem" "$chat" \
        "<color argb=\"$color\"/><usericon iconsetpath=\"COT_MAPPING_SPOTMAP/b-m-p-s-m/$color\"/>" 86400
}

report_history() {
    if [ ! -s "$REPORT_LOG" ]; then LOG "No reports yet"; return; fi
    LOG white "---- last reports ----"
    grep '^== ' "$REPORT_LOG" | tail -n 8 | while IFS= read -r line; do LOG white "${line:3}"; done
    LOG white "Full text: $REPORT_LOG"
}
