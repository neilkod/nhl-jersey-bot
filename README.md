# NHL Jersey Clearance Bot

Monitors the [Fanatics NHL clearance page](https://www.fanatics.com/nhl/jerseys-sale-items/o-3539+d-08662378+os-90+z-9162-596540854) every 6 hours and sends a Gmail notification when clearance jerseys appear for a watched team in a target category and size.

---

## How it works

1. **GitHub Actions** runs `main.py` on a cron schedule (every 6 hours by default).
2. **Playwright** (headless Chromium) loads the Fanatics clearance listing page.
3. Products are classified by team, jersey type, and size against rules in `config.yaml`.
4. A **state machine** per `(team, jersey_type)` pair decides whether to send an email:
   - `NOT_SEEN` → jerseys found → send email → `NOTIFIED`
   - `NOTIFIED` → jerseys gone → `NOT_SEEN` (reset; next appearance re-triggers)
5. `state.json` is committed back to the repo after each run to persist this state across Actions runs.

```
NOT_SEEN ──( jerseys appear )──▶ NOTIFIED ──( jerseys gone )──▶ NOT_SEEN
              email sent here                  re-arm for next window
```

---

## Tech stack

| Component | Technology | Why |
|---|---|---|
| Scraping | [Playwright](https://playwright.dev/python/) (headless Chromium) | Fanatics is a JavaScript SPA; a real browser is required to get fully rendered product listings |
| Scheduling | [GitHub Actions](https://docs.github.com/en/actions) cron | Free (2,000 min/month included), always-on, no server to manage |
| Notifications | Python `smtplib` + Gmail SMTP | Zero cost, no third-party service required |
| State | `state.json` committed to the repo | Free, auditable, survives workflow restarts |
| Config | `config.yaml` | All tunable behaviour in one place; no code changes needed for common updates |
| Language | Python 3.11 | Standard library covers email; Playwright has a first-class Python binding |

---

## Scraping strategy

The scraper tries three approaches in order and uses the first that returns results:

1. **API interception** — Playwright intercepts JSON network responses fired during page load. Fanatics fetches product data via an internal API; this captures that payload directly and avoids brittle CSS selectors.
2. **`__NEXT_DATA__`** — If the page uses Next.js SSR, the full product list is often embedded as JSON in a `<script id="__NEXT_DATA__">` tag.
3. **DOM scraping** — Multiple CSS-selector strategies tried in sequence against the rendered HTML.

If Fanatics redesigns their site and the bot stops returning results, run `python main.py --debug` to produce `debug_screenshot.png`, `debug_page.html`, and `debug_api_responses.json` for inspection.

---

## Jersey categories

Fanatics sells NHL jerseys in several tiers. The bot currently recognises:

| Category | Enabled | Fanatics product keywords | Typical retail price |
|---|---|---|---|
| **Authentic** | yes | "Authentic", "Adidas Authentic", "Primegreen", "Primeblue" | ~$220–250 |
| **Premier** | yes | "Premier", "Reebok Premier" | ~$130–160 |
| **Practice** | yes | "Practice" | ~$60–100 |
| Breakaway | no | "Breakaway", "Replica" | ~$120 |

A jersey title is matched against each category's `keywords` list (case-insensitive). If no keyword matches, an Authentic/Premier fallback classification fires based on `min_original_price` in `config.yaml`.

To enable Breakaway alerts, set `breakaway.enabled: true` in `config.yaml`.

### A note on Authentic jersey sizing

Authentic NHL jerseys use **numeric sizing**, not S/M/L/XL:

| Numeric | Approximate fit |
|---|---|
| 48 | Men's Small |
| 50 | Men's Medium |
| **52** | **Men's Large (fitted)** |
| **54** | **Men's Large/XL (relaxed)** |
| 56 | Men's XXL |

Practice and Breakaway jerseys use standard S/M/L/XL. The bot searches for both `standard` and `numeric` size lists configured in `config.yaml`.

---

## One-time setup

### 1. Fork / clone and create a private GitHub repo

Keep the repo **private**; it contains your notification email address.

```bash
git clone https://github.com/YOUR_USERNAME/nhl-jersey-bot.git
cd nhl-jersey-bot
```

### 2. Create a Gmail App Password

Google disabled plain-password SMTP in 2022. An App Password is a separate 16-character credential your Google account generates for a single app. It is not your main password and can be revoked at any time without affecting your account.

Steps:
1. Sign in to [myaccount.google.com](https://myaccount.google.com).
2. Navigate to **Security → 2-Step Verification** (must be enabled).
3. Scroll to **App passwords** and click it.
4. Name it "jersey-bot", leave app/device as "Mail", and click **Generate**.
5. Copy the 16-character code — you will not see it again.

### 3. Add the App Password as a GitHub Secret

1. Go to your repo on GitHub → **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `GMAIL_APP_PASSWORD`
3. Value: the 16-character code from the previous step.

GitHub Secrets are encrypted at rest, never shown in workflow logs, and not exposed to forks of the repo. They are safe for credentials like this.

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
# Normal run (sends email if jerseys found)
GMAIL_APP_PASSWORD=your_app_password python main.py

# Dry-run: scrape only, no email sent, state.json not modified
python main.py --dry-run

# Debug: writes debug_screenshot.png, debug_page.html, debug_api_responses.json
python main.py --debug --dry-run

# Use a different config file
python main.py --config my_other_config.yaml
```

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

Set `notify: false` to track a team in state without receiving emails (useful staging before turning on alerts).

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
    - "XXL"   # ← add as needed
  numeric:
    - "52"
    - "54"
    - "56"    # ← add as needed
```

### Changing the polling interval

Edit the cron expression in `.github/workflows/check.yml`:

```yaml
- cron: '0 */6 * * *'   # every 6 hours
- cron: '0 */4 * * *'   # every 4 hours
- cron: '0 8,14,20 * * *'  # 8 am, 2 pm, 8 pm UTC
```

Note: GitHub Actions free-tier cron jobs may be delayed by a few minutes during high-traffic periods.

---

## Extending to other product types (e.g., T-shirts, hoodies)

The architecture supports monitoring any product category on Fanatics, not just jerseys. The steps to add T-shirt/hoodie clearance tracking are:

1. Find the Fanatics clearance URL for that category and add it to `config.yaml` (or create a second config file).
2. Add category keywords for the new product type under `jersey_categories` (the key name is arbitrary).
3. Add the team/size rules you want.
4. If using a separate config, add a second step in `check.yml` pointing to it:

```yaml
- name: Run hoodie bot
  env:
    GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
  run: python main.py --config config_hoodies.yaml
```

---

## File structure

```
nhl-jersey-bot/
├── .github/
│   └── workflows/
│       └── check.yml       GitHub Actions workflow (scheduling + CI)
├── bot/
│   ├── __init__.py
│   ├── models.py           Jersey dataclass
│   ├── scraper.py          Playwright scraper + classification logic
│   ├── notifier.py         Gmail SMTP email sender
│   └── state.py            Per-(team,category) notification state machine
├── config.yaml             All tunable parameters
├── state.json              Persisted run-to-run notification state (auto-committed)
├── main.py                 Orchestrator / entry point
├── requirements.txt
└── README.md
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No jerseys found | Fanatics changed their page structure | Run `--debug` and inspect `debug_page.html` / `debug_api_responses.json`; update selectors in `scraper.py` if needed |
| Email not sent | `GMAIL_APP_PASSWORD` secret missing or wrong | Verify the secret value in GitHub repo settings |
| Bot running but no notification | Jerseys were already found on a previous run | Check `state.json`; if status is `"NOTIFIED"` for your team, the jerseys are still listed (or were never reset). Delete the relevant key in `state.json` and re-run to force a fresh check. |
| GitHub Actions not triggering | Workflow file syntax error, or repo has been inactive | Check the Actions tab in GitHub; inactive repos on free tier can have cron jobs paused — re-enable by visiting the Actions tab |
