"""
Trademark Search Backend API
================================
Flask server that scrapes QuickCompany.in and returns trademark data as JSON.

Deploy on:  Railway / Render / Fly.io / any VPS
GitHub:     Push this folder, connect to Railway/Render for free hosting

Endpoints:
  GET /api/search?q=Nike&mobile=9876543210
  GET /health

Install:
  pip install -r requirements.txt

Run locally:
  python app.py
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import time
import re
import hashlib
import json
import os
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────

BASE_URL      = "https://www.quickcompany.in"
SEARCH_URL    = f"{BASE_URL}/trademarks"
CACHE_TTL_HRS = 24          # cache results for 24 hours
MAX_PAGES     = 2           # pages to scrape per query (keep low to be polite)
REQUEST_DELAY = 1.5         # seconds between page requests

# Simple in-memory cache  {cache_key: {"data": [...], "expires": datetime}}
_cache = {}

SCRAPER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         BASE_URL,
}

# ─────────────────────────────────────────────
#  APP SETUP
# ─────────────────────────────────────────────

app = Flask(__name__)

# Allow requests from any origin (your WordPress site will call this)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ─────────────────────────────────────────────
#  CACHE HELPERS
# ─────────────────────────────────────────────

def cache_key(query: str) -> str:
    return hashlib.md5(query.strip().lower().encode()).hexdigest()

def cache_get(key: str):
    entry = _cache.get(key)
    if entry and datetime.utcnow() < entry["expires"]:
        return entry["data"]
    return None

def cache_set(key: str, data: list):
    _cache[key] = {
        "data":    data,
        "expires": datetime.utcnow() + timedelta(hours=CACHE_TTL_HRS),
    }

# ─────────────────────────────────────────────
#  SCRAPER
# ─────────────────────────────────────────────

def make_session():
    s = requests.Session()
    s.headers.update(SCRAPER_HEADERS)
    try:
        s.get(BASE_URL, timeout=10)   # grab cookies
    except Exception:
        pass
    return s


def fetch_page(session, query: str, page: int):
    try:
        resp = session.get(
            SEARCH_URL,
            params={"q": query, "page": page},
            timeout=12,
        )
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  [SCRAPER] fetch error page {page}: {e}")
        return None


def parse_cards(soup: BeautifulSoup) -> list:
    results = []

    # Try multiple selector patterns (site may use different layouts)
    cards = (
        soup.select("div.trademark-item")
        or soup.select("div.search-result-item")
        or soup.select("div.result-card")
        or soup.select("li.trademark-list-item")
    )

    # Fallback: grab all links pointing to /trademarks/<id>
    if not cards:
        links = soup.find_all("a", href=re.compile(r"/trademarks/\d+"))
        seen = set()
        for link in links:
            href = link.get("href", "")
            app_num = href.rstrip("/").split("/")[-1]
            if app_num in seen:
                continue
            seen.add(app_num)
            results.append({
                "title":              link.get_text(strip=True) or "—",
                "application_number": app_num,
                "status":             "—",
                "applicant":          "—",
                "class":              "—",
                "filing_date":        "—",
                "url":                BASE_URL + href if href.startswith("/") else href,
            })
        return results

    for card in cards:
        def txt(selectors):
            for sel in selectors:
                el = card.select_one(sel)
                if el:
                    return el.get_text(strip=True)
            return "—"

        link_el = card.select_one("a[href*='/trademarks/']")
        href    = link_el["href"] if link_el else ""
        url     = (BASE_URL + href) if href.startswith("/") else href

        app_num = href.rstrip("/").split("/")[-1] if href else "—"

        results.append({
            "title":              txt([".trademark-title", "h3", "h2", ".brand-name", "a"]),
            "application_number": txt([".application-number", ".tm-number", ".app-num"]) or app_num,
            "status":             txt([".trademark-status", ".status-badge", ".status", ".tm-status"]),
            "applicant":          txt([".applicant-name", ".owner", ".proprietor", ".applicant"]),
            "class":              txt([".trademark-class", ".class-number", ".tm-class"]),
            "filing_date":        txt([".filing-date", ".date-filed", ".application-date"]),
            "url":                url or "—",
        })

    return results


def scrape_trademarks(query: str) -> list:
    """Scrape up to MAX_PAGES of results for query. Uses cache."""
    key = cache_key(query)
    cached = cache_get(key)
    if cached is not None:
        print(f"  [CACHE HIT] '{query}'")
        return cached

    print(f"  [SCRAPING] '{query}'")
    session  = make_session()
    all_data = []
    seen_ids = set()

    for page in range(1, MAX_PAGES + 1):
        soup = fetch_page(session, query, page)
        if not soup:
            break

        cards = parse_cards(soup)
        if not cards:
            break

        for tm in cards:
            uid = tm.get("application_number", "") or tm.get("title", "")
            if uid and uid not in seen_ids:
                seen_ids.add(uid)
                all_data.append(tm)

        if page < MAX_PAGES:
            time.sleep(REQUEST_DELAY)

    cache_set(key, all_data)
    return all_data

# ─────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})


@app.route("/api/search")
def api_search():
    query  = request.args.get("q", "").strip()
    mobile = request.args.get("mobile", "").strip()

    # Basic validation
    if not query:
        return jsonify({"error": "Brand name is required."}), 400

    if not mobile or not re.match(r'^[0-9+\-\s]{7,15}$', mobile):
        return jsonify({"error": "A valid mobile number is required."}), 400

    # Optional: log leads to a file (mobile + query)
    log_lead(query, mobile)

    try:
        results = scrape_trademarks(query)
        return jsonify({
            "query":   query,
            "count":   len(results),
            "results": results,
            "cached":  bool(cache_get(cache_key(query))),
        })
    except Exception as e:
        print(f"  [ERROR] {e}")
        return jsonify({"error": "Search failed. Please try again later."}), 500


# ─────────────────────────────────────────────
#  LEAD LOGGING  (saves mobile + query to leads.json)
# ─────────────────────────────────────────────

LEADS_FILE = "leads.json"

def log_lead(query: str, mobile: str):
    """Append lead to leads.json file."""
    try:
        leads = []
        if os.path.exists(LEADS_FILE):
            with open(LEADS_FILE, "r") as f:
                leads = json.load(f)
        leads.append({
            "timestamp": datetime.utcnow().isoformat(),
            "brand":     query,
            "mobile":    mobile,
        })
        with open(LEADS_FILE, "w") as f:
            json.dump(leads, f, indent=2)
    except Exception as e:
        print(f"  [LEAD LOG ERROR] {e}")


@app.route("/api/leads")
def get_leads():
    """
    Admin endpoint to view collected leads.
    IMPORTANT: Add password protection before using in production!
    """
    secret = request.args.get("secret", "")
    admin_secret = os.environ.get("ADMIN_SECRET", "changeme123")

    if secret != admin_secret:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        if not os.path.exists(LEADS_FILE):
            return jsonify({"leads": [], "count": 0})
        with open(LEADS_FILE, "r") as f:
            leads = json.load(f)
        return jsonify({"leads": leads, "count": len(leads)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n✅  Trademark API running on http://localhost:{port}")
    print(f"   Test: http://localhost:{port}/api/search?q=Nike&mobile=9876543210\n")
    app.run(host="0.0.0.0", port=port, debug=False)