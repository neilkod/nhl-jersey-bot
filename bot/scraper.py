"""
Fanatics product scraper — uses ScraperAPI to bypass Akamai bot protection.

ScraperAPI routes requests through residential IPs and renders JavaScript,
returning the same HTML a real browser would see. No Playwright needed.

Extraction strategy (tried in order):
  1. __NEXT_DATA__ JSON embedded in page HTML (Next.js SSR)
  2. DOM scraping with BeautifulSoup

Run with --debug to write debug_page.html for selector inspection.
"""

import json
import logging
import os
import re
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from .models import Jersey

logger = logging.getLogger(__name__)

SCRAPERAPI_ENDPOINT = "http://api.scraperapi.com"


# ── Public API ────────────────────────────────────────────────────────────────

def scrape_jerseys(config: dict, debug: bool = False) -> List[Jersey]:
    api_key = os.environ.get("SCRAPERAPI_KEY", "")
    if not api_key:
        raise EnvironmentError("SCRAPERAPI_KEY environment variable is not set.")

    url = config["fanatics_url"]
    logger.info(f"Fetching {url} via ScraperAPI…")

    html = _fetch(url, api_key)
    if not html:
        return []

    if debug:
        with open("debug_page.html", "w", encoding="utf-8") as fh:
            fh.write(html)
        logger.info("Debug file written: debug_page.html")

    soup = BeautifulSoup(html, "lxml")

    jerseys = _from_next_data(soup, config)

    if not jerseys:
        logger.info("Falling back to DOM scraping…")
        jerseys = _dom_scrape(soup, config)

    logger.info(f"Total jerseys extracted: {len(jerseys)}")
    return jerseys


# ── Fetch ─────────────────────────────────────────────────────────────────────

def _fetch(url: str, api_key: str) -> Optional[str]:
    # Try plain fetch first (1 credit). Fanatics uses Next.js SSR so product
    # data is usually in the initial HTML without needing JS rendering.
    # Falls back to render=true (5 credits) if the plain response looks empty.
    for render in (False, True):
        params = {
            "api_key": api_key,
            "url": url,
            "country_code": "us",
        }
        if render:
            params["render"] = "true"
            logger.info("Retrying with JS rendering enabled…")

        try:
            resp = requests.get(SCRAPERAPI_ENDPOINT, params=params, timeout=120)
            resp.raise_for_status()
            chars = len(resp.text)
            logger.info(f"ScraperAPI: HTTP {resp.status_code}, {chars:,} chars (render={render})")
            if chars > 5_000:   # a real page; Access Denied pages are ~600 chars
                return resp.text
            logger.warning(f"Response suspiciously short ({chars} chars), retrying…")
        except requests.HTTPError as exc:
            logger.error(f"ScraperAPI HTTP error (render={render}): {exc}")
        except requests.RequestException as exc:
            logger.error(f"ScraperAPI request failed (render={render}): {exc}")

    return None


# ── Extraction strategies ─────────────────────────────────────────────────────

def _from_next_data(soup: BeautifulSoup, config: dict) -> List[Jersey]:
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        return []
    try:
        data = json.loads(tag.string)
        products = _find_product_list(data)
        if products:
            jerseys = _parse_products(products, config)
            logger.info(f"[strategy-1] {len(jerseys)} jerseys from __NEXT_DATA__")
            return jerseys
    except Exception as exc:
        logger.debug(f"__NEXT_DATA__ parse failed: {exc}")
    return []


def _dom_scrape(soup: BeautifulSoup, config: dict) -> List[Jersey]:
    def _has(cls, *terms):
        return cls and any(t in " ".join(cls).lower() for t in terms)

    cards = (
        soup.find_all(class_=lambda c: _has(c, "product-card", "productcard", "product-container", "item-cell", "productitem")) or
        soup.find_all("article") or
        []
    )

    if not cards:
        logger.warning("No product cards found. Run with --debug and inspect debug_page.html.")
        return []

    logger.info(f"[strategy-2] {len(cards)} candidate cards found in DOM")
    jerseys = []
    for card in cards:
        try:
            name_el = (
                card.find(class_=lambda c: _has(c, "product-name", "productname")) or
                card.find(class_=lambda c: _has(c, "title")) or
                card.find("h2") or card.find("h3")
            )
            name = name_el.get_text(strip=True) if name_el else ""
            if not name:
                continue

            link = card.find("a", href=True)
            href = link["href"] if link else ""
            url = f"https://www.fanatics.com{href}" if href.startswith("/") else href

            sale_el = card.find(class_=lambda c: _has(c, "sale-price", "final-price", "current-price", "selling-price"))
            orig_el = card.find(class_=lambda c: _has(c, "original-price", "list-price", "was-price", "regular-price")) or card.find("s")

            sale_price = _parse_price(sale_el.get_text() if sale_el else "")
            orig_price = _parse_price(orig_el.get_text() if orig_el else "")

            size_els = card.find_all(class_=lambda c: _has(c, "size"))
            sizes = [el.get_text(strip=True) for el in size_els if el.get_text(strip=True)]

            j = _build_jersey(name, sale_price, orig_price, url, sizes, config)
            if j:
                jerseys.append(j)
        except Exception as exc:
            logger.debug(f"DOM card parse error: {exc}")

    logger.info(f"[strategy-2] {len(jerseys)} matching jerseys from DOM")
    return jerseys


# ── JSON product-list finder ──────────────────────────────────────────────────

_PRODUCT_KEYS = {"productName", "name", "title", "displayName", "itemName"}


def _find_product_list(data, _depth: int = 0) -> list:
    if _depth > 8:
        return []
    if isinstance(data, list) and data:
        if isinstance(data[0], dict) and _PRODUCT_KEYS & data[0].keys():
            return data
    if isinstance(data, dict):
        for v in data.values():
            result = _find_product_list(v, _depth + 1)
            if result:
                return result
    return []


# ── Product parsing ───────────────────────────────────────────────────────────

def _parse_products(products: list, config: dict) -> List[Jersey]:
    out = []
    for p in products:
        try:
            name = (p.get("productName") or p.get("name") or
                    p.get("title") or p.get("displayName") or p.get("itemName") or "")
            if not name:
                continue
            sale = _coerce_price(p.get("salePrice") or p.get("price") or p.get("finalPrice"))
            orig = _coerce_price(p.get("listPrice") or p.get("originalPrice") or p.get("regularPrice"))
            url = p.get("pdpUrl") or p.get("url") or p.get("productUrl") or ""
            if url and not url.startswith("http"):
                url = f"https://www.fanatics.com{url}"
            sizes = _extract_sizes_from_dict(p)
            j = _build_jersey(name, sale, orig, url, sizes, config)
            if j:
                out.append(j)
        except Exception as exc:
            logger.debug(f"Product parse error: {exc}")
    return out


def _build_jersey(name, sale_price, orig_price, url, sizes, config) -> Optional[Jersey]:
    if is_excluded(name, config):
        return None
    jersey_type = classify_jersey_type(name, orig_price or sale_price, config)
    if not jersey_type:
        return None
    return Jersey(
        name=name,
        team=_detect_team(name, config),
        jersey_type=jersey_type,
        sale_price=sale_price or 0.0,
        original_price=orig_price,
        url=url,
        sizes_available=sizes,
    )


# ── Classification ────────────────────────────────────────────────────────────

def classify_jersey_type(name: str, price: Optional[float], config: dict) -> Optional[str]:
    name_lower = name.lower()
    for cat_name, cat_cfg in config.get("jersey_categories", {}).items():
        if not cat_cfg.get("enabled", True):
            continue
        for kw in cat_cfg.get("keywords", []):
            if kw.lower() in name_lower:
                return cat_name.capitalize()
    authentic_min = (config.get("jersey_categories", {})
                         .get("authentic", {}).get("min_original_price", 180))
    if price and price >= authentic_min:
        return "Authentic"
    return None


def is_excluded(name: str, config: dict) -> bool:
    return any(kw.lower() in name.lower() for kw in config.get("exclude_keywords", []))


def _detect_team(name: str, config: dict) -> str:
    for t in config.get("watch_teams", []):
        if t["name"].lower() in name.lower():
            return t["name"]
    return "Unknown"


# ── Utilities ─────────────────────────────────────────────────────────────────

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
    m = re.search(r"\d+\.?\d*", text.replace(",", "").replace("$", ""))
    return float(m.group()) if m else None
