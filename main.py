#!/usr/bin/env python3
"""
NHL Jersey Clearance Bot — entry point.

Usage:
  python main.py                  normal run
  python main.py --dry-run        scrape but skip email + state writes
  python main.py --debug          write debug_screenshot.png / debug_page.html
  python main.py --config other.yaml
"""

import argparse
import logging
import sys

import yaml

from bot.models import Jersey
from bot.notifier import send_notification
from bot.scraper import scrape_jerseys
from bot.state import (
    load_state, save_state,
    should_notify, mark_notified, reset_if_notified,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def filter_jerseys(jerseys: list, config: dict) -> dict:
    """
    Returns {(team, jersey_type): [Jersey, ...]} for notify-enabled teams
    whose jerseys also match target sizes.
    """
    notify_teams = {t["name"] for t in config["watch_teams"] if t.get("notify")}
    enabled_cats = {
        k.capitalize()
        for k, v in config["jersey_categories"].items()
        if v.get("enabled")
    }

    result: dict = {}
    for j in jerseys:
        if j.team not in notify_teams:
            continue
        if j.jersey_type not in enabled_cats:
            continue
        if not _has_target_size(j.sizes_available, config):
            continue
        result.setdefault((j.team, j.jersey_type), []).append(j)
    return result


def _has_target_size(sizes: list, config: dict) -> bool:
    """True when the jersey comes in one of the configured target sizes,
    or when no size information is available (include-by-default)."""
    if not sizes:
        return True
    ts = config.get("target_sizes", {})
    targets = {s.upper() for s in ts.get("standard", [])} | {str(n) for n in ts.get("numeric", [])}
    return bool({s.upper().strip() for s in sizes} & targets)


def main() -> None:
    parser = argparse.ArgumentParser(description="NHL Jersey Clearance Bot")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scrape only — no emails sent, state unchanged")
    parser.add_argument("--debug", action="store_true",
                        help="Save debug_screenshot.png and debug_page.html")
    parser.add_argument("--config", default="config.yaml", metavar="PATH",
                        help="Path to config file (default: config.yaml)")
    args = parser.parse_args()

    config = load_config(args.config)
    state = load_state()

    # ── Scrape ────────────────────────────────────────────────────────────────
    logger.info("Scraping Fanatics…")
    all_jerseys = scrape_jerseys(config, debug=args.debug)
    logger.info(f"Total jerseys on page: {len(all_jerseys)}")

    # ── Filter for watched teams + sizes ──────────────────────────────────────
    matched = filter_jerseys(all_jerseys, config)
    total_matched = sum(len(v) for v in matched.values())
    logger.info(f"Matching jerseys (watched teams + target sizes): {total_matched}")

    # ── Notify ────────────────────────────────────────────────────────────────
    for (team, jersey_type), jerseys in matched.items():
        if should_notify(state, team, jersey_type):
            logger.info(f"  NOTIFY  {team} — {jersey_type} ({len(jerseys)} jersey(s))")
            if not args.dry_run:
                send_notification(team, jersey_type, jerseys, config)
                mark_notified(state, team, jersey_type)
        else:
            logger.info(f"  SKIP    {team} — {jersey_type} (already notified this window)")

    # ── Reset teams whose jerseys are gone → allow re-notification later ──────
    notify_teams = {t["name"] for t in config["watch_teams"] if t.get("notify")}
    enabled_cats = {
        k.capitalize()
        for k, v in config["jersey_categories"].items()
        if v.get("enabled")
    }
    for team in notify_teams:
        for jersey_type in enabled_cats:
            if (team, jersey_type) not in matched:
                if reset_if_notified(state, team, jersey_type):
                    logger.info(f"  RESET   {team} — {jersey_type} (no longer on sale)")

    # ── Persist state ─────────────────────────────────────────────────────────
    if not args.dry_run:
        save_state(state)
        logger.info("State saved.")
    else:
        logger.info("Dry-run: state not written.")


if __name__ == "__main__":
    main()
