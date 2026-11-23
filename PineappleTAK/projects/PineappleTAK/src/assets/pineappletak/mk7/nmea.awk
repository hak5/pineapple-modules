# PineappleTAK (Mark VII) - NMEA reader for a USB GPS (u-blox and others), busybox awk.
#
# Reads NMEA sentences from the GPS and writes the same one-line snapshot that
# PagerTAK's GPS loop writes:   fix lat lon hae ce speed track sats epoch   ("-" = unknown)
# Usage: awk -v OUT=/tmp/pineappletak/gps -v SYNC=1 -f nmea.awk < /dev/ttyACM0
BEGIN { FS = ","; n = 0; spd = "-"; trk = "-"; synced = 0 }

function deg(v, h,   d, m, x) {            # ddmm.mmmm / dddmm.mmmm + hemisphere -> decimal degrees
    if (v !~ /^[0-9]+\.?[0-9]*$/) return ""
    d = int(v / 100); m = v - d * 100
    x = d + m / 60
    if (h == "S" || h == "W") x = -x
    return sprintf("%.7f", x)
}

function now(   c, t) { c = "date +%s"; c | getline t; close(c); return t }

function write(line,   tmp) {
    tmp = OUT ".tmp"
    print line > tmp; close(tmp)
    system("mv -f '" tmp "' '" OUT "'")
}

{ sub(/\r$/, ""); sub(/\*[0-9A-Fa-f][0-9A-Fa-f]$/, "") }

# RMC: time, status, lat, N/S, lon, E/W, speed (knots), course, date
$1 ~ /^\$G[NPLAB]RMC$/ {
    if ($3 == "A") {
        spd = ($8 ~ /^[0-9.]+$/) ? sprintf("%.2f", $8 * 0.514444) : "-"
        trk = ($9 ~ /^[0-9.]+$/) ? $9 : "-"
        # TAK drops CoT with a badly wrong time: set the clock from GPS once if it is clearly wrong
        if (SYNC == 1 && !synced && $10 ~ /^[0-9]{6}$/ && $2 ~ /^[0-9]{6}/) {
            c = "date -u +%Y"; c | getline y; close(c)
            if (y + 0 < 2025) {
                system(sprintf("date -u -s '20%s-%s-%s %s:%s:%s' >/dev/null 2>&1", substr($10, 5, 2), substr($10, 3, 2), substr($10, 1, 2),
                               substr($2, 1, 2), substr($2, 3, 2), substr($2, 5, 2)))
            }
            synced = 1
        }
    } else { spd = "-"; trk = "-" }
    next
}

# GGA: time, lat, N/S, lon, E/W, fix quality, satellites, HDOP, altitude (MSL), M, geoid separation
$1 ~ /^\$G[NPLAB]GGA$/ {
    sats = ($8 ~ /^[0-9]+$/) ? $8 + 0 : "-"
    if (++n % 2) next                          # one snapshot every ~2 s at 1 Hz
    lat = deg($3, $4); lon = deg($5, $6)
    if ($7 + 0 > 0 && lat != "" && lon != "") {
        hae = ($10 ~ /^-?[0-9.]+$/) ? $10 + (($12 ~ /^-?[0-9.]+$/) ? $12 : 0) : "-"
        ce = ($9 ~ /^[0-9.]+$/) ? sprintf("%.1f", $9 * 4) : "-"   # ~4 m per unit of HDOP for a u-blox
        write("1 " lat " " lon " " hae " " ce " " spd " " trk " " sats " " now())
    } else {
        write("0 - - - - - - " sats " " now())
    }
    fflush()
}
