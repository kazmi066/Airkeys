"""Capture the Mac keyboard while sharing is on.

The tap lives on its own thread. On Python 3.14, a tap installed on the Tk
run loop fires while the GIL is released and aborts the process. This thread
keeps the GIL only while the tap is dispatching, then sleeps so the window
and the network can run.
"""

from __future__ import annotations

import queue
import sys
import threading
import time

from airkeys.inject import INJECT_MARKER, USER_DATA_FIELD
from airkeys.route import FLAGS_CHANGED, KEY_DOWN, KEY_UP, FloodFuse, route_event

TAP_DISABLED_TIMEOUT = 0xFFFFFFFE
TAP_DISABLED_USER = 0xFFFFFFFF
AUTOREPEAT_FIELD = 8
KEYCODE_FIELD = 9
RUN_HANDLED = 4
CG_PATH = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
CF_PATH = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"


class Grabber:
    def __init__(self, state, map_cmd) -> None:
        self.state = state
        self.map_cmd = map_cmd
        self.events: queue.Queue = queue.Queue()
        self.fuse = FloodFuse()
        self.held_mods: set[int] = set()
        self.permission_hint = ""
        self.tap = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._ok = False

    def ensure(self) -> bool:
        if sys.platform != "darwin":
            self.permission_hint = "Keyboard capture only runs on macOS."
            return False
        if self._thread is not None and self._thread.is_alive() and self._ok:
            return True
        self.shutdown()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._ok = False
        self.held_mods = set()
        self.fuse.clear()
        self._thread = threading.Thread(target=self._thread_main, name="airkeys-keys", daemon=True)
        self._thread.start()
        self._ready.wait(2)
        return self._ok

    def shutdown(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(1.5)
        self._thread = None
        self._ok = False
        self.tap = None

    def _thread_main(self) -> None:
        try:
            self._run_loop()
        except Exception as exc:
            self.permission_hint = str(exc)
            self._ok = False
        finally:
            self._ready.set()

    def _run_loop(self) -> None:
        import ctypes

        # PyDLL does not drop the GIL. The tap callback is safe only while it is held.
        cg = ctypes.PyDLL(CG_PATH)
        cf = ctypes.PyDLL(CF_PATH)
        self._bind(ctypes, cg, cf)
        mode = ctypes.c_void_p.in_dll(cf, "kCFRunLoopDefaultMode")
        mask = (1 << KEY_DOWN) | (1 << KEY_UP) | (1 << FLAGS_CHANGED)
        callback = self._CFUNCTYPE(self._callback_impl)
        self._callback = callback
        tap = cg.CGEventTapCreate(1, 0, 0, mask, callback, None)
        if not tap:
            self.permission_hint = _permission_text()
            self._ok = False
            self._ready.set()
            return
        source = cf.CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = cf.CFRunLoopGetCurrent()
        cf.CFRunLoopAddSource(loop, source, mode)
        cg.CGEventTapEnable(tap, True)
        self.tap = tap
        self._ok = True
        self.permission_hint = ""
        self._ready.set()
        try:
            while not self._stop.is_set():
                handled = 0
                while handled < 40 and not self._stop.is_set():
                    result = cf.CFRunLoopRunInMode(mode, 0, True)
                    if result != RUN_HANDLED:
                        break
                    handled += 1
                time.sleep(0.004)
        finally:
            cg.CGEventTapEnable(tap, False)
            cf.CFRunLoopRemoveSource(loop, source, mode)
            cf.CFRelease(source)
            cf.CFRelease(tap)
            self.tap = None
            self._ok = False

    def _bind(self, ctypes, cg, cf) -> None:
        self._CFUNCTYPE = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        cg.CGEventTapCreate.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint64,
            self._CFUNCTYPE,
            ctypes.c_void_p,
        ]
        cg.CGEventTapCreate.restype = ctypes.c_void_p
        cg.CGEventTapEnable.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        cg.CGEventTapEnable.restype = None
        cg.CGEventGetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        cg.CGEventGetIntegerValueField.restype = ctypes.c_int64
        cg.CGEventGetFlags.argtypes = [ctypes.c_void_p]
        cg.CGEventGetFlags.restype = ctypes.c_uint64
        cf.CFMachPortCreateRunLoopSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        cf.CFMachPortCreateRunLoopSource.restype = ctypes.c_void_p
        cf.CFRunLoopGetCurrent.restype = ctypes.c_void_p
        cf.CFRunLoopAddSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        cf.CFRunLoopAddSource.restype = None
        cf.CFRunLoopRemoveSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        cf.CFRunLoopRemoveSource.restype = None
        cf.CFRunLoopRunInMode.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_bool]
        cf.CFRunLoopRunInMode.restype = ctypes.c_int32
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFRelease.restype = None
        self._cg = cg

    def _callback_impl(self, _proxy, typ, event, _refcon):
        try:
            if typ in (TAP_DISABLED_TIMEOUT, TAP_DISABLED_USER):
                if self.tap:
                    self._cg.CGEventTapEnable(self.tap, True)
                return event
            if self._on_event(typ, event):
                return None
        except Exception:
            return event
        return event

    def _on_event(self, typ, event) -> bool:
        if typ not in (KEY_DOWN, KEY_UP, FLAGS_CHANGED):
            return False
        cg = self._cg
        is_ours = cg.CGEventGetIntegerValueField(event, USER_DATA_FIELD) == INJECT_MARKER
        keycode = int(cg.CGEventGetIntegerValueField(event, KEYCODE_FIELD))
        flags = int(cg.CGEventGetFlags(event))
        repeat = bool(cg.CGEventGetIntegerValueField(event, AUTOREPEAT_FIELD))
        decision, self.held_mods = route_event(
            typ,
            keycode,
            flags,
            sharing=self.state.active(),
            is_ours=is_ours,
            repeat=repeat,
            held_mods=self.held_mods,
            map_cmd_to_ctrl=bool(self.map_cmd()),
        )
        if decision.toggle:
            self.state.enabled = False
            self.events.put(("stop",))
        if decision.forward:
            if self.fuse.add():
                self.state.enabled = False
                self.events.put(("fuse",))
                return False
            self.events.put(("keys", decision.forward))
        return decision.swallow


def _permission_text() -> str:
    return (
        "Allow this Python in Accessibility, then click Share.\n"
        + sys.executable
    )


def open_accessibility_settings() -> None:
    import subprocess

    subprocess.run(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
        check=False,
    )


def probe() -> tuple[bool, str]:
    """Create a tap and release it. Sharing stays off, so keys are not swallowed."""
    grabber = Grabber(_Idle(), lambda: True)
    ok = grabber.ensure()
    hint = grabber.permission_hint
    grabber.shutdown()
    if ok:
        return True, "Keyboard capture is allowed. AirKeys can share keys from this Mac."
    return False, hint or "Keyboard capture is blocked."


class _Idle:
    def __init__(self) -> None:
        self.enabled = False
        self.connected = False

    def active(self) -> bool:
        return False
