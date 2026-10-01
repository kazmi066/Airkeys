"""Mac virtual keycodes mapped to Windows scan codes and Linux key names.

Codes are the physical keys on an Apple ANSI keyboard, which is what a
MacBook Air uses. The PC applies its own layout to that physical key.
"""

from __future__ import annotations

from typing import NamedTuple


class KeyInfo(NamedTuple):
    name: str
    win_scan: int
    win_ext: bool
    linux: str


def _key(name: str, scan: int, ext: bool = False, linux: str | None = None) -> KeyInfo:
    if linux is None:
        linux = f"char:{name}" if len(name) == 1 else f"key:{name}"
    return KeyInfo(name, scan, ext, linux)


# mac keycode -> key
KEYS: dict[int, KeyInfo] = {
    # letters
    0: _key("a", 0x1E),
    1: _key("s", 0x1F),
    2: _key("d", 0x20),
    3: _key("f", 0x21),
    4: _key("h", 0x23),
    5: _key("g", 0x22),
    6: _key("z", 0x2C),
    7: _key("x", 0x2D),
    8: _key("c", 0x2E),
    9: _key("v", 0x2F),
    11: _key("b", 0x30),
    12: _key("q", 0x10),
    13: _key("w", 0x11),
    14: _key("e", 0x12),
    15: _key("r", 0x13),
    16: _key("y", 0x15),
    17: _key("t", 0x14),
    31: _key("o", 0x18),
    32: _key("u", 0x16),
    34: _key("i", 0x17),
    35: _key("p", 0x19),
    37: _key("l", 0x26),
    38: _key("j", 0x24),
    40: _key("k", 0x25),
    45: _key("n", 0x31),
    46: _key("m", 0x32),
    # digits
    18: _key("1", 0x02),
    19: _key("2", 0x03),
    20: _key("3", 0x04),
    21: _key("4", 0x05),
    23: _key("5", 0x06),
    22: _key("6", 0x07),
    26: _key("7", 0x08),
    28: _key("8", 0x09),
    25: _key("9", 0x0A),
    29: _key("0", 0x0B),
    # punctuation
    27: _key("-", 0x0C),
    24: _key("=", 0x0D),
    33: _key("[", 0x1A),
    30: _key("]", 0x1B),
    42: _key("\\", 0x2B),
    41: _key(";", 0x27),
    39: _key("'", 0x28),
    50: _key("`", 0x29),
    43: _key(",", 0x33),
    47: _key(".", 0x34),
    44: _key("/", 0x35),
    10: _key("section", 0x56, linux="char:<"),
    # editing
    36: _key("enter", 0x1C, linux="key:enter"),
    76: _key("enter", 0x1C, ext=True, linux="key:enter"),
    48: _key("tab", 0x0F, linux="key:tab"),
    49: _key("space", 0x39, linux="key:space"),
    51: _key("backspace", 0x0E, linux="key:backspace"),
    53: _key("escape", 0x01, linux="key:esc"),
    # modifiers. Command defaults to the Windows key unless the sender remaps it.
    55: _key("cmd", 0x5B, ext=True, linux="key:cmd"),
    54: _key("cmd_r", 0x5C, ext=True, linux="key:cmd_r"),
    59: _key("ctrl", 0x1D, linux="key:ctrl"),
    62: _key("ctrl_r", 0x1D, ext=True, linux="key:ctrl_r"),
    58: _key("alt", 0x38, linux="key:alt"),
    61: _key("alt_r", 0x38, ext=True, linux="key:alt_r"),
    56: _key("shift", 0x2A, linux="key:shift"),
    60: _key("shift_r", 0x36, linux="key:shift_r"),
    57: _key("caps", 0x3A, linux="key:caps_lock"),
    # arrows and navigation
    123: _key("left", 0x4B, ext=True, linux="key:left"),
    124: _key("right", 0x4D, ext=True, linux="key:right"),
    125: _key("down", 0x50, ext=True, linux="key:down"),
    126: _key("up", 0x48, ext=True, linux="key:up"),
    115: _key("home", 0x47, ext=True, linux="key:home"),
    119: _key("end", 0x4F, ext=True, linux="key:end"),
    116: _key("pageup", 0x49, ext=True, linux="key:page_up"),
    121: _key("pagedown", 0x51, ext=True, linux="key:page_down"),
    117: _key("delete", 0x53, ext=True, linux="key:delete"),
    114: _key("insert", 0x52, ext=True, linux="key:insert"),
    # function row
    122: _key("f1", 0x3B, linux="key:f1"),
    120: _key("f2", 0x3C, linux="key:f2"),
    99: _key("f3", 0x3D, linux="key:f3"),
    118: _key("f4", 0x3E, linux="key:f4"),
    96: _key("f5", 0x3F, linux="key:f5"),
    97: _key("f6", 0x40, linux="key:f6"),
    98: _key("f7", 0x41, linux="key:f7"),
    100: _key("f8", 0x42, linux="key:f8"),
    101: _key("f9", 0x43, linux="key:f9"),
    109: _key("f10", 0x44, linux="key:f10"),
    103: _key("f11", 0x57, linux="key:f11"),
    111: _key("f12", 0x58, linux="key:f12"),
}

LEFT_CMD = 55
RIGHT_CMD = 54
LEFT_CTRL = 59
RIGHT_CTRL = 62
CAPS = 57
FN = 63

MODIFIER_CODES = {
    LEFT_CMD,
    RIGHT_CMD,
    LEFT_CTRL,
    RIGHT_CTRL,
    58,  # left option
    61,  # right option
    56,  # left shift
    60,  # right shift
}


def remap_command(code: int, map_cmd_to_ctrl: bool) -> int:
    """Turn the Command keys into Control. Windows shortcuts then match the Mac habit."""
    if not map_cmd_to_ctrl:
        return code
    if code == LEFT_CMD:
        return LEFT_CTRL
    if code == RIGHT_CMD:
        return RIGHT_CTRL
    return code


def linux_parts(info: KeyInfo) -> tuple[str, str]:
    kind, value = info.linux.split(":", 1)
    return kind, value
