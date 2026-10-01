"""Remember the PIN and the last computer this Mac connected to."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

PATH = Path.home() / ".airkeys.json"


def load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def update(**values) -> dict:
    data = load()
    data.update(values)
    PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def receiver_pin() -> str:
    data = load()
    pin = data.get("pin")
    if isinstance(pin, str) and len(pin) == 6 and pin.isdigit():
        return pin
    return new_pin()


def new_pin() -> str:
    pin = f"{secrets.randbelow(1_000_000):06d}"
    update(pin=pin)
    return pin
