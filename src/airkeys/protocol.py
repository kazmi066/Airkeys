"""Newline-delimited JSON messages for one keyboard session."""

from __future__ import annotations

import hmac
import json

PROTOCOL = 1
MAX_LINE = 1024


class ProtocolError(Exception):
    pass


class AuthError(Exception):
    pass


def encode(payload: dict) -> bytes:
    message = {"v": PROTOCOL, **payload}
    data = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_LINE:
        raise ProtocolError("message is too long")
    return data + b"\n"


def decode_line(line: bytes) -> dict:
    if len(line) > MAX_LINE:
        raise ProtocolError("message is too long")
    try:
        text = line.decode("utf-8")
        obj = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("bad message") from exc
    if not isinstance(obj, dict) or obj.get("v") != PROTOCOL:
        raise ProtocolError("bad message")
    return obj


def pins_match(got: object, expected: str) -> bool:
    if not isinstance(got, str):
        return False
    left = got.encode("utf-8")
    right = expected.encode("utf-8")
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def parse_key(msg: dict) -> tuple[int, bool] | None:
    if msg.get("op") != "key":
        return None
    code = msg.get("code")
    down = msg.get("down")
    if isinstance(code, bool) or not isinstance(code, int) or not 0 <= code <= 511:
        return None
    if isinstance(down, bool):
        return code, down
    if down in (0, 1):
        return code, bool(down)
    return None
