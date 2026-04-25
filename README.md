# NHL Jersey Clearance Bot

> Built by a San Jose Sharks fan who missed out on a Patrick Marleau Premier jersey
> because by the time the Reddit thread surfaced the deal, only youth sizes were left.
> Never again.

Monitors the [Fanatics NHL clearance page](https://www.fanatics.com/nhl/jerseys-sale-items/o-3539+d-08662378+os-90+z-9162-596540854) every 6 hours and sends a Gmail notification the moment clearance jerseys appear for a watched team in a target category and size. No more checking Reddit. No more showing up late.

---

## How it works

1. **GitHub Actions** runs `main.py` on a cron schedule (every 6 hours by default).
2. **Playwright** (headless Chromium) loads the Fanatics clearance listing page.
3. Products are classified by team, jersey type, and size against rules in `config.yaml`.
4. A **state machine** per `(team, jersey_type)` pair decides whether to send an email:
   - `NOT_SEEN` → jerseys found → send email → `NOTIFIED`
   - `NOTIFIED` → jerseys gone → `NOT_SEEN` (resets; next appearance re-triggers)
5. `state.json` is committed back to the repo after each run to persist this state across Actions runs.

```
NOT_SEEN ──( jerseys appear )──▶ NOTIFIED ──( jerseys gone )──▶ NOT_SEEN
              email sent here                  re-arm for next window
```

One email per availability window per category. No spam, no re-alerts while the same jerseys are still sitting there.

---

## Tech stack

| Component | Technology | Why |
|---|---|---|
| Scraping | [Playwright](https://playwright.dev/python/) (headless Chromium) | Fanatics is a JavaScript SPA; a real browser is required to get fully rendered product listings |
| Anti-detection | [playwright-stealth](https://pypi.org/project/playwright-stealth/) | Patches `navigator.webdriver` and ~20 other browser fingerprint signals that bot-detection systems check |
| Scheduling | [GitHub Actions](https://docs.github.com/en/actions) cron | Free (2,000 min/month included), always-on, no server to manage |
| Notifications | Python `smtplib` + Gmail SMTP | Zero cost, no third-party service required |
| State | `state.json` committed to the repo | Free, auditable, survives workflow restarts |
| Config | `config.yaml` | All tunable behaviour in one place; no code changes needed for common updates |
| Language | Python 3.11 | Standard library covers email; Playwright has a first-class Python binding |

Everything is free. No paid services, no credit card required.

---

## Scraping strategy

The scraper tries three approaches in order and uses the first that returns results:

1. **API interception** — Playwright intercepts JSON network responses fired during page load. Fanatics fetches product data via an internal API; capturing that payload directly avoids brittle CSS selectors and survives layout redesigns.
2. **`__NEXT_DATA__`** — If the page uses Next.js SSR, the full product list is embedded as JSON in a `<script id="__NEXT_DATA__">` tag.
3. **DOM scraping** — Multiple CSS-selector strategies tried in sequence against the rendered HTML.

### Anti-scraping measures

- **playwright-stealth** patches the most common headless browser fingerprints
- **Realistic browser headers** — Chrome 124 User-Agent, `Accept-Language: en-US`, Eastern timezone
- **Human-like delays** — random 1.5–3.5s pause before page interaction; random scroll speed
- **Scroll-to-load** — slowly scrolls the full page to trigger lazy-loaded product cards
- **Cookie banner dismissal** — automatically clicks "Accept" on consent banners that would otherwise block content

At 4 requests/day the bot is far below any rate-limit threshold.

---

## Jersey categories

Fanatics sells NHL jerseys in several tiers. The bot currently watches:

| Category | Enabled | Fanatics product keywords | Typical retail price |
|---|---|---|---|
| **Authentic** | yes | "Authentic", "Adidas Authentic", "Primegreen", "Primeblue" | ~$220–250 |
| **Premier** | yes | "Premier", "Reebok Premier" | ~$130–160 |
| **Practice** | yes | "Practice" | ~$60–100 |
| Breakaway | no | "Breakaway", "Replica" | ~$120 |

A jersey title is matched against each category's `keywords` list (case-insensitive). If no keyword matches, a price-based fallback classifies anything over `min_original_price` (set in `config.yaml`) as Authentic.

To enable Breakaway alerts, set `breakaway.enabled: true` in `config.yaml`.

### A note on Authentic and Premier jersey sizing

Authentic NHL jerseys use **numeric sizing**, not S/M/L/XL:

| Numeric | Approximate fit |
|---|---|
| 48 | Men's Small |
| 50 | Men's Medium |
| **52** | **Men's Large (fitted)** |
| **54** | **Men's Large/XL (relaxed)** |
| 56 | Men's XXL |

Practice and Breakaway jerseys use standard S/M/L/XL. The bot searches both `standard` and `numeric` size lists from `config.yaml`, so a single run covers both jersey styles.

---

## One-time setup

### 1. Clone and create a private GitHub repo

Keep the repo **private** — it contains your notification email address.

```bash
git clone https://github.com/YOUR_USERNAME/nhl-jersey-bot.git
cd nhl-jersey-bot
```

### 2. Create a Gmail App Password

Google disabled plain-password SMTP in 2022. An App Password is a 16-character code your Google account generates for a single app — separate from your main password, revocable at any time.

1. Go directly to **https://myaccount.google.com/apppasswords** (the Security page navigation can be unreliable).
2. 2-Step Verification must be enabled on your account first.
3. Name it "jersey-bot" and click **Generate**.
4. Copy the 16-character code — you will not see it again.

### 3. Add the App Password as a GitHub Secret

1. Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `GMAIL_APP_PASSWORD`
3. Value: the 16-character code.

GitHub Secrets are encrypted at rest, never shown in workflow logs, and not exposed to forks. They are safe for credentials like this.

### 4. Install locally (optional, for testing)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

---

## Running locally

```bash
# Normal run (sends email if jerseys found, updates state.json)
GMAIL_APP_PASSWORD=your_app_password python main.py

# Dry-run: scrape only, no email, state.json unchanged
python main.py --dry-run

# Debug: writes debug_screenshot.png, debug_page.html, debug_api_responses.json
python main.py --debug --dry-run

# Use a different config file
python main.py --config my_other_config.yaml
```

---

## Triggering a debug run on GitHub Actions

The workflow has a manual **debug mode** that saves page artifacts without sending any emails or modifying state:

1. Go to **Actions → NHL Jersey Check → Run workflow**
2. Set the **debug** dropdown to `true`
3. Click **Run workflow**

When the run finishes, an **Artifacts** section appears at the bottom of the run page with a downloadable `fanatics-debug.zip` containing:
- `debug_screenshot.png` — what the browser actually rendered
- `debug_page.html` — the full rendered HTML (useful for finding correct CSS selectors)
- `debug_api_responses.json` — all JSON the page fetched from Fanatics' backend API

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
  # existing entries …
  fanatics_branded:
    enabled: true
    keywords:
      - "Fanatics Branded"
      - "Breakaway"
```

### Changing target sizes

```yaml
target_sizes:
  standard:
    - "L"
    - "XL"
    - "XXL"   # add as needed
  numeric:
    - "52"
    - "54"
    - "56"    # add as needed
```

### Changing the polling interval

Edit the cron expression in `.github/workflows/check.yml`:

```yaml
- cron: '0 */6 * * *'        # every 6 hours
- cron: '0 */4 * * *'        # every 4 hours
- cron: '0 8,14,20 * * *'    # 8 am, 2 pm, 8 pm UTC
```

GitHub Actions free-tier cron jobs may be delayed a few minutes during high-traffic periods.

---

## Extending to other product types (T-shirts, hoodies, etc.)

The architecture supports monitoring any product category on Fanatics. To add T-shirt or hoodie clearance tracking:

1. Find the Fanatics clearance URL for that category and add it to `config.yaml` (or a separate config file).
2. Add category keywords under `jersey_categories` — the key name is arbitrary.
3. If using a separate config, add a step in `check.yml`:

```yaml
- name: Run apparel bot
  env:
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
│   ├── scraper.py          Playwright scraper with stealth, scroll, cookie dismissal
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
| No jerseys found | Fanatics changed their page structure | Trigger a debug run (see above); inspect `debug_page.html` and `debug_api_responses.json` to find the correct selectors, then update `scraper.py` |
| Email not sent | `GMAIL_APP_PASSWORD` secret missing or wrong | Verify the secret in repo Settings → Secrets |
| Notification not firing | Jerseys were already seen on a previous run | Check `state.json`; if the team/category shows `"NOTIFIED"`, those jerseys are still listed. Delete that key in `state.json` and commit to force a fresh check |
| GitHub Actions not triggering on schedule | Repo may have been marked inactive | Visit the Actions tab and re-enable workflows; GitHub pauses cron jobs on repos with no activity for 60 days |
| Push rejected after a run | Bot committed `state.json` while you were working locally | Run `git pull --rebase` then push |
