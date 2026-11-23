# certs/

Put your TAK client certificate files here. **Never commit real certificates.** The repo's `.gitignore` excludes `*.p12`, `*.pem`, `*.key` and `*.crt` in this folder.

| File | Required | What it is |
|---|---|---|
| `client.pem` | yes (TLS) | Pager's client certificate **and** private key, unencrypted PEM |
| `ca.pem` | recommended | TAK Server CA / truststore, PEM, so the server certificate is verified |
| `*.p12` | optional | Drop your TAK `.p12` files here instead, and PagerTAK converts them on first run |

Convert on a PC:

```
openssl pkcs12 -legacy -in pager01.p12 -nodes -out client.pem      # drop -legacy on OpenSSL 1.1
openssl pkcs12 -legacy -in truststore-root.p12 -nokeys -out ca.pem
```

**No files needed at all:** enroll with your TAK username and password (web console *Settings > Enroll with your TAK account*, or Pager *Settings > TAK server > Enroll*), and PagerTAK writes `client.pem` and `ca.pem` here itself.

**No `scp` needed either:** in the web console, *Settings > Import a connection package* takes the ATAK connection `.zip`, and *Settings > Upload a certificate* takes a `.p12` or PEM. Both convert into this folder and reconnect.
