"""Fetch DGVCL smart-meter data and upsert it into Supabase.

Auth (first match wins):
  PORTAL_COOKIE            a Cookie header copied from a browser you logged in with
  PORTAL_USER/PORTAL_PASS  log in with a headless browser (needs `playwright`)

Other env: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape

BASE = "https://dgvclsmartmeter.dgvclinfra.in/portal/"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
IST = "+05:30"


def log(*a):
    print(datetime.now(timezone.utc).strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- auth
def login_with_browser(user, password):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        page.fill("#txtLogin", user)
        page.fill("input[type=password]", password)
        page.click("#btnlogin")
        page.wait_for_timeout(6000)
        # Surface whatever the portal tells the user (toast / inline error) to diagnose failures.
        msgs = page.evaluate(
            """() => [...document.querySelectorAll('.toast-message, .toast-error, .error_messagecommon, '
                + '[class*=error], [role=alert]')].map(e => e.innerText.trim()).filter(Boolean)""")
        if msgs and "Dashboard" not in page.url:
            log("portal message after login click:", " | ".join(dict.fromkeys(msgs))[:300])
        log("page url after click:", page.url)
        try:
            page.wait_for_url(re.compile(r"Dashboard\.aspx", re.I), timeout=45000)
        except Exception:
            shot = os.environ.get("LOGIN_DEBUG_SHOT", "login_failed.png")
            page.screenshot(path=shot)
            browser.close()
            sys.exit("Login did not reach the dashboard (wrong credentials, or the portal "
                     "rejected the headless login). Screenshot: " + shot)
        cookie = "; ".join(f"{c['name']}={c['value']}" for c in ctx.cookies())
        browser.close()
        return cookie


def get_cookie():
    if os.environ.get("PORTAL_COOKIE"):
        return os.environ["PORTAL_COOKIE"]
    user, pw = os.environ.get("PORTAL_USER"), os.environ.get("PORTAL_PASS")
    if not (user and pw):
        sys.exit("Set PORTAL_COOKIE, or PORTAL_USER and PORTAL_PASS.")
    log("logging in with headless browser")
    return login_with_browser(user, pw)


# ---------------------------------------------------------------- portal
class Portal:
    def __init__(self, cookie):
        self.cookie = cookie
        self.csrf = None
        self.meter = None

    def _open(self, req):
        try:
            return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            sys.exit(f"HTTP {e.code} from portal (session expired?)")

    def init(self):
        req = urllib.request.Request(BASE + "usages.aspx", headers={"Cookie": self.cookie, "User-Agent": UA})
        html = self._open(req)

        def hidden(id_):
            m = re.search(r'id="%s"[^>]*value="([^"]*)"' % id_, html)
            return unescape(m.group(1)) if m else None

        self.csrf, self.meter = hidden("hdnCSRFToken"), hidden("hdnMeterValue")
        if not (self.csrf and self.meter):
            sys.exit("Not logged in (no CSRF token / meter number on the usage page).")

    def call(self, page, method, payload):
        req = urllib.request.Request(
            f"{BASE}{page}/{method}",
            data=json.dumps(payload).encode(),
            headers={"Cookie": self.cookie, "User-Agent": UA, "csrftoken": self.csrf,
                     "Content-Type": "application/json; charset=utf-8"},
        )
        return json.loads(json.loads(self._open(req))["d"])


# ---------------------------------------------------------------- parsing
def num(s):
    """'252.56V' -> 252.56 ; 'NA'/'' -> None"""
    m = re.search(r"-?\d+(?:\.\d+)?", s or "")
    return float(m.group()) if m else None


def ts(s):
    return s + IST if s else None


def realtime_row(d):
    return {
        "meter_time": ts(d["MeterDateTime"]),
        "meter": d["MeterNumber"],
        "voltage_v": num(d.get("VoltageL1")),
        "current_a": num(d.get("CurrentL1")),
        "frequency_hz": num(d.get("Frequency")),
        "import_kwh": num(d.get("ActiveEnergyImport")),
        "export_kwh": num(d.get("ActiveEnergyExport")),
        "active_power_kw": num(d.get("ActivePower")),
        "apparent_power_kva": num(d.get("ApparentPower")),
        "reactive_power_var": num(d.get("ReactivePower")),
        "md_kw": num(d.get("MDActiveImport")),
        "md_time": ts(d.get("MDDatetime")),
        "power_factor": num(d.get("SignedPowerFactor")),
        "load_limit_w": num(d.get("LoadLimitValue")),
    }


def fetch_realtime(portal):
    for attempt in range(6):
        r = portal.call("GetRealTimeReads.aspx", "GetRealTimeReadss", {})
        data = r.get("Data")
        if r.get("Status") == 1 and data and data.get("MeterNumber"):
            log("real-time:", r.get("Message", "")[:110])
            return realtime_row(data)
        log(f"real-time not ready (status {r.get('Status')}): {str(r.get('Message'))[:100]}")
        time.sleep(60)
    return None


def fetch_monthly(portal):
    u = portal.call("Usages.aspx", "LoadUsage", dict(
        UsageOrGeneration="U", Type="K", Mode="M", strDate="", endDate="", hourlyType="",
        SeasonId="", weatherOverlay=0, usageyear="", MeterNumber=portal.meter,
        DateFromDaily="", DateToDaily="", DateFromSeasonal="0", DateToSeasonal="0",
        IsNonAmi=False, IsNetUsage=True))
    if "dtException" in u:
        log("usage error:", u["dtException"][0].get("MessageInformation"))
        return []
    return [{"month": f"{r['Year']}-{r['Month']:02d}-01", "kwh": r["UsageValue"], "demand_kw": r["DemandValue"]}
            for r in u.get("objUsageGenerationResultSetTwo", [])]


def fetch_bills(portal):
    b = portal.call("dashboard.aspx", "LoadAllUsageAjax",
                    {"Type": "D", "Mode": "M", "UsageType": "NU", "MeterNumber": portal.meter})
    out = []
    for row in b.get("objNonAMIBillingData", []):
        for pre in ("Last", "Last2nd", "LastYear"):
            if row.get(pre + "BillYear") and float(row[pre + "Bill"] or 0) > 0:
                out.append({"month": f"{row[pre + 'BillYear']}-{row[pre + 'BillMonth']:02d}-01",
                            "amount": float(row[pre + "Bill"])})
    return out


# ---------------------------------------------------------------- supabase
def upsert(table, rows, key):
    if not rows:
        return
    url = os.environ["SUPABASE_URL"].rstrip("/") + f"/rest/v1/{table}?on_conflict={key}"
    k = os.environ["SUPABASE_SERVICE_KEY"]
    req = urllib.request.Request(url, data=json.dumps(rows).encode(), method="POST", headers={
        "apikey": k, "Authorization": "Bearer " + k, "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except urllib.error.HTTPError as e:
        sys.exit(f"Supabase {table}: HTTP {e.code} {e.read().decode()[:300]}")
    log(f"upserted {len(rows)} row(s) into {table}")


def main():
    for v in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        if not os.environ.get(v):
            sys.exit(f"Missing env {v}")
    portal = Portal(get_cookie())
    portal.init()
    log("meter", portal.meter)

    rt = fetch_realtime(portal)
    if rt:
        upsert("realtime_reads", [rt], "meter_time")
    upsert("monthly_usage", fetch_monthly(portal), "month")
    upsert("bills", fetch_bills(portal), "month")


if __name__ == "__main__":
    main()
