"""
Scrapes historical tee-sheet data from Sterling Country Club's Clubessential
NetCaddy booking system, walking backward day by day from a start date until
the site stops returning data for a given day (three consecutive failures).

Output: one JSON object per day, appended to data/raw/teesheet.ndjson, so
progress survives interruption and re-runs can resume.

Usage:
    CLUB_USERNAME=... CLUB_PASSWORD=... python scraper.py \
        [--start-date 8/18/2026] [--max-days 3650] [--delay 1.5]
"""
import argparse
import datetime
import json
import os
import sys
import time

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

BASE_URL = "https://www.sccathn.com"
LOGIN_URL = f"{BASE_URL}/member-login"
TEESHEET_URL = f"{BASE_URL}/Default.aspx?p=DynamicModule&pageid=390519&tt=booking&ssid=311496&vnf=1"

USERNAME_SEL = "#masterPageUC_MPCA390487_ctl00_ctl02_txtUsername"
PASSWORD_SEL = "#masterPageUC_MPCA390487_ctl00_ctl02_txtPassword"
LOGIN_BTN_SEL = "#btnSecureLogin"
LOGIN_ERROR_SEL = "#login_error .errLogin"

TIME_SLOT_PANEL_SEL = "#masterPageUC_MPCA390550_ctl02_ctrl_Booking_ctl02_TimeSlotPanel"
DATE_LABEL_SEL = ".NC_DashboardDate .date"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "raw")
OUT_FILE = os.path.join(DATA_DIR, "teesheet.ndjson")


def log(msg):
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def login(page, username, password):
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.fill(USERNAME_SEL, username)
    page.fill(PASSWORD_SEL, password)
    page.click(LOGIN_BTN_SEL)

    try:
        page.wait_for_selector("a[href*='logout']", timeout=20000)
    except PWTimeoutError:
        err_el = page.query_selector(LOGIN_ERROR_SEL)
        err_text = err_el.inner_text().strip() if err_el else ""
        raise RuntimeError(f"Login did not complete (error: {err_text!r}). Check credentials.")
    log("Logged in.")


def go_to_date(page, date_obj, timeout_s=8):
    date_str = f"{date_obj.month}/{date_obj.day}/{date_obj.year}"
    expected_label = date_obj.strftime("%A, %B ") + str(date_obj.day) + date_obj.strftime(", %Y")

    page.evaluate(f"changeDate('{date_str}')")

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        el = page.query_selector(DATE_LABEL_SEL)
        if el:
            label = el.inner_text().strip()
            if label == expected_label:
                return True
        time.sleep(0.3)
    return False


def extract_day(page):
    html = page.inner_html(TIME_SLOT_PANEL_SEL)
    soup = BeautifulSoup(html, "html.parser")

    slots = []
    for sec in soup.select("div.tsSection"):
        time_span = sec.select_one(".timeText")
        if not time_span:
            continue
        try:
            time_text = next(time_span.stripped_strings)
        except StopIteration:
            continue

        blocked_reason = None
        blocked_el = sec.select_one("[class*=resSectionBlocked] .blockBorder")
        if blocked_el:
            txt = blocked_el.get_text(strip=True)
            if txt:
                blocked_reason = txt

        parties = []
        for party_div in sec.select("div.NC_Reserved"):
            players = []
            for p in party_div.select(".playerJQ"):
                cls = p.get("class", [])
                if "NC_GuestPlayer" in cls:
                    ptype = "guest"
                elif "NC_TBDPlayer" in cls:
                    ptype = "tbd"
                else:
                    ptype = "member"
                name_el = p.select_one(".fullName")
                name = name_el.get_text(strip=True) if name_el else ""
                if ptype != "tbd" and name:
                    players.append({"name": name, "type": ptype})
            if players:
                parties.append(players)

        slots.append({
            "time": time_text,
            "blocked_reason": blocked_reason,
            "parties": parties,
        })
    return slots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", default=None, help="m/d/yyyy, default = yesterday")
    ap.add_argument("--max-days", type=int, default=3650)
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between days")
    ap.add_argument("--consecutive-failures-to-stop", type=int, default=3)
    args = ap.parse_args()

    username = os.environ.get("CLUB_USERNAME")
    password = os.environ.get("CLUB_PASSWORD")
    if not username or not password:
        sys.exit("Set CLUB_USERNAME and CLUB_PASSWORD environment variables.")

    if args.start_date:
        m, d, y = (int(x) for x in args.start_date.split("/"))
        start_date = datetime.date(y, m, d)
    else:
        start_date = datetime.date.today() - datetime.timedelta(days=1)

    os.makedirs(DATA_DIR, exist_ok=True)

    already_done = set()
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE) as f:
            for line in f:
                try:
                    already_done.add(json.loads(line)["date"])
                except (json.JSONDecodeError, KeyError):
                    pass
        log(f"Resuming: {len(already_done)} days already scraped in {OUT_FILE}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        login(page, username, password)
        page.goto(TEESHEET_URL, wait_until="domcontentloaded")
        page.wait_for_selector(TIME_SLOT_PANEL_SEL, timeout=20000)

        current = start_date
        consecutive_failures = 0
        days_scraped = 0
        oldest_success = None
        last_login = time.monotonic()
        # The site logs out inactive sessions after ~38 min (see KillMePlease
        # timer on login.js); re-login well before that so a multi-hour scrape
        # doesn't silently die partway through.
        RELOGIN_INTERVAL_S = 15 * 60

        with open(OUT_FILE, "a") as out:
            for _ in range(args.max_days):
                date_key = current.isoformat()

                if date_key in already_done:
                    current -= datetime.timedelta(days=1)
                    continue

                if time.monotonic() - last_login > RELOGIN_INTERVAL_S:
                    log("Refreshing session (re-login) before it times out...")
                    login(page, username, password)
                    page.goto(TEESHEET_URL, wait_until="domcontentloaded")
                    page.wait_for_selector(TIME_SLOT_PANEL_SEL, timeout=20000)
                    last_login = time.monotonic()

                ok = go_to_date(page, current)
                if not ok:
                    consecutive_failures += 1
                    log(f"{date_key}: FAILED to load ({consecutive_failures} consecutive)")
                    if consecutive_failures >= args.consecutive_failures_to_stop:
                        log(f"Hit {consecutive_failures} consecutive failures at {date_key} — "
                            f"treating as historical boundary. Oldest successful date: {oldest_success}")
                        break
                    current -= datetime.timedelta(days=1)
                    time.sleep(args.delay)
                    continue

                consecutive_failures = 0
                slots = extract_day(page)
                record = {"date": date_key, "weekday": current.strftime("%A"), "slots": slots}
                out.write(json.dumps(record) + "\n")
                out.flush()
                days_scraped += 1
                oldest_success = date_key
                n_reserved = sum(1 for s in slots if s["parties"])
                n_blocked = sum(1 for s in slots if s["blocked_reason"])
                log(f"{date_key} ({record['weekday']}): {len(slots)} slots, "
                    f"{n_reserved} with reservations, {n_blocked} blocked")

                current -= datetime.timedelta(days=1)
                time.sleep(args.delay)

        browser.close()

    log(f"Done. Scraped {days_scraped} new days. Oldest successful date: {oldest_success}")


if __name__ == "__main__":
    main()
