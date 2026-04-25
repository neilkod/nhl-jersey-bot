"""
Notification state machine.

Each (team, jersey_type) pair cycles through:

  NOT_SEEN ──(jerseys appear)──▶ NOTIFIED ──(jerseys gone)──▶ NOT_SEEN

An email fires only on the NOT_SEEN → NOTIFIED transition, so the user
gets exactly one alert per "availability window" per category.
"""

import json
import os
from datetime import datetime, timezone
from typing import Tuple

STATE_FILE = "state.json"


def _key(team: str, jersey_type: str) -> str:
    return f"{team}|{jersey_type}"


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def should_notify(state: dict, team: str, jersey_type: str) -> bool:
    """True when jerseys are present and we haven't notified yet this window."""
    return state.get(_key(team, jersey_type), {}).get("status") != "NOTIFIED"


def mark_notified(state: dict, team: str, jersey_type: str) -> None:
    state[_key(team, jersey_type)] = {
        "status": "NOTIFIED",
        "last_notified": datetime.now(timezone.utc).isoformat(),
    }


def reset_if_notified(state: dict, team: str, jersey_type: str) -> bool:
    """Reset back to NOT_SEEN so the next appearance re-triggers an email.
    Returns True if a reset actually happened."""
    key = _key(team, jersey_type)
    if state.get(key, {}).get("status") == "NOTIFIED":
        state[key] = {"status": "NOT_SEEN"}
        return True
    return False
