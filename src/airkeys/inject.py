"""Type incoming keys on this computer."""

from __future__ import annotations

import sys
import threading

from airkeys.keymap import KEYS, KeyInfo, linux_parts

# Marker stamped on events this process creates, so a Mac capture tap can ignore them.
INJECT_MARKER = 0x41524B31
USER_DATA_FIELD = 42
PRIVATE_SOURCE = -1
FLAG_SHIFT = 0x00020000
FLAG_CTRL = 0x00040000
FLAG_ALT = 0x00080000
FLAG_CMD = 0x00100000
FLAG_CAPS = 0x00010000
MOD_FLAG = {
    56: FLAG_SHIFT,
    60: FLAG_SHIFT,
    59: FLAG_CTRL,
    62: FLAG_CTRL,
    58: FLAG_ALT,
    61: FLAG_ALT,
    55: FLAG_CMD,
    54: FLAG_CMD,
}


class Injector:
    def press(self, code: int, down: bool) -> None:
        raise NotImplementedError

    def release_all(self) -> None:
        raise NotImplementedError


def make_injector() -> Injector:
    if sys.platform == "darwin":
        return MacInjector()
    if sys.platform == "win32":
        return WinInjector()
    return LinuxInjector()


class MacInjector(Injector):
    def __init__(self) -> None:
        import ctypes

        self._ctypes = ctypes
        self.cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        self.cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.cg.CGEventSourceCreate.argtypes = [ctypes.c_int32]
        self.cg.CGEventSourceCreate.restype = ctypes.c_void_p
        self.cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
        self.cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        self.cg.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
        self.cg.CGEventSetIntegerValueField.restype = None
        self.cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        self.cg.CGEventSetFlags.restype = None
        self.cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        self.cg.CGEventPost.restype = None
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]
        self.cf.CFRelease.restype = None
        self._source = self.cg.CGEventSourceCreate(PRIVATE_SOURCE)
        self._held: set[int] = set()
        self._caps = False
        self._lock = threading.Lock()

    def press(self, code: int, down: bool) -> None:
        with self._lock:
            if code == 57 and down:
                self._caps = not self._caps
            if down:
                self._held.add(code)
            else:
                self._held.discard(code)
            flags = FLAG_CAPS if self._caps else 0
            for held in self._held:
                flags |= MOD_FLAG.get(held, 0)
            self._post(code, down, flags)

    def release_all(self) -> None:
        with self._lock:
            held = list(self._held)
            self._held.clear()
            for code in held:
                self._post(code, False, 0)

    def _post(self, code: int, down: bool, flags: int) -> None:
        event = self.cg.CGEventCreateKeyboardEvent(self._source, code, down)
        if not event:
            return
        self.cg.CGEventSetIntegerValueField(event, USER_DATA_FIELD, INJECT_MARKER)
        self.cg.CGEventSetFlags(event, flags)
        # HID tap so the focused app treats it as a real key.
        self.cg.CGEventPost(0, event)
        self.cf.CFRelease(event)


class WinInjector(Injector):
    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        ulong_ptr = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class INPUTUNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("ii", INPUTUNION)]

        self.INPUT = INPUT
        self.KEYBDINPUT = KEYBDINPUT
        if ctypes.sizeof(ctypes.c_void_p) == 8 and ctypes.sizeof(INPUT) != 40:
            raise RuntimeError(f"Windows INPUT struct is {ctypes.sizeof(INPUT)} bytes, expected 40")
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.user32.SendInput.restype = wintypes.UINT
        self._held: dict[int, tuple[int, bool]] = {}
        self._lock = threading.Lock()

    def press(self, code: int, down: bool) -> None:
        info = KEYS.get(code)
        if info is None:
            return
        with self._lock:
            self._send(info, down)
            if down:
                self._held[code] = (info.win_scan, info.win_ext)
            else:
                self._held.pop(code, None)

    def release_all(self) -> None:
        with self._lock:
            held = list(self._held.values())
            self._held.clear()
            for scan, ext in held:
                self._send_scan(scan, ext, False)

    def _send(self, info: KeyInfo, down: bool) -> None:
        self._send_scan(info.win_scan, info.win_ext, down)

    def _send_scan(self, scan: int, extended: bool, down: bool) -> None:
        flags = 0x0008  # KEYEVENTF_SCANCODE
        if extended:
            flags |= 0x0001
        if not down:
            flags |= 0x0002
        command = self.INPUT()
        command.type = 1
        command.ii.ki = self.KEYBDINPUT(0, scan, flags, 0, 0)
        sent = self.user32.SendInput(1, self._ctypes.byref(command), self._ctypes.sizeof(command))
        if sent != 1:
            raise OSError(f"SendInput failed ({self._ctypes.get_last_error()})")


class LinuxInjector(Injector):
    def __init__(self) -> None:
        try:
            from pynput.keyboard import Controller, Key
        except ImportError as exc:
            raise RuntimeError(
                "Linux needs pynput. From the airkeys folder run: python3 -m pip install pynput"
            ) from exc
        self.controller = Controller()
        self.Key = Key
        self._held: dict[int, object] = {}
        self._lock = threading.Lock()

    def press(self, code: int, down: bool) -> None:
        info = KEYS.get(code)
        if info is None:
            return
        key = self._resolve(info)
        with self._lock:
            if down:
                self.controller.press(key)
                self._held[code] = key
            else:
                self.controller.release(key)
                self._held.pop(code, None)

    def release_all(self) -> None:
        with self._lock:
            held = list(self._held.values())
            self._held.clear()
            for key in held:
                self.controller.release(key)

    def _resolve(self, info: KeyInfo):
        kind, value = linux_parts(info)
        if kind == "char":
            return value
        return getattr(self.Key, value)
