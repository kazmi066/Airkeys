"""Capture the Mac keyboard while sharing is on, and pass it through otherwise."""

from __future__ import annotations

import sys

from airkeys.inject import INJECT_MARKER, USER_DATA_FIELD
from airkeys.route import KEY_DOWN, KEY_UP, FLAGS_CHANGED, FloodFuse, route_event

TAP_DISABLED_TIMEOUT = 0xFFFFFFFE
TAP_DISABLED_USER = 0xFFFFFFFF
AUTOREPEAT_FIELD = 8
KEYCODE_FIELD = 9
RUN_HANDLED = 4


class Grabber:
    def __init__(self, state, map_cmd, on_toggle, on_forward, on_fuse) -> None:
        self.state = state
        self.map_cmd = map_cmd
        self.on_toggle = on_toggle
        self.on_forward = on_forward
        self.on_fuse = on_fuse
        self.fuse = FloodFuse()
        self.held_mods: set[int] = set()
        self.permission_hint = ""
        self.tap = None
        self._source = None
        self._callback = None
        self.cg = None
        self.cf = None
        self._mode = None

    def ensure(self) -> bool:
        if sys.platform != "darwin":
            self.permission_hint = "Keyboard capture only runs on macOS."
            return False
        if self.tap:
            return True
        import ctypes

        self.cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        self.cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self._bind(ctypes)
        mask = (1 << KEY_DOWN) | (1 << KEY_UP) | (1 << FLAGS_CHANGED)
        self._callback = self._CFUNCTYPE(self._callback_impl)
        # Keep the callback object alive for the life of the tap.
        tap = self.cg.CGEventTapCreate(
            1,  # kCGSessionEventTap
            0,  # kCGHeadInsertEventTap
            0,  # kCGEventTapOptionDefault, so the callback can delete events
            mask,
            self._callback,
            None,
        )
        if not tap:
            self.permission_hint = _permission_text()
            return False
        source = self.cf.CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = self.cf.CFRunLoopGetCurrent()
        self.cf.CFRunLoopAddSource(loop, source, self._mode)
        self.cg.CGEventTapEnable(tap, True)
        self.tap = tap
        self._source = source
        self.permission_hint = ""
        return True

    def pump(self) -> None:
        if not self.tap or self.cf is None:
            return
        for _ in range(30):
            result = self.cf.CFRunLoopRunInMode(self._mode, 0, True)
            if result != RUN_HANDLED:
                break

    def shutdown(self) -> None:
        tap = self.tap
        source = self._source
        self.tap = None
        self._source = None
        if tap and self.cg is not None:
            self.cg.CGEventTapEnable(tap, False)
        if source and self.cf is not None:
            self.cf.CFRelease(source)
        if tap and self.cf is not None:
            self.cf.CFRelease(tap)

    def _bind(self, ctypes) -> None:
        cg = self.cg
        cf = self.cf
        callback_type = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        self._CFUNCTYPE = callback_type
        cg.CGEventTapCreate.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint64,
            callback_type,
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
        cf.CFRunLoopGetCurrent.argtypes = []
        cf.CFRunLoopGetCurrent.restype = ctypes.c_void_p
        cf.CFRunLoopAddSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        cf.CFRunLoopAddSource.restype = None
        cf.CFRunLoopRunInMode.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_bool]
        cf.CFRunLoopRunInMode.restype = ctypes.c_int32
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFRelease.restype = None
        self._mode = ctypes.c_void_p.in_dll(cf, "kCFRunLoopDefaultMode")

    def _callback_impl(self, _proxy, typ, event, _refcon):
        try:
            if typ in (TAP_DISABLED_TIMEOUT, TAP_DISABLED_USER):
                if self.tap:
                    self.cg.CGEventTapEnable(self.tap, True)
                return event
            if self._on_event(typ, event):
                return None
        except Exception:
            return event
        return event

    def _on_event(self, typ, event) -> bool:
        if typ not in (KEY_DOWN, KEY_UP, FLAGS_CHANGED):
            return False
        user = self.cg.CGEventGetIntegerValueField(event, USER_DATA_FIELD)
        is_ours = user == INJECT_MARKER
        keycode = int(self.cg.CGEventGetIntegerValueField(event, KEYCODE_FIELD))
        flags = int(self.cg.CGEventGetFlags(event))
        repeat = bool(self.cg.CGEventGetIntegerValueField(event, AUTOREPEAT_FIELD))
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
            self.on_toggle()
        if decision.forward:
            if self.fuse.add():
                self.on_fuse()
                return False
            self.on_forward(decision.forward)
        return decision.swallow


def _permission_text() -> str:
    import sys as _sys

    return (
        "macOS is blocking keyboard capture. Open System Settings, Privacy & Security, "
        f"Accessibility, and enable this program:\n{_sys.executable}"
    )


def open_accessibility_settings() -> None:
    import subprocess

    subprocess.run(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
        check=False,
    )


def probe() -> tuple[bool, str]:
    """Create a tap and release it. Safe to run, it does not swallow keys."""
    state = _Idle()
    grabber = Grabber(state, lambda: True, lambda: None, lambda _pairs: None, lambda: None)
    ok = grabber.ensure()
    if not ok:
        return False, grabber.permission_hint
    grabber.pump()
    grabber.shutdown()
    return True, "Keyboard capture is allowed. AirKeys can share keys from this Mac."


class _Idle:
    def active(self) -> bool:
        return False
