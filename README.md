# NHL Jersey Clearance Bot

> Built by a San Jose Sharks fan who missed out on a Patrick Marleau Premier jersey
> because by the time the Reddit thread surfaced the deal, only youth sizes were left.
> Never again.

Monitors the [Fanatics NHL clearance page](https://www.fanatics.com/nhl/jerseys-sale-items/o-3539+d-08662378+os-90+z-9162-596540854) every 6 hours and sends a Gmail notification the moment clearance jerseys appear for a watched team in a target category. No more checking Reddit. No more showing up late.

---

## How it works

1. **GitHub Actions** runs `main.py` on a cron schedule (every 6 hours by default).
2. **ScraperAPI** fetches the Fanatics clearance listing page through a residential IP, bypassing Fanatics' Akamai bot protection.
3. **BeautifulSoup** parses the HTML and extracts product cards using Fanatics' confirmed CSS selectors.
4. Products are classified by team and jersey type against rules in `config.yaml`.
5. A **state machine** per `(team, jersey_type)` pair decides whether to send an email:
   - `NOT_SEEN` → jerseys found → send email → `NOTIFIED`
   - `NOTIFIED` → jerseys gone → `NOT_SEEN` (resets; next appearance re-triggers)
6. `state.json` is committed back to the repo after each run to persist state across Actions runs.

```
NOT_SEEN ──( jerseys appear )──▶ NOTIFIED ──( jerseys gone )──▶ NOT_SEEN
              email sent here                  re-arm for next window
```

One email per availability window per category. No spam, no re-alerts while the same jerseys are still listed.

---

## Tech stack

| Component | Technology | Why |
|---|---|---|
| HTTP fetch | [ScraperAPI](https://scraperapi.com) | Routes requests through residential IPs, bypassing Fanatics' Akamai WAF which blocks all datacenter/cloud IPs (GitHub Actions, Vercel, etc.) |
| HTML parsing | [BeautifulSoup4](https://pypi.org/project/beautifulsoup4/) + lxml | Lightweight, no browser required; Fanatics serves SSR HTML so a real browser is unnecessary |
| Scheduling | [GitHub Actions](https://docs.github.com/en/actions) cron | Free (2,000 min/month included), always-on, no server to manage |
| Notifications | Python `smtplib` + Gmail SMTP | Zero cost, no third-party service required |
| State | `state.json` committed to the repo | Free, auditable, survives workflow restarts |
| Config | `config.yaml` | All tunable behaviour in one place; no code changes needed for common updates |
| Language | Python 3.11 | Standard library covers email; minimal dependencies |

**Why not Playwright / headless browser?** Fanatics uses Akamai Bot Manager which blocks datacenter IP ranges outright — the browser never even loads. ScraperAPI solves this at the network level.

**Why not scrape directly?** GitHub Actions, Vercel, Render, and all major free cloud platforms use datacenter IP ranges that Akamai flags automatically. A residential proxy (ScraperAPI) is the only reliable free-tier solution.

---

## Scraping approach

ScraperAPI fetches the Fanatics clearance URL and returns the server-rendered HTML. BeautifulSoup then parses it using these confirmed Fanatics CSS selectors:

| Data | Selector |
|---|---|
| Product card | `div.product-card` |
| Name + link | `div.product-card-title a` |
| Sale price | `span.lowest span.money-value` |
| Original price | `span.strike-through span.money-value` |

> **Note on sizes:** Fanatics does not show size availability on the listing page — only on individual product pages. The bot therefore alerts on any matching jersey regardless of size. The product link in the notification email goes straight to the product page where you can confirm your size is in stock before buying.

---

## Jersey categories

Fanatics sells NHL jerseys in several tiers. The bot currently watches:

| Category | Enabled | Fanatics product keywords | Typical retail price |
|---|---|---|---|
| **Authentic** | yes | "Authentic", "Adidas Authentic", "Primegreen", "Primeblue" | ~$220–250 |
| **Premier** | yes | "Premier", "Reebok Premier", "Premium" | ~$120–170 |
| **Practice** | yes | "Practice" | ~$60–100 |
| Breakaway | no | "Breakaway", "Replica" | ~$90–120 |

> **Why "Premium" is under Premier:** Fanatics replaced the old Reebok "Premier" jersey with their own "Fanatics Premium" mid-tier jersey. The product titles on the site say "Premium", not "Premier", so both keywords are needed to catch the full range.

A jersey title is matched against each category's `keywords` list (case-insensitive). If no keyword matches, a price-based fallback classifies anything over `min_original_price` (set in `config.yaml`) as Authentic.

To enable Breakaway alerts, set `breakaway.enabled: true` in `config.yaml`.

---

## One-time setup

### 1. Clone and create a private GitHub repo

Keep the repo **private** — it contains your notification email address.

### 2. Create a ScraperAPI account

Sign up at [scraperapi.com](https://scraperapi.com) — the free plan includes 1,000 API credits/month. This bot uses ~720 credits/month (24 checks/day × 30 days) with one fallback render credit if needed. No credit card required for the free tier.

Your API key is on the ScraperAPI dashboard immediately after signup.

### 3. Create a Gmail App Password

Google disabled plain-password SMTP in 2022. An App Password is a 16-character code your Google account generates for a single app — separate from your main password, revocable at any time.

Go directly to **https://myaccount.google.com/apppasswords** (2-Step Verification must be enabled first), name it "jersey-bot", and click Generate.

### 4. Add secrets to GitHub

Go to your repo → **Settings → Secrets and variables → Actions** and add two repository secrets:

| Secret name | Value |
|---|---|
| `SCRAPERAPI_KEY` | Your ScraperAPI API key |
| `GMAIL_APP_PASSWORD` | The 16-character Gmail app password |

GitHub Secrets are encrypted at rest, never shown in workflow logs, and not exposed to forks.

### 5. Install locally (optional, for testing)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

---

## Running locally

```bash
# Normal run (sends email if jerseys found, updates state.json)
SCRAPERAPI_KEY=your_key GMAIL_APP_PASSWORD=your_password python main.py

# Dry-run: scrape only, no email, state.json unchanged
python main.py --dry-run

# Debug: writes debug_page.html for selector inspection
python main.py --debug --dry-run

# Use a different config file
python main.py --config my_other_config.yaml
```

---

## Triggering a debug run on GitHub Actions

The workflow has a manual debug mode that saves the raw page HTML without sending any emails or modifying state:

1. Go to **Actions → NHL Jersey Check → Run workflow**
2. Set the **debug** dropdown to `true`
3. Click **Run workflow**

When the run finishes, an **Artifacts** section appears at the bottom of the run page with a downloadable `fanatics-debug.zip` containing `debug_page.html`. Open it in a browser or text editor to inspect the page structure.

---

## Configuration reference (`config.yaml`)

### Adding a team

```yaml
watch_teams:
  - name: "San Jose Sharks"
    notify: true
  - name: "Florida Panthers"
    notify: false
  # Add any NHL team name exactly as it appears in Fanatics product titles:
  - name: "Toronto Maple Leafs"
    notify: true
```

Set `notify: false` to track a team in state without receiving emails — useful for staging a new team before turning alerts on.

### Adding a jersey category

```yaml
jersey_categories:
  fanatics_premium:
    enabled: true
    keywords:
      - "Fanatics Premium"
```

### Adding or removing exclusions

Products whose titles contain any of these keywords are silently dropped. Current exclusions:

```yaml
exclude_keywords:
  - "Youth"       # youth/kids jerseys
  - "Kids"
  - "Toddler"
  - "Infant"
  - "Preschool"
  - "Girls"
  - "Boys"
  - "Child"
  - "Women"       # women's cut jerseys (different sizing)
```

To stop excluding a category, remove the keyword. To add one (e.g. "Womens" variants), append it to the list.

### Enabling Breakaway alerts

```yaml
jersey_categories:
  breakaway:
    enabled: true   # was false
```

### Changing the polling interval

Edit the cron expression in `.github/workflows/check.yml`:

```yaml
- cron: '0 */6 * * *'        # every 6 hours (default)
- cron: '0 * * * *'          # every hour
- cron: '0 */6 * * *'        # every 6 hours
- cron: '0 */4 * * *'        # every 4 hours
- cron: '0 8,14,20 * * *'    # 8 am, 2 pm, 8 pm UTC
```

GitHub Actions free-tier cron jobs may be delayed a few minutes during high-traffic periods.

---

## Extending to other product types (T-shirts, hoodies, etc.)

The architecture monitors any Fanatics clearance URL. To add T-shirt or hoodie tracking:

1. Find the Fanatics clearance URL for that category.
2. Add it to `config.yaml` or create a separate config file.
3. Add category keywords under `jersey_categories`.
4. If using a separate config, add a step in `check.yml`:

```yaml
- name: Run apparel bot
  env:
    SCRAPERAPI_KEY: ${{ secrets.SCRAPERAPI_KEY }}
    GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
  run: python main.py --config config_apparel.yaml
```

---

## File structure

```
nhl-jersey-bot/
├── .github/
│   └── workflows/
│       └── check.yml       GitHub Actions workflow (scheduling, debug mode, artifact upload)
├── bot/
│   ├── __init__.py
│   ├── models.py           Jersey dataclass
│   ├── scraper.py          ScraperAPI fetch + BeautifulSoup parsing
│   ├── notifier.py         Gmail SMTP email sender
│   └── state.py            Per-(team, category) notification state machine
├── config.yaml             All tunable parameters — teams, categories, sizes, email
├── state.json              Persisted run-to-run notification state (auto-committed by bot)
├── main.py                 Orchestrator / entry point
├── requirements.txt
└── README.md
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `SCRAPERAPI_KEY not set` error | Secret missing from repo | Add `SCRAPERAPI_KEY` in repo Settings → Secrets |
| 0 jerseys found, page is ~600 chars | Akamai block got through (rare) | Retry; ScraperAPI rotates IPs automatically |
| 0 jerseys found, page is 1MB+ | Fanatics updated their CSS class names | Trigger a debug run, download `debug_page.html`, search for product name text to find the new selector, update `scraper.py` |
| Email not sent | `GMAIL_APP_PASSWORD` wrong or missing | Verify the secret in repo Settings → Secrets |
| Notification not firing | Jerseys were already seen on a previous run | Check `state.json`; delete the relevant `NOTIFIED` entry and commit to force a fresh check |
| Push rejected after a run | Bot committed `state.json` while you were working locally | Run `git pull --rebase` then push |
| GitHub Actions not triggering on schedule | Repo marked inactive | Visit the Actions tab to re-enable; GitHub pauses cron jobs on repos with no activity for 60 days |
