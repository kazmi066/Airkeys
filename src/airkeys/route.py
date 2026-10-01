"""Decide what a Mac key event should do.

This stays free of CoreGraphics so the rules can be tested without a display.
The numeric event types match CGEventType on purpose.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from airkeys.keymap import CAPS, FN, KEYS, MODIFIER_CODES, remap_command

KEY_DOWN = 10
KEY_UP = 11
FLAGS_CHANGED = 12

TOGGLE_KEY = 40  # k

FLAG_SHIFT = 0x00020000
FLAG_CTRL = 0x00040000
FLAG_ALT = 0x00080000
FLAG_CMD = 0x00100000
MOD_MASK = FLAG_SHIFT | FLAG_CTRL | FLAG_ALT | FLAG_CMD
TOGGLE_FLAGS = FLAG_CTRL | FLAG_ALT


@dataclass
class Decision:
    swallow: bool
    toggle: bool
    forward: list[tuple[int, bool]]


class FloodFuse:
    """Trip if events arrive faster than a person can type.

    A capture/inject loop on one Mac would otherwise repeat forever.
    """

    def __init__(self, limit: int = 50, window: float = 0.1) -> None:
        self.limit = limit
        self.window = window
        self.hits: deque[float] = deque()

    def add(self, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        self.hits.append(moment)
        while self.hits and moment - self.hits[0] > self.window:
            self.hits.popleft()
        return len(self.hits) > self.limit

    def clear(self) -> None:
        self.hits.clear()


def route_event(
    event_type: int,
    keycode: int,
    flags: int,
    *,
    sharing: bool,
    is_ours: bool,
    repeat: bool,
    held_mods: set[int],
    map_cmd_to_ctrl: bool,
) -> tuple[Decision, set[int]]:
    held = set(held_mods)
    if is_ours:
        return Decision(False, False, []), held

    if event_type == KEY_DOWN and keycode == TOGGLE_KEY and (flags & MOD_MASK) == TOGGLE_FLAGS:
        # Swallow the shortcut either way so it does not type a k.
        if repeat:
            return Decision(True, False, []), held
        return Decision(True, True, []), held

    if event_type == FLAGS_CHANGED and keycode == FN:
        if sharing:
            return Decision(True, False, []), held
        return Decision(False, False, []), held

    if event_type == FLAGS_CHANGED and keycode == CAPS:
        if not sharing:
            return Decision(False, False, []), held
        return Decision(True, False, [(CAPS, True), (CAPS, False)]), held

    if event_type == FLAGS_CHANGED and keycode in MODIFIER_CODES:
        down = keycode not in held
        if down:
            held.add(keycode)
        else:
            held.discard(keycode)
        if not sharing:
            return Decision(False, False, []), held
        sent = remap_command(keycode, map_cmd_to_ctrl)
        return Decision(True, False, [(sent, down)]), held

    if event_type in (KEY_DOWN, KEY_UP) and keycode in MODIFIER_CODES | {CAPS, FN}:
        # Modifiers are handled from flags-changed events.
        if sharing:
            return Decision(True, False, []), held
        return Decision(False, False, []), held

    if event_type in (KEY_DOWN, KEY_UP):
        if keycode not in KEYS:
            return Decision(False, False, []), held
        if not sharing:
            return Decision(False, False, []), held
        down = event_type == KEY_DOWN
        return Decision(True, False, [(keycode, down)]), held

    return Decision(False, False, []), held
