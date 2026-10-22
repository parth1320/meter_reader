"""Run the collector on your own PC.

You log in by hand (a browser window opens, so the portal's captcha sees a normal
person). The script then keeps the session alive and reads data every COLLECT_EVERY_H hours.
When the session dies, the login window opens again.

    python collector/local.py          # run forever
    python collector/local.py --once   # login if needed, collect once, exit

Needs a `.env` file in the project root with SUPABASE_URL and SUPABASE_SERVICE_KEY.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

import collect
from collect import BASE, Portal, SessionExpired, log

ROOT = Path(__file__).resolve().parent.parent
SESSION_FILE = ROOT / ".session"
KEEPALIVE_S = 8 * 60          # portal idles out after 20 min
COLLECT_EVERY_H = 2
LOGIN_TIMEOUT_S = 15 * 60


def load_env():
    f = ROOT / ".env"
    if not f.exists():
        sys.exit("Missing .env in the project root (see README).")
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))
    for v in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        if not os.environ.get(v):
            sys.exit(f".env is missing {v}")


def manual_login():
    """Open a visible browser; wait for the user to log in; return a Cookie header."""
    from playwright.sync_api import sync_playwright

    log("Opening browser - please log in to the portal (you have 15 minutes)...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        ua = page.evaluate("navigator.userAgent")
        page.goto(BASE)
        page.wait_for_url(re.compile(r"Dashboard\.aspx", re.I), timeout=LOGIN_TIMEOUT_S * 1000)
        page.wait_for_timeout(2000)
        cookie = "; ".join(f"{c['name']}={c['value']}" for c in ctx.cookies())
        browser.close()
    SESSION_FILE.write_text(json.dumps({"cookie": cookie, "ua": ua}), encoding="utf-8")
    collect.UA = ua  # the portal may tie the session to the browser identity
    log("Login captured.")
    return cookie


def keep_alive(cookie):
    """Same call the portal page makes to extend the session. Raises SessionExpired if dead."""
    portal = Portal(cookie)
    portal.init()  # also verifies we are still logged in
    for page, method in (("default.aspx", "ExtendSession"), ("Common.aspx", "GetrefreshedTokenJWT")):
        req = urllib.request.Request(
            f"{BASE}{page}/{method}", data=b"{}", method="POST",
            headers={"Cookie": cookie, "User-Agent": collect.UA, "csrftoken": portal.csrf,
                     "Content-Type": "application/json; charset=utf-8"})
        try:
            portal._open(req)
        except SessionExpired:
            raise
        except Exception as e:  # keep-alive is best effort
            log(f"{method} failed: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    load_env()

    cookie = None
    if SESSION_FILE.exists():
        try:
            saved = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            cookie, collect.UA = saved["cookie"], saved["ua"]
        except Exception:
            SESSION_FILE.unlink(missing_ok=True)
    next_collect = 0.0
    fresh = False
    while True:
        try:
            if not cookie:
                cookie = manual_login()
                fresh = True
            if time.time() >= next_collect:
                collect.collect_once(cookie)
                fresh = False
                next_collect = time.time() + COLLECT_EVERY_H * 3600
                if args.once:
                    return
            else:
                keep_alive(cookie)
                log("session kept alive")
        except SessionExpired as e:
            log("Session expired:", e)
            if fresh:
                sys.exit("The session was rejected right after a fresh login, so retrying won't help. "
                         "Send the 'debug:' line above to get it fixed (debug_page.html was saved).")
            cookie = None
            SESSION_FILE.unlink(missing_ok=True)
            continue  # reopen the login window immediately
        except Exception as e:  # network blip etc. - try again next round
            log("error:", repr(e))
        time.sleep(KEEPALIVE_S)


if __name__ == "__main__":
    main()
