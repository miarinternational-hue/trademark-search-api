"""
Trademark Search Backend API - Full Detail Scraper
====================================================
Scrapes QuickCompany.in search results AND visits each detail page
to get full info: applicant, status, class, filing date, etc.
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
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────

BASE_URL      = "https://www.quickcompany.in"
SEARCH_URL    = f"{BASE_URL}/trademarks"
CACHE_TTL_HRS = 24
MAX_PAGES     = 2
REQUEST_DELAY = 1.0
MAX_DETAIL_WORKERS = 5   # parallel detail page fetches

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

_cache = {}

# ─────────────────────────────────────────────
#  APP
# ─────────────────────────────────────────────

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ─────────────────────────────────────────────
#  CACHE
# ─────────────────────────────────────────────

def cache_key(q):
    return hashlib.md5(q.strip().lower().encode()).hexdigest()

def cache_get(key):
    e = _cache.get(key)
    if e and datetime.utcnow() < e["expires"]:
        return e["data"]
    return None

def cache_set(key, data):
    _cache[key] = {"data": data, "expires": datetime.utcnow() + timedelta(hours=CACHE_TTL_HRS)}

# ─────────────────────────────────────────────
#  SESSION
# ─────────────────────────────────────────────

def make_session():
    s = requests.Session()
    s.headers.update(SCRAPER_HEADERS)
    try:
        s.get(BASE_URL, timeout=10)
    except:
        pass
    return s

# ─────────────────────────────────────────────
#  SEARCH PAGE SCRAPER
# ─────────────────────────────────────────────

def fetch_search_page(session, query, page):
    try:
        resp = session.get(SEARCH_URL, params={"q": query, "page": page}, timeout=12)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  [SEARCH ERROR] page {page}: {e}")
        return None


def parse_search_results(soup):
    """Extract trademark links and basic info from search results page."""
    results = []

    # Try to find trademark links pointing to detail pages
    links = soup.find_all("a", href=re.compile(r"/trademarks/[a-zA-Z0-9\-]+"))
    seen = set()

    for link in links:
        href = link.get("href", "")
        # Skip pagination, category links etc
        slug = href.rstrip("/").split("/")[-1]
        if not slug or slug in ("trademarks", "search") or slug in seen:
            continue
        # Only include if slug looks like a trademark (has letters)
        if not re.search(r'[a-zA-Z]', slug) and not re.search(r'\d{5,}', slug):
            continue
        seen.add(slug)

        full_url = BASE_URL + href if href.startswith("/") else href

        # Try to get title from link text or nearby heading
        title = link.get_text(strip=True)
        if not title or len(title) < 2:
            parent = link.parent
            if parent:
                title = parent.get_text(strip=True)[:60]

        results.append({
            "title": title or slug.replace("-", " ").title(),
            "url":   full_url,
            "slug":  slug,
        })

    return results

# ─────────────────────────────────────────────
#  DETAIL PAGE SCRAPER
# ─────────────────────────────────────────────

def fetch_detail(session, tm):
    """Visit the trademark detail page and extract full info."""
    url = tm.get("url", "")
    if not url:
        return tm

    try:
        time.sleep(0.3)
        resp = session.get(url, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        def find_value(labels):
            """Find a value near a label text on the page."""
            for label_text in labels:
                # Method 1: look for dt/dd pairs
                for dt in soup.find_all(["dt", "th", "label", "strong", "b"]):
                    if label_text.lower() in dt.get_text(strip=True).lower():
                        sibling = dt.find_next_sibling(["dd", "td", "span", "p"])
                        if sibling:
                            val = sibling.get_text(strip=True)
                            if val and len(val) > 0:
                                return val
                # Method 2: look for divs with matching class or text
                for el in soup.find_all(["div", "span", "p", "td"]):
                    text = el.get_text(strip=True)
                    if label_text.lower() in text.lower() and len(text) < 80:
                        next_el = el.find_next_sibling()
                        if next_el:
                            val = next_el.get_text(strip=True)
                            if val and 1 < len(val) < 200:
                                return val
            return "—"

        # Extract trademark name / title
        title_el = (
            soup.select_one("h1")
            or soup.select_one("h2")
            or soup.select_one(".trademark-name")
            or soup.select_one(".brand-name")
        )
        title = title_el.get_text(strip=True) if title_el else tm.get("title", "—")

        # Application number — often in URL slug or on page
        app_slug = tm.get("slug", "")
        app_num_match = re.search(r'\d{5,}', app_slug)
        app_num = app_num_match.group(0) if app_num_match else app_slug

        # Look for structured data on detail page
        status      = find_value(["status", "trademark status", "current status"])
        applicant   = find_value(["applicant", "owner", "proprietor", "filed by"])
        tm_class    = find_value(["class", "nice class", "trademark class", "goods & services"])
        filing_date = find_value(["filing date", "application date", "date of filing", "filed on"])
        description = find_value(["goods & services", "description", "specification"])

        # Try meta tags too
        for meta in soup.find_all("meta"):
            content = meta.get("content", "")
            name    = meta.get("name", "") + meta.get("property", "")
            if "applicant" in name.lower() and applicant == "—":
                applicant = content
            if "status" in name.lower() and status == "—":
                status = content
            if "class" in name.lower() and tm_class == "—":
                tm_class = content

        # Try JSON-LD structured data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict):
                    if applicant == "—" and data.get("applicant"):
                        applicant = str(data["applicant"])
                    if status == "—" and data.get("status"):
                        status = str(data["status"])
                    if filing_date == "—" and data.get("filingDate"):
                        filing_date = str(data["filingDate"])
            except:
                pass

        tm.update({
            "title":              title,
            "application_number": app_num or app_slug,
            "status":             status,
            "applicant":          applicant,
            "class":              tm_class,
            "filing_date":        filing_date,
            "description":        description if description != "—" else "",
            "url":                url,
        })

    except Exception as e:
        print(f"  [DETAIL ERROR] {url}: {e}")
        tm.setdefault("application_number", tm.get("slug", "—"))
        tm.setdefault("status", "—")
        tm.setdefault("applicant", "—")
        tm.setdefault("class", "—")
        tm.setdefault("filing_date", "—")

    return tm


# ─────────────────────────────────────────────
#  MAIN SCRAPER
# ─────────────────────────────────────────────

def scrape_trademarks(query):
    key    = cache_key(query)
    cached = cache_get(key)
    if cached is not None:
        print(f"  [CACHE HIT] '{query}'")
        return cached

    print(f"  [SCRAPING] '{query}'")
    session  = make_session()
    all_tms  = []
    seen_url = set()

    # Step 1: collect all trademark URLs from search pages
    for page in range(1, MAX_PAGES + 1):
        print(f"    Search page {page}...")
        soup = fetch_search_page(session, query, page)
        if not soup:
            break

        results = parse_search_results(soup)
        if not results:
            print(f"    No results on page {page}, stopping.")
            break

        for tm in results:
            if tm["url"] not in seen_url:
                seen_url.add(tm["url"])
                all_tms.append(tm)

        if page < MAX_PAGES:
            time.sleep(REQUEST_DELAY)

    print(f"    Found {len(all_tms)} trademarks. Fetching details...")

    # Step 2: fetch detail pages in parallel (max 5 at a time)
    enriched = []
    with ThreadPoolExecutor(max_workers=MAX_DETAIL_WORKERS) as executor:
        futures = {executor.submit(fetch_detail, session, tm): tm for tm in all_tms}
        for future in as_completed(futures):
            try:
                enriched.append(future.result())
            except Exception as e:
                print(f"  [THREAD ERROR] {e}")
                enriched.append(futures[future])

    # Deduplicate by application number
    seen_ids = set()
    final = []
    for tm in enriched:
        uid = tm.get("application_number", "") or tm.get("url", "")
        if uid and uid not in seen_ids:
            seen_ids.add(uid)
            final.append(tm)

    cache_set(key, final)
    print(f"    Done. {len(final)} unique trademarks.")
    return final


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

    if not query:
        return jsonify({"error": "Brand name is required."}), 400
    if not mobile or not re.match(r'^[0-9+\-\s]{7,15}$', mobile):
        return jsonify({"error": "A valid mobile number is required."}), 400

    log_lead(query, mobile)

    try:
        results = scrape_trademarks(query)
        return jsonify({
            "query":   query,
            "count":   len(results),
            "results": results,
        })
    except Exception as e:
        print(f"  [ERROR] {e}")
        return jsonify({"error": "Search failed. Please try again later."}), 500


# ─────────────────────────────────────────────
#  LEAD LOGGING
# ─────────────────────────────────────────────

LEADS_FILE = "leads.json"

def log_lead(query, mobile):
    try:
        leads = []
        if os.path.exists(LEADS_FILE):
            with open(LEADS_FILE, "r") as f:
                leads = json.load(f)
        leads.append({"timestamp": datetime.utcnow().isoformat(), "brand": query, "mobile": mobile})
        with open(LEADS_FILE, "w") as f:
            json.dump(leads, f, indent=2)
    except Exception as e:
        print(f"  [LEAD LOG ERROR] {e}")


@app.route("/api/leads")
def get_leads():
    secret       = request.args.get("secret", "")
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
    print(f"\n✅  Trademark API running on http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)