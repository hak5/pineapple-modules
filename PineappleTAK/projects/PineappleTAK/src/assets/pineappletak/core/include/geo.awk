# geo.awk - lat/lon helpers for PagerTAK (pure awk, works with busybox awk)
#   mgrs(lat, lon)            -> "16S EF 12345 67890"  (1 m precision, WGS84)
#   offset(lat, lon, brg, m)  -> "lat lon" of the point m meters away on bearing brg
function _tan(x) { return sin(x) / cos(x) }
function _floor(x) { return (x == int(x) || x >= 0) ? int(x) : int(x) - 1 }
function mgrs(lat, lon,    pi, a, f, k0, e2, ep2, zone, lon0, phi, lam, N, T, C, A, M, E, Nn, band, bands, set, col, row, colL, rowL, e100k, n100k, ce, cn) {
    if (lat < -80 || lat > 84) return "N/A"
    pi = 3.14159265358979; a = 6378137.0; f = 1/298.257223563; k0 = 0.9996
    e2 = f * (2 - f); ep2 = e2 / (1 - e2)
    zone = int((lon + 180) / 6) + 1; if (zone > 60) zone = 60
    if (lat >= 56 && lat < 64 && lon >= 3 && lon < 12) zone = 32
    if (lat >= 72) { if (lon >= 0 && lon < 9) zone = 31; else if (lon >= 9 && lon < 21) zone = 33; else if (lon >= 21 && lon < 33) zone = 35; else if (lon >= 33 && lon < 42) zone = 37 }
    lon0 = ((zone - 1) * 6 - 180 + 3) * pi / 180
    phi = lat * pi / 180; lam = lon * pi / 180
    N = a / sqrt(1 - e2 * sin(phi)^2); T = _tan(phi)^2; C = ep2 * cos(phi)^2; A = cos(phi) * (lam - lon0)
    M = a * ((1 - e2/4 - 3*e2^2/64 - 5*e2^3/256) * phi - (3*e2/8 + 3*e2^2/32 + 45*e2^3/1024) * sin(2*phi) \
        + (15*e2^2/256 + 45*e2^3/1024) * sin(4*phi) - (35*e2^3/3072) * sin(6*phi))
    E = k0 * N * (A + (1 - T + C) * A^3/6 + (5 - 18*T + T^2 + 72*C - 58*ep2) * A^5/120) + 500000
    Nn = k0 * (M + N * _tan(phi) * (A^2/2 + (5 - T + 9*C + 4*C^2) * A^4/24 + (61 - 58*T + T^2 + 600*C - 330*ep2) * A^6/720))
    if (lat < 0) Nn += 10000000
    bands = "CDEFGHJKLMNPQRSTUVWXX"
    band = substr(bands, int((lat + 80) / 8) + 1, 1)
    set = (zone - 1) % 6 + 1
    colL = (set % 3 == 1) ? "ABCDEFGH" : (set % 3 == 2) ? "JKLMNPQR" : "STUVWXYZ"
    rowL = "ABCDEFGHJKLMNPQRSTUV"
    e100k = int(E / 100000); n100k = int(Nn / 100000) % 20
    col = substr(colL, e100k, 1)
    row = substr(rowL, ((n100k + ((set % 2 == 0) ? 5 : 0)) % 20) + 1, 1)
    ce = int(E) % 100000; cn = int(Nn) % 100000
    return sprintf("%d%s %s%s %05d %05d", zone, band, col, row, ce, cn)
}
function offset(lat, lon, brg, m,    pi, R, d, t, p1, l1, p2, l2) {
    pi = 3.14159265358979; R = 6371008.8; d = m / R; t = brg * pi / 180
    p1 = lat * pi / 180; l1 = lon * pi / 180
    p2 = atan2(sin(p1)*cos(d) + cos(p1)*sin(d)*cos(t), sqrt(1 - (sin(p1)*cos(d) + cos(p1)*sin(d)*cos(t))^2))
    l2 = l1 + atan2(sin(t)*sin(d)*cos(p1), cos(d) - sin(p1)*sin(p2))
    return sprintf("%.6f %.6f", p2 * 180 / pi, ((l2 * 180 / pi) + 540) % 360 - 180)
}
