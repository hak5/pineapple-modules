#!/bin/bash
# shellcheck disable=SC2154
# PagerTAK - TAK Server setup helpers (sourced by payload.sh)
#
#   tak_enroll       get a client certificate from the TAK Server with a username
#                    and password (TAK Server certificate enrollment, port 8446)
#   cert_import      a .p12 or .pem uploaded from the web console
#   pkg_import       an ATAK connection data package (.pref + .p12 files)
#   tak_test         try the connection and say exactly what fails
#   cert_days        days until the client certificate expires
#   setup_in_browser first-run setup from the web console
#
# Long jobs write their progress to $RUN/<job>.status ("busy|...", "ok|..." or
# "err|..."), which the web console polls.

ENROLL_LOG="${LOG_TMP:-/tmp/pagertak}-enroll.log"

job_status() { printf '%s\n' "$2" > "$RUN/$1.status"; }

certs_ready() {
    [ -s "$CERT_DIR/$C_CLIENT_PEM" ] && grep -q "PRIVATE KEY" "$CERT_DIR/$C_CLIENT_PEM" 2>/dev/null
}

# cert_days -> days left on the client certificate (empty if none / no openssl)
cert_days() {
    local end now t
    certs_ready && command -v openssl >/dev/null 2>&1 || return 1
    end=$(openssl x509 -noout -enddate -in "$CERT_DIR/$C_CLIENT_PEM" 2>/dev/null | cut -d= -f2) || return 1
    [ -n "$end" ] || return 1
    t=$(date -d "$end" +%s 2>/dev/null) || t=$(date -D "%b %d %H:%M:%S %Y" -d "${end% GMT}" +%s 2>/dev/null) || return 1
    now=$(date +%s)
    echo $(( (t - now) / 86400 ))
}

cert_cn() {
    command -v openssl >/dev/null 2>&1 && certs_ready || return 1
    openssl x509 -noout -subject -in "$CERT_DIR/$C_CLIENT_PEM" 2>/dev/null | sed -n 's/.*CN *= *\([^,/]*\).*/\1/p'
}

# Warns on the Pager when the client certificate runs out within 30 days
cert_expiry_check() {
    local d
    d=$(cert_days) || return 0
    if [ "$d" -lt 0 ]; then LOG red "Your TAK client certificate has EXPIRED - enroll again or upload a new one"
    elif [ "$d" -le 30 ]; then LOG yellow "Your TAK client certificate expires in $d days"
    fi
}

# p12_import FILE OUT PASSWORD [nokeys] -> no prompts (for the web console).
# Installs the OpenSSL legacy module itself if the file needs it.
p12_import() {
    local rc
    p12_to_pem "$1" "$2" "$3" "$4"; rc=$?
    if [ $rc = 3 ]; then
        { opkg update; opkg install libopenssl-legacy; } >> "$CERT_LOG" 2>&1
        p12_to_pem "$1" "$2" "$3" "$4"; rc=$?
    fi
    return $rc
}

p12_reason() {
    case $1 in
        2) echo "wrong password" ;;
        3) echo "it uses old RC2/3DES encryption and the OpenSSL legacy module could not be installed" ;;
        4) echo "this $DEVICE_WORD's OpenSSL cannot read old RC2/3DES files - use Enroll instead, or convert it to PEM on a PC" ;;
        *) echo "not a readable .p12 (see $CERT_LOG)" ;;
    esac
}

# cert_import KIND(client|ca) FILE PASSWORD -> "ok|..." / "err|..."
cert_import() {
    local kind=$1 f=$2 pw=$3 dest tmp rc
    [ -s "$f" ] || { echo "err|Upload missing"; return; }
    command -v openssl >/dev/null 2>&1 || { echo "err|openssl is not installed - run: opkg install openssl-util"; return; }
    mkdir -p "$CERT_DIR"
    if [ "$kind" = client ]; then dest="$CERT_DIR/$C_CLIENT_PEM"; else dest="$CERT_DIR/$C_CA_PEM"; fi
    tmp="$RUN/certimport.pem"
    if grep -q -- "-----BEGIN" "$f" 2>/dev/null; then
        cp "$f" "$tmp"
    else
        if [ "$kind" = client ]; then p12_import "$f" "$tmp" "${pw:-atakatak}"; else p12_import "$f" "$tmp" "${pw:-atakatak}" nokeys; fi
        rc=$?
        [ $rc = 0 ] || { rm -f "$tmp"; echo "err|Could not read the .p12: $(p12_reason $rc)"; return; }
    fi
    if [ "$kind" = client ]; then
        grep -q "PRIVATE KEY" "$tmp" || { rm -f "$tmp"; echo "err|No private key in that file - pick the client certificate, not the truststore"; return; }
        grep -q "ENCRYPTED" "$tmp" && { rm -f "$tmp"; echo "err|The private key is encrypted - export it unencrypted"; return; }
    fi
    grep -q "CERTIFICATE-----" "$tmp" || { rm -f "$tmp"; echo "err|No certificate in that file"; return; }
    [ -f "$dest" ] && cp -p "$dest" "$dest.bak"
    ( umask 077; cp "$tmp" "$dest.tmp" ) && mv "$dest.tmp" "$dest"
    rm -f "$tmp"
    if [ "$kind" = client ]; then cfg_set client_pem "$C_CLIENT_PEM"; else cfg_set ca_pem "$C_CA_PEM"; fi
    : > "$RUN/reconnect"; : > "$RUN/reload"
    LOG green "Certificate saved: certs/${dest##*/}"
    echo "ok|Saved certs/${dest##*/}"
}

# pkg_import HOST PORT PROTO CLIENT_P12 CLIENT_PW CA_P12 CA_PW
# (the web console has already unpacked the data package and read its .pref)
pkg_import() {
    local host=$1 port=$2 proto=$3 cfile=$4 cpw=$5 afile=$6 apw=$7 r msg="" had_client=0
    [ -n "$host" ] || { echo "err|No server address in that package"; return; }
    cfg_set host "$host"
    [[ $port =~ ^[0-9]{1,5}$ ]] && cfg_set port "$port"
    case "$proto" in ssl|tls) cfg_set proto tls ;; tcp) cfg_set proto tcp ;; udp) cfg_set proto udp ;; esac
    if [ -s "$afile" ]; then
        r=$(cert_import ca "$afile" "$apw"); [ "${r%%|*}" = ok ] || msg+=" CA: ${r#*|}."
    fi
    if [ -s "$cfile" ]; then
        had_client=1
        r=$(cert_import client "$cfile" "$cpw"); [ "${r%%|*}" = ok ] || msg+=" Client certificate: ${r#*|}."
    fi
    rm -f "$cfile" "$afile"
    load_config; : > "$RUN/reconnect"; : > "$RUN/reload"
    [ "${WEB_LOADED:-0}" = 1 ] && web_cfg_write
    if [ -n "$msg" ]; then echo "err|Server set to $host.$msg"; return; fi
    LOG green "Connection package imported: $C_PROTO://$C_HOST:$C_PORT"
    if [ $had_client = 0 ] && ! certs_ready && [ "$C_PROTO" = tls ]; then
        echo "ok|Server set to $host:$C_PORT. This package has no client certificate - enroll with your TAK username and password"
    else
        echo "ok|Imported: $C_PROTO://$C_HOST:$C_PORT"
    fi
}

# json_get FILE KEY -> string value (jsonfilter on OpenWrt, else Python, else sed)
json_get() {
    if command -v jsonfilter >/dev/null 2>&1; then
        jsonfilter -i "$1" -e "@.$2" 2>/dev/null
    elif configure_python 2>/dev/null; then
        "$PYTHON_BIN" -c 'import json,sys; v=json.load(open(sys.argv[1])).get(sys.argv[2]); print(v if isinstance(v, str) else "")' "$1" "$2" 2>/dev/null
    fi
}

pem_wrap() {  # pem_wrap TEXT -> PEM CERTIFICATE (adds the header/footer if the server left them out)
    if grep -q -- "-----BEGIN" <<< "$1"; then printf '%s\n' "$1"
    else printf -- '-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n' "$(tr -d ' \r\n' <<< "$1" | awk '{ for (i = 1; i <= length($0); i += 64) print substr($0, i, 64) }')"
    fi
}

# tak_enroll HOST USER PASSWORD [PORT] -> status in $RUN/enroll.status
# TAK Server's enrollment API: GET /Marti/api/tls/config (subject fields),
# POST the CSR to /Marti/api/tls/signClient/v2 (JSON: signedCert, ca0, ca1...).
tak_enroll() {
    local host=$1 user=$2 pass=$3 port=${4:-8446} dir="$RUN/enroll" subj o ou code rc k v ca=() tls=(-k)
    job_status enroll "busy|Contacting $host:$port..."
    command -v openssl >/dev/null 2>&1 || { job_status enroll "err|openssl is not installed - run: opkg install openssl-util"; return 1; }
    [ -n "$host" ] && [ -n "$user" ] && [ -n "$pass" ] || { job_status enroll "err|Server, username and password are all needed"; return 1; }
    [[ $host =~ ^[A-Za-z0-9.-]+$ ]] || { job_status enroll "err|Server must be a host name or IP address"; return 1; }
    rm -rf "$dir"; mkdir -p "$dir"; chmod 700 "$dir"
    [ -s "$CERT_DIR/$C_CA_PEM" ] && tls=(--cacert "$CERT_DIR/$C_CA_PEM")
    local cu=${user//\\/\\\\} cp=${pass//\\/\\\\}          # curl config quoting: \ and " are escaped
    cu=${cu//\"/\\\"}; cp=${cp//\"/\\\"}
    ( umask 077; printf 'user = "%s:%s"\n' "$cu" "$cp" > "$dir/auth" )   # keeps the password off the command line
    enroll_config() {
        code=$(curl -sS "${tls[@]}" --connect-timeout 15 --max-time 30 -K "$dir/auth" -o "$dir/config.xml" -w '%{http_code}' \
            "https://$host:$port/Marti/api/tls/config"); rc=$?; echo "config: curl $rc HTTP $code"
    }
    {
        echo "== $(date '+%F %T') enroll $user at $host:$port"
        enroll_config
        # Many servers put a public certificate (Let's Encrypt...) on the enrollment port, not the TAK CA's:
        # then check it against the public CAs instead (never unchecked - the password goes with it)
        case "$rc" in 35|51|58|60|77|83)
            if [ "${tls[0]}" = --cacert ]; then
                echo "the TAK CA does not match the enrollment port's certificate - trying the public CAs"
                tls=(); enroll_config
            fi ;;
        esac
    } >> "$ENROLL_LOG" 2>&1
    case "$rc" in
        6) rm -rf "$dir"; job_status enroll "err|Cannot look up $host - is this $DEVICE_WORD online? (internet / DNS)"; return 1 ;;
        7) rm -rf "$dir"; job_status enroll "err|$host refused the connection on port $port (wrong enrollment port?)"; return 1 ;;
        28) rm -rf "$dir"; job_status enroll "err|No answer from $host:$port (firewall, or the enrollment port is closed)"; return 1 ;;
    esac
    case "$rc" in 35|51|58|60|77|83)
        rm -rf "$dir"
        job_status enroll "err|Could not verify $host:$port's certificate (not from your TAK CA or a public CA). On OpenWrt, opkg install ca-bundle adds the public CA list."
        return 1 ;;
    esac
    case "$code" in
        200) ;;
        401|403) rm -rf "$dir"; job_status enroll "err|The TAK Server refused that username or password"; return 1 ;;
        000|"") rm -rf "$dir"; job_status enroll "err|Cannot reach $host:$port (enrollment port open? see $ENROLL_LOG)"; return 1 ;;
        *) rm -rf "$dir"; job_status enroll "err|The TAK Server answered HTTP $code on the enrollment port"; return 1 ;;
    esac
    subj="/CN=${user//\//_}"
    while IFS='|' read -r k v; do
        case "$k" in C|ST|L|O|OU) subj+="/$k=${v//\//_}" ;; esac
    done < <(grep -o '<[A-Za-z0-9:]*nameEntry [^>]*>' "$dir/config.xml" | while read -r e; do
                 printf '%s|%s\n' "$(sed -n 's/.* name="\([^"]*\)".*/\1/p' <<< "$e")" "$(sed -n 's/.* value="\([^"]*\)".*/\1/p' <<< "$e")"
             done)
    job_status enroll "busy|Making a key (this takes a few seconds on this device)..."
    if ! openssl req -new -newkey rsa:2048 -nodes -keyout "$dir/key.pem" -subj "$subj" -out "$dir/csr.pem" >> "$ENROLL_LOG" 2>&1; then
        rm -rf "$dir"; job_status enroll "err|openssl could not make a key (see $ENROLL_LOG)"; return 1
    fi
    grep -v -- "-----" "$dir/csr.pem" > "$dir/csr.b64"
    job_status enroll "busy|Asking $host to sign the certificate..."
    {
        code=$(curl -sS "${tls[@]}" --connect-timeout 15 --max-time 60 -K "$dir/auth" -o "$dir/signed.json" -w '%{http_code}' \
            -H "Content-Type: application/pkcs10" -H "Accept: application/json" --data-binary "@$dir/csr.b64" \
            "https://$host:$port/Marti/api/tls/signClient/v2?clientUid=$C_UID&version=${PRODUCT_NAME:-PagerTAK}-$PAYLOAD_VERSION"); echo "sign: curl $? HTTP $code"
    } >> "$ENROLL_LOG" 2>&1
    rm -f "$dir/auth"
    if [ "$code" != 200 ]; then
        rm -rf "$dir"
        case "$code" in 401|403) job_status enroll "err|The TAK Server refused the request (user not allowed to enroll?)" ;;
            *) job_status enroll "err|Signing failed (HTTP ${code:-none}, see $ENROLL_LOG)" ;; esac
        return 1
    fi
    v=$(json_get "$dir/signed.json" signedCert)
    [ -n "$v" ] || { rm -rf "$dir"; job_status enroll "err|The TAK Server's answer had no certificate (see $ENROLL_LOG)"; return 1; }
    { cat "$dir/key.pem"; pem_wrap "$v"; } > "$dir/client.pem"
    for k in ca0 ca1 ca2 ca3; do
        v=$(json_get "$dir/signed.json" "$k"); [ -n "$v" ] && ca+=("$(pem_wrap "$v")")
    done
    openssl x509 -noout -in "$dir/client.pem" 2>/dev/null || { rm -rf "$dir"; job_status enroll "err|The signed certificate could not be read"; return 1; }
    mkdir -p "$CERT_DIR"
    [ -f "$CERT_DIR/$C_CLIENT_PEM" ] && cp -p "$CERT_DIR/$C_CLIENT_PEM" "$CERT_DIR/$C_CLIENT_PEM.bak"
    ( umask 077; cp "$dir/client.pem" "$CERT_DIR/$C_CLIENT_PEM.tmp" ) && mv "$CERT_DIR/$C_CLIENT_PEM.tmp" "$CERT_DIR/$C_CLIENT_PEM"
    if [ ${#ca[@]} -gt 0 ]; then
        printf '%s\n' "${ca[@]}" > "$CERT_DIR/$C_CA_PEM.tmp" && mv "$CERT_DIR/$C_CA_PEM.tmp" "$CERT_DIR/$C_CA_PEM"
    fi
    rm -rf "$dir"
    cfg_set host "$host"; cfg_set proto tls
    [ "$(cfg_get port 8089)" = 8087 ] && cfg_set port 8089
    load_config; : > "$RUN/reconnect"; : > "$RUN/reload"
    [ "${WEB_LOADED:-0}" = 1 ] && web_cfg_write
    LOG green "Enrolled with $host as $user"
    job_status enroll "ok|Enrolled as $user - certificate saved, valid $(cert_days) days"
}

host_resolves() {
    [[ $1 =~ ^[0-9.]+$ ]] && return 0
    if command -v nslookup >/dev/null 2>&1; then nslookup "$1" >/dev/null 2>&1
    elif command -v getent >/dev/null 2>&1; then getent hosts "$1" >/dev/null 2>&1
    else return 0; fi
}

# tak_test -> status in $RUN/test.status: name, port, TLS handshake, client
# certificate, server certificate - and the first thing that fails.
tak_test() {
    local host=$C_HOST port=$C_PORT out args
    job_status test "busy|Testing $C_PROTO://$host:$port..."
    if ! host_resolves "$host"; then
        job_status test "err|Cannot resolve $host (check the address and that this device is online)"; return 1
    fi
    if [ "$C_PROTO" = udp ]; then job_status test "ok|UDP sends without a reply, so there is nothing to test beyond the address"; return 0; fi
    if ! tcp_probe "$host" "$port"; then
        job_status test "err|No connection to $host:$port: $PROBE_ERR (wrong port, firewall, or the server is down)"; return 1
    fi
    if [ "$C_PROTO" = tcp ]; then job_status test "ok|Connected to $host:$port (TCP, no certificate needed)"; return 0; fi
    command -v openssl >/dev/null 2>&1 || { job_status test "err|openssl is not installed - run: opkg install openssl-util"; return 1; }
    certs_ready || { job_status test "err|Port $port answers, but there is no client certificate yet - enroll or upload one"; return 1; }
    args=(-connect "$host:$port" -cert "$CERT_DIR/$C_CLIENT_PEM" -key "$CERT_DIR/$C_CLIENT_PEM")
    [[ $host =~ ^[0-9.]+$ ]] || args+=(-servername "$host")
    [ -s "$CERT_DIR/$C_CA_PEM" ] && args+=(-CAfile "$CERT_DIR/$C_CA_PEM")
    out=$( { sleep 4; } | timeout 10 openssl s_client "${args[@]}" 2>&1 )
    local d; d=$(cert_days)
    if grep -qi "certificate expired" <<< "$out" || { [ -n "$d" ] && [ "$d" -lt 0 ]; }; then
        job_status test "err|Your client certificate has expired - enroll again"; return 1
    fi
    if grep -qi "unknown ca\|bad certificate\|certificate unknown\|certificate required\|handshake failure" <<< "$out"; then
        job_status test "err|The TAK Server rejected your client certificate (not issued by its CA, or revoked)"; return 1
    fi
    if grep -qi "wrong version number\|unknown protocol\|packet length too long" <<< "$out"; then
        job_status test "err|Port $port is not a TLS port - TLS is usually 8089, TCP 8087"; return 1
    fi
    if ! grep -q "BEGIN CERTIFICATE\|Server certificate" <<< "$out"; then
        job_status test "err|TLS handshake failed: $(grep -m1 -i 'error\|alert' <<< "$out" | cut -c1-120)"; return 1
    fi
    local note=""
    if [ -s "$CERT_DIR/$C_CA_PEM" ] && ! grep -q "Verify return code: 0 (ok)" <<< "$out"; then
        note=" (warning: the server's certificate did not verify against your CA file)"
    elif [ ! -s "$CERT_DIR/$C_CA_PEM" ]; then
        note=" (no CA file, so the server's certificate is not checked)"
    fi
    job_status test "ok|Connected to $host:$port with your certificate$note${d:+, certificate valid $d more days}"
}

# First-run setup from a web browser. Starts the web console in setup mode and
# waits until the browser presses Finish (or B on the Pager cancels).
setup_in_browser() {
    local rc b
    [ "${WEB_LOADED:-0}" = 1 ] || { ERROR_DIALOG "The web console files are missing - copy the full $PRODUCT_NAME folder again."; return 1; }
    web_install || return 1
    if [ ! -s "$WEB_AUTH" ]; then
        PROMPT "Choose a password for the web page. Write it down - you type it in the browser."
        web_password_prompt || return 1
    fi
    : > "$RUN/setup_mode"; rm -f "$RUN/setup_done"
    web_start; rc=$?
    case $rc in
        0) ;;
        *) rm -f "$RUN/setup_mode"; ERROR_DIALOG "The web console did not start (code $rc, see $WEB_LOG)"; return 1 ;;
    esac
    cfg_set web 1
    LED CYAN
    LOG green "Setup in your browser:"
    web_show_urls
    LOG white "Sign in, fill in the TAK server and certificates, then press Finish setup."
    LOG white "A = show a QR code   B = cancel"
    while [ ! -f "$RUN/setup_done" ]; do
        b=$(WAIT_FOR_INPUT 1)
        case "$b" in
            A) web_qr ;;
            B) if [ "$(CONFIRMATION_DIALOG "Cancel setup?")" = "$DUCKYSCRIPT_USER_CONFIRMED" ]; then
                   rm -f "$RUN/setup_mode"; web_stop; return 1
               fi ;;
        esac
    done
    rm -f "$RUN/setup_mode" "$RUN/setup_done"
    cfg_set configured 1
    load_config
    LOG green "Setup finished"
    return 0
}

# setup_done (web command) -> checks the basics before the payload carries on
setup_finish() {
    load_config
    [ -n "$C_HOST" ] && [ "$C_HOST" != tak.example.com ] || { echo "err|Enter the TAK server address first"; return; }
    if [ "$C_PROTO" = tls ] && ! certs_ready; then echo "err|TLS needs a client certificate - enroll, import a package or upload one"; return; fi
    [ -n "$C_CALLSIGN" ] || { echo "err|Enter a callsign"; return; }
    : > "$RUN/setup_done"; rm -f "$RUN/setup_mode"
    [ "${WEB_LOADED:-0}" = 1 ] && web_cfg_write
    echo "ok|Setup finished - $PRODUCT_NAME is connecting"
}
