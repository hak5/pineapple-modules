# Sentinel

A module that watches your own Wi-Fi instead of attacking someone else's. The idea is to leave the Pineapple
running at home as a sentinel for your Wi-Fi.

- Spectrum of 2.4 and 5 GHz (5 GHz with the MK7AC), coloured by security
- Security audit of every network nearby (WPA3, PMF, open, WEP, WPS), with plain-language reasons
- Your networks: star your own access points to get their own score and have them watched
- Passive intrusion detection: someone copying your network's name, deauthentication bursts, floods of fake
  access points, an access point answering for any name, and a few more

A Reports tab sums up the last 24 hours, 7 or 30 days (scores day by day, what to change on your router, alerts,
channels), and exports it as a designed HTML page, PDF, CSV or Markdown.

The Notifications tab can send alerts to your phone through ntfy (ntfy.sh or your own server). The Pineapple needs
a way to reach it: client mode on wlan2, not the MK7AC.

A type of alert that is just noise for you (say, your router changing channel) can be muted: still recorded,
but no longer counted as unread.

It only listens: it never transmits, and by default it doesn't keep any info about other people's devices.

It needs `python3-sqlite3`. If it's missing, the module shows a button to install it with opkg (the Pineapple
needs Internet for that).

Don't run Recon while Sentinel is listening: both use the same radios, so Recon misses networks. Stop monitoring
first, it gives the radios back.

Full documentation, screenshots, test reports and an offline installer:
https://github.com/wackojice/sentinel-pineapple

MIT licence. Made by Not_Hackerman.
