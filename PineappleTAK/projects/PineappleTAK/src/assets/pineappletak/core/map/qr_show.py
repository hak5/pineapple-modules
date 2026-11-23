#!/usr/bin/env python3
"""Shows a QR code of the PagerTAK web console address on the Pager screen.

The QR matrix comes from `qrencode -t ASCII` (opkg install qrencode); drawing
uses pagerfb, PagerTAK's pure-Python screen driver. Any button closes it.
"""
import argparse
import os
import subprocess
import sys
import time

W, H = 480, 222


def qr_matrix(text):
    out = subprocess.run(["qrencode", "-t", "ASCII", "-m", "1", "-l", "M", text],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True).stdout.decode()
    rows = [line for line in out.splitlines() if line.strip() or line]
    # ASCII output: each module is two characters, "##" dark and "  " light
    return [[line[i:i + 2] == "##" for i in range(0, len(line), 2)] for line in rows if line]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default="")                 # kept for older callers; not used
    ap.add_argument("--url", required=True)
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args(argv)
    m = qr_matrix(args.url)
    n = max(len(m), 1)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import pagerfb  # noqa: E402
    Pager = pagerfb.Pager
    with Pager() as p:
        p.set_rotation(270)
        p.clear_input_events()
        white, black, grey = p.rgb(255, 255, 255), p.rgb(0, 0, 0), p.rgb(150, 150, 150)
        p.clear(black)
        scale = max(1, (H - 8) // n)
        size = scale * n
        x0, y0 = 8, (H - size) // 2
        p.fill_rect(x0 - 4, y0 - 4, size + 8, size + 8, white)
        for r, row in enumerate(m):
            for c, dark in enumerate(row):
                if dark:
                    p.fill_rect(x0 + c * scale, y0 + r * scale, scale, scale, black)
        tx = x0 + size + 16
        p.draw_text(tx, 30, "PagerTAK web", white, 2)
        url = args.url
        for i in range(0, len(url), 36):
            p.draw_text(tx, 70 + (i // 36) * 16, url[i:i + 36], white, 1)
        p.draw_text(tx, H - 30, "Scan with your phone.", grey, 1)
        p.draw_text(tx, H - 16, "Any button closes.", grey, 1)
        p.flip()
        end = time.time() + args.timeout
        while time.time() < end:
            _, pressed, _ = p.poll_input()
            if pressed:
                break
            time.sleep(0.05)
        p.clear(black)
        p.flip()
    return 0


if __name__ == "__main__":
    sys.exit(main())
