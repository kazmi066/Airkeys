"""Keep a Windows receiver alive when Ctrl+C is typed into a terminal.

SendInput of Ctrl+C becomes a console cancel for whichever program owns that
console. AirKeys used to be that program, so cancelling a terminal quit the
receiver. Detach, and ignore the signal if a console is still attached.
"""

from __future__ import annotations

import signal
import sys

_HANDLER = None


def detach_from_console() -> None:
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    ctrl_c = 0
    ctrl_break = 1

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    def handler(ctrl_type: int) -> bool:
        return ctrl_type in (ctrl_c, ctrl_break)

    global _HANDLER
    _HANDLER = handler
    kernel.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
    kernel.SetConsoleCtrlHandler.restype = wintypes.BOOL
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    except (OSError, ValueError):
        pass
    kernel.SetConsoleCtrlHandler(_HANDLER, True)
    kernel.FreeConsole.restype = wintypes.BOOL
    kernel.FreeConsole()
