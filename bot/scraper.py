"""
Fanatics product scraper.

Extraction strategy (tried in order):
  1. Intercept the JSON API response Fanatics issues during page load —
     more reliable than DOM parsing and survives layout redesigns.
  2. Extract from __NEXT_DATA__ embedded in the HTML.
  3. DOM scraping with multiple CSS-selector fallbacks.

If the site structure changes and the scraper stops returning results, run
with --debug to save debug_screenshot.png and debug_page.html for inspection.
"""

import json
import logging
import re
from typing import List, Optional

from playwright.sync_api import sync_playwright, Page, Response

from .models import Jersey

logger = logging.getLogger(__name__)

# ── Public API ────────────────────────────────────────────────────────────────

def scrape_jerseys(config: dict, debug: bool = False) -> List[Jersey]:
    url = config["fanatics_url"]
    jerseys: List[Jersey] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # Collect all JSON responses while the page loads so we can mine them
        # for product data without relying on any specific API path.
        captured_json: list = []

        def on_response(response: Response) -> None:
            ct = response.headers.get("content-type", "")
            if "application/json" not in ct:
                return
            try:
                data = response.json()
                captured_json.append(data)
            except Exception:
                pass

        page.on("response", on_response)

        logger.info(f"Loading {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(6_000)   # let deferred JS finish
        except Exception as exc:
            logger.error(f"Page load error: {exc}")
            browser.close()
            return []

        if debug:
            page.screenshot(path="debug_screenshot.png", full_page=True)
            with open("debug_page.html", "w", encoding="utf-8") as fh:
                fh.write(page.content())
            with open("debug_api_responses.json", "w", encoding="utf-8") as fh:
                json.dump(captured_json, fh, indent=2, default=str)
            logger.info("Debug files written: debug_screenshot.png / debug_page.html / debug_api_responses.json")

        # --- Strategy 1: intercepted API responses ---------------------------
        for payload in captured_json:
            products = _find_product_list(payload)
            if products:
                jerseys = _parse_products(products, config)
                logger.info(f"[strategy-1] parsed {len(jerseys)} jerseys from API response")
                break

        # --- Strategy 2: __NEXT_DATA__ in page HTML --------------------------
        if not jerseys:
            jerseys = _extract_from_next_data(page, config)

        # --- Strategy 3: DOM scraping ----------------------------------------
        if not jerseys:
            logger.info("Falling back to DOM scraping…")
            jerseys = _dom_scrape(page, config)

        browser.close()

    logger.info(f"Total jerseys extracted: {len(jerseys)}")
    return jerseys


# ── Strategy helpers ──────────────────────────────────────────────────────────

def _extract_from_next_data(page: Page, config: dict) -> List[Jersey]:
    raw = page.evaluate(
        "() => { const el = document.getElementById('__NEXT_DATA__'); "
        "return el ? el.textContent : null; }"
    )
    if not raw:
        return []
    try:
        data = json.loads(raw)
        products = _find_product_list(data)
        if products:
            jerseys = _parse_products(products, config)
            logger.info(f"[strategy-2] parsed {len(jerseys)} jerseys from __NEXT_DATA__")
            return jerseys
    except Exception as exc:
        logger.debug(f"__NEXT_DATA__ parse failed: {exc}")
    return []


def _dom_scrape(page: Page, config: dict) -> List[Jersey]:
    card_selectors = [
        '[class*="product-container"]',
        '[class*="ProductCard"]',
        '[class*="product-card"]',
        '[data-testid*="product"]',
        'article[class*="product"]',
        '[class*="item-cell"]',
        '[class*="ProductItem"]',
    ]

    cards = []
    for sel in card_selectors:
        try:
            cards = page.query_selector_all(sel)
            if cards:
                logger.info(f"[strategy-3] found {len(cards)} cards via '{sel}'")
                break
        except Exception:
            continue

    if not cards:
        logger.warning(
            "No product cards found via DOM. "
            "Re-run with --debug and inspect debug_page.html to locate the right selector."
        )
        return []

    jerseys: List[Jersey] = []
    for card in cards:
        try:
            name = _first_text(card, [
                '[class*="product-name"]', '[class*="ProductName"]',
                '[class*="item-description"]', '[data-testid*="name"]',
                '[class*="title"]', 'h2', 'h3',
            ])
            if not name:
                continue

            sale_text = _first_text(card, [
                '[class*="sale-price"]', '[class*="SalePrice"]',
                '[class*="final-price"]', '[class*="current-price"]',
                '[class*="selling-price"]',
            ])
            orig_text = _first_text(card, [
                '[class*="original-price"]', '[class*="OriginalPrice"]',
                '[class*="list-price"]', '[class*="was-price"]',
                '[class*="regular-price"]', 's',
            ])
            link_el = card.query_selector("a[href]")
            href = link_el.get_attribute("href") if link_el else ""
            url = f"https://www.fanatics.com{href}" if href and href.startswith("/") else (href or "")

            size_els = card.query_selector_all('[class*="size"]')
            sizes = [el.inner_text().strip() for el in size_els if el.inner_text().strip()]

            jersey = _build_jersey(
                name=name,
                sale_price=_parse_price(sale_text),
                orig_price=_parse_price(orig_text),
                url=url,
                sizes=sizes,
                config=config,
            )
            if jersey:
                jerseys.append(jersey)
        except Exception as exc:
            logger.debug(f"DOM card parse error: {exc}")

    logger.info(f"[strategy-3] DOM scrape yielded {len(jerseys)} matching jerseys")
    return jerseys


# ── JSON product-list finder (recursive) ──────────────────────────────────────

_PRODUCT_KEYS = {"productName", "name", "title", "displayName", "itemName"}

def _find_product_list(data, _depth: int = 0) -> list:
    """Recursively walk a JSON blob to find the first array of product-like dicts."""
    if _depth > 8:
        return []
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and _PRODUCT_KEYS & first.keys():
            return data
    if isinstance(data, dict):
        for v in data.values():
            result = _find_product_list(v, _depth + 1)
            if result:
                return result
    return []


# ── Product parsing ───────────────────────────────────────────────────────────

def _parse_products(products: list, config: dict) -> List[Jersey]:
    out: List[Jersey] = []
    for p in products:
        try:
            name = (
                p.get("productName") or p.get("name") or
                p.get("title") or p.get("displayName") or
                p.get("itemName") or ""
            )
            if not name:
                continue
            sale = _coerce_price(p.get("salePrice") or p.get("price") or p.get("finalPrice"))
            orig = _coerce_price(p.get("listPrice") or p.get("originalPrice") or p.get("regularPrice"))
            url = p.get("pdpUrl") or p.get("url") or p.get("productUrl") or ""
            if url and not url.startswith("http"):
                url = f"https://www.fanatics.com{url}"
            sizes = _extract_sizes_from_dict(p)
            j = _build_jersey(name=name, sale_price=sale, orig_price=orig,
                              url=url, sizes=sizes, config=config)
            if j:
                out.append(j)
        except Exception as exc:
            logger.debug(f"Product parse error: {exc}")
    return out


def _build_jersey(
    name: str,
    sale_price: Optional[float],
    orig_price: Optional[float],
    url: str,
    sizes: list,
    config: dict,
) -> Optional[Jersey]:
    if is_excluded(name, config):
        return None
    jersey_type = classify_jersey_type(name, orig_price or sale_price, config)
    if not jersey_type:
        return None
    team = _detect_team(name, config)
    return Jersey(
        name=name,
        team=team,
        jersey_type=jersey_type,
        sale_price=sale_price or 0.0,
        original_price=orig_price,
        url=url,
        sizes_available=sizes,
    )


# ── Classification helpers ────────────────────────────────────────────────────

def classify_jersey_type(name: str, price: Optional[float], config: dict) -> Optional[str]:
    """Return the matched category name (title-cased) or None."""
    name_lower = name.lower()
    for cat_name, cat_cfg in config.get("jersey_categories", {}).items():
        if not cat_cfg.get("enabled", True):
            continue
        for kw in cat_cfg.get("keywords", []):
            if kw.lower() in name_lower:
                return cat_name.capitalize()
    # Price-based fallback for Authentic when keyword is absent
    authentic_min = (config.get("jersey_categories", {})
                         .get("authentic", {})
                         .get("min_original_price", 180))
    if price and price >= authentic_min:
        return "Authentic"
    return None


def is_excluded(name: str, config: dict) -> bool:
    name_lower = name.lower()
    return any(kw.lower() in name_lower for kw in config.get("exclude_keywords", []))


def _detect_team(name: str, config: dict) -> str:
    name_lower = name.lower()
    for team_cfg in config.get("watch_teams", []):
        if team_cfg["name"].lower() in name_lower:
            return team_cfg["name"]
    return "Unknown"


# ── Utility ───────────────────────────────────────────────────────────────────

def _extract_sizes_from_dict(p: dict) -> list:
    sizes = []
    for key in ("sizes", "availableSizes", "sizeOptions", "variants", "skus"):
        val = p.get(key)
        if not isinstance(val, list):
            continue
        for item in val:
            if isinstance(item, str):
                sizes.append(item)
            elif isinstance(item, dict):
                v = item.get("size") or item.get("label") or item.get("value") or ""
                if v:
                    sizes.append(str(v))
    return sizes


def _coerce_price(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return _parse_price(str(value))


def _parse_price(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    cleaned = text.replace(",", "").replace("$", "")
    m = re.search(r"\d+\.?\d*", cleaned)
    return float(m.group()) if m else None


def _first_text(element, selectors: list) -> str:
    for sel in selectors:
        try:
            el = element.query_selector(sel)
            if el:
                t = el.inner_text().strip()
                if t:
                    return t
        except Exception:
            continue
    return ""
