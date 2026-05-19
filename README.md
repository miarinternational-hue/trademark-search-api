# Trademark Search System

A live trademark search tool for your WordPress website.  
Scrapes QuickCompany.in and shows results + company details instantly.

---

## 📁 Files

| File | Purpose |
|------|---------|
| `app.py` | Python backend (Flask API) |
| `requirements.txt` | Python dependencies |
| `trademark-search-widget.html` | WordPress frontend widget |

---

## 🚀 Step 1 — Deploy Backend on Railway (Free)

1. Go to **https://railway.app** and sign up (free)
2. Click **New Project → Deploy from GitHub repo**
3. Push these files to a GitHub repo and connect it
4. Railway auto-detects Python and runs `gunicorn app:app`
5. Go to **Settings → Networking → Generate Domain**
6. Copy your URL e.g. `https://trademark-api-production.up.railway.app`

> **Alternative:** Use **Render.com** (also free) — same steps.

---

## ⚙️ Step 2 — Set Environment Variables (on Railway/Render)

| Variable | Value |
|----------|-------|
| `PORT` | `5000` |
| `ADMIN_SECRET` | Any secret password you choose |

---

## 🌐 Step 3 — Update the Widget

Open `trademark-search-widget.html` and find this line near the top of the `<script>`:

```js
const API_BASE = "https://YOUR-BACKEND-URL.com";  // ← change this!
```

Replace with your Railway/Render URL:

```js
const API_BASE = "https://trademark-api-production.up.railway.app";
```

---

## 🖥️ Step 4 — Add to WordPress

### Option A: HTML Block (Easiest)
1. Edit any WordPress page
2. Add a new block → search **"Custom HTML"**
3. Paste the entire contents of `trademark-search-widget.html`
4. Publish

### Option B: Elementor / Divi
1. Add an **HTML widget**
2. Paste the widget code
3. Save

### Option C: Child Theme (Best for performance)
1. Save `trademark-search-widget.html` content into your child theme
2. Include via `<?php include get_stylesheet_directory() . '/trademark-widget.html'; ?>`

---

## 🔍 API Endpoints

### Search Trademarks
```
GET /api/search?q=Nike&mobile=9876543210
```
**Response:**
```json
{
  "query": "Nike",
  "count": 3,
  "results": [
    {
      "title": "NIKE",
      "application_number": "1234567",
      "status": "Registered",
      "applicant": "Nike Inc.",
      "class": "25",
      "filing_date": "15/03/2010",
      "url": "https://www.quickcompany.in/trademarks/1234567"
    }
  ]
}
```

### View Collected Leads
```
GET /api/leads?secret=YOUR_ADMIN_SECRET
```

### Health Check
```
GET /health
```

---

## 💡 Features

- ✅ Live scraping from QuickCompany.in
- ✅ 24-hour caching (same search = instant result)
- ✅ Lead collection (saves mobile number + brand name)
- ✅ Status badges: Registered / Pending / Objected / Abandoned
- ✅ Shows: Owner, Class, Filing Date, Application No.
- ✅ Links back to QuickCompany for full details
- ✅ Matches your existing website design

---

## 🛠️ Run Locally (for testing)

```bash
pip install -r requirements.txt
python app.py
# Visit: http://localhost:5000/api/search?q=Nike&mobile=9876543210
```

---

## ⚠️ Notes

- QuickCompany may require login for full results. If results are empty, you may need to add browser cookies to `SCRAPER_HEADERS` in `app.py`.
- Be respectful — don't set `MAX_PAGES` too high. Default is 2 pages per search.
- Leads are saved to `leads.json` on the server. Export via the `/api/leads` endpoint.
