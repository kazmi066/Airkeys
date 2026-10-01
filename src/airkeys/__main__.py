"""AirKeys command line."""

from __future__ import annotations

import sys

from airkeys import __version__

HELP = """\
AirKeys sends a MacBook keyboard to another computer on the same Wi-Fi.

  python3 -m airkeys              open the window
  python3 -m airkeys send         this Mac is the keyboard
  python3 -m airkeys receive      this computer receives keys
  python3 -m airkeys doctor       check macOS keyboard permission
  python3 -m airkeys version
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] == "gui":
        from airkeys.ui import run

        run(None)
        return 0
    command = args[0]
    if command == "send":
        from airkeys.ui import run

        run("send")
        return 0
    if command == "receive":
        from airkeys.ui import run

        run("receive")
        return 0
    if command == "doctor":
        from airkeys.grab_mac import probe

        ok, text = probe()
        print(text)
        return 0 if ok else 1
    if command == "version":
        print(__version__)
        return 0
    if command in {"-h", "--help", "help"}:
        print(HELP)
        return 0
    print(HELP)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
