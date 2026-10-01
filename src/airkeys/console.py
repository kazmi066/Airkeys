"""Keep a Windows receiver alive when Ctrl+C is typed into a terminal.

SendInput of Ctrl+C becomes a console cancel for whichever program owns that
console. AirKeys used to be that program, so cancelling a terminal quit the
receiver. Detach, and ignore the signal if a console is still attached.
"""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

_HANDLER = None


def relaunch_as_admin() -> bool:
    """Start an elevated receiver and leave this process. Games drop keys from a normal window.

    Returns True when this process should exit because the elevated copy was started.
    runas does not keep PYTHONPATH, so the new command sets it itself.
    """
    if sys.platform != "win32" or _is_admin():
        return False
    import ctypes
    from ctypes import wintypes

    src = Path(__file__).resolve().parents[1]
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    exe = pythonw if pythonw.is_file() else python
    command = f'/c set "PYTHONPATH={src}" && start "" "{exe}" -m airkeys receive'
    shell = ctypes.windll.shell32
    shell.ShellExecuteW.argtypes = [
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_int,
    ]
    shell.ShellExecuteW.restype = ctypes.c_void_p
    try:
        launched = shell.ShellExecuteW(None, "runas", os.environ.get("COMSPEC", "cmd.exe"), command, str(src.parent), 0) or 0
    except Exception:
        return False
    return launched > 32


def _is_admin() -> bool:
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


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
