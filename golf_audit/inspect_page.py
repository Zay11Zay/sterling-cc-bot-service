"""
One-off diagnostic: log in and dump the full rendered HTML of a given page.
Used to inspect page structures (e.g. the member directory) before writing
a real scraper against them.

Usage:
    CLUB_USERNAME=... CLUB_PASSWORD=... python inspect_page.py <url> [out_file]
"""
import os
import sys

from playwright.sync_api import sync_playwright

from scraper import login

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "raw")


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: inspect_page.py <url> [out_file]")
    url = sys.argv[1]
    out_name = sys.argv[2] if len(sys.argv) > 2 else "page_dump.html"

    username = os.environ.get("CLUB_USERNAME")
    password = os.environ.get("CLUB_PASSWORD")
    if not username or not password:
        sys.exit("Set CLUB_USERNAME and CLUB_PASSWORD environment variables.")

    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, out_name)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        login(page, username, password)
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        html = page.content()
        with open(out_path, "w") as f:
            f.write(html)
        browser.close()

    print(f"Saved {len(html)} bytes to {out_path}")


if __name__ == "__main__":
    main()
