# NullSec DeauthDetect

**WiFi Deauthentication Attack Detector for WiFi Pineapple MK7/Enterprise**

Real-time monitoring for deauthentication and disassociation frames with intelligent alerting, attacker tracking, and webhook notifications.

## Features

- **Real-time Monitoring** — Captures deauth/disassoc frames using tcpdump on monitor-mode interface
- **Intelligent Alerting** — Configurable threshold and time window for attack detection
- **Attacker Tracking** — Identifies and ranks source MACs by deauth frame count
- **Severity Classification** — CRITICAL/HIGH/MEDIUM/LOW based on frame rate
- **Webhook Notifications** — Discord/Slack alerts on attack detection
- **Channel Hopping** — Automatic channel rotation for full-spectrum monitoring
- **Persistent Statistics** — Tracks total deauths, unique attackers, alert history
- **Background Operation** — Runs as a background job with start/stop control

## How It Works

1. Starts `tcpdump` on a monitor-mode wireless interface
2. Filters for management frames: deauthentication (subtype 12) and disassociation (subtype 10)
3. Parses source/destination MACs and tracks frame counts
4. When deauth count exceeds threshold within the configured time window, triggers an alert
5. Alerts include severity rating, top attacker MACs, and frame statistics
6. Optionally sends webhook notification (Discord/Slack compatible)

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `interface` | `wlan1mon` | Monitor-mode wireless interface |
| `threshold` | `10` | Deauth frames per window to trigger alert |
| `window` | `30` | Time window in seconds |
| `webhook` | (empty) | Discord/Slack webhook URL for alerts |
| `channel_hop` | `true` | Enable automatic channel hopping |

## Alert Severity Levels

| Severity | Rate (frames/sec) | Indication |
|----------|--------------------|------------|
| CRITICAL | > 10 | Active targeted deauth attack |
| HIGH | > 5 | Probable deauth flood |
| MEDIUM | > 2 | Suspicious deauth activity |
| LOW | ≤ 2 | Minor deauth events (may be normal) |

## Dependencies

- `tcpdump` (installed via module dependency manager)

## API Actions

| Action | Description |
|--------|-------------|
| `start_monitor` | Start deauth monitoring |
| `stop_monitor` | Stop monitoring |
| `get_status` | Get running status and stats |
| `get_alerts` | Retrieve alert history |
| `clear_alerts` | Clear all alerts and stats |
| `get_interfaces` | List available wireless interfaces |
| `get_stats` | Get monitoring statistics |

## Output

Alerts are stored in `/root/.deauth-detect/alerts.json`:
```json
{
  "timestamp": "2024-01-15 14:30:22",
  "deauth_count": 47,
  "window_seconds": 30.0,
  "rate": 1.6,
  "severity": "MEDIUM",
  "top_attackers": [
    {"mac": "aa:bb:cc:dd:ee:ff", "count": 35},
    {"mac": "11:22:33:44:55:66", "count": 12}
  ]
}
```

## Use Cases

- **Defensive monitoring** — Detect if someone is running aireplay-ng or mdk4 deauth attacks against your network
- **Penetration testing** — Verify your own deauth attacks are reaching targets
- **Compliance auditing** — Monitor for unauthorized wireless denial-of-service activity
- **Incident response** — Identify attacker MACs and attack patterns

## Author

**NullSec** ([@bad-antics](https://github.com/bad-antics))

## License

MIT
