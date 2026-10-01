"""One window. On a Mac it shares the keyboard. Everywhere else it receives keys."""

from __future__ import annotations

import queue
import socket
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont

from airkeys import settings
from airkeys.discover import DISCOVERY_PORT, Beacon, Finder, local_ipv4, parse_host
from airkeys.inject import make_injector
from airkeys.link import DEFAULT_PORT, Client, Server
from airkeys.protocol import AuthError

BG = "#f5f5f7"
CARD = "#ffffff"
INK = "#1d1d1f"
MUTED = "#86868b"
BLUE = "#007aff"
LINE = "#d2d2d7"
SELECT = "#e8f2ff"


class ShareState:
    def __init__(self) -> None:
        self.enabled = False
        self.connected = False

    def active(self) -> bool:
        return self.enabled and self.connected


def _font(widget, size: int, weight: str = "normal") -> tuple:
    family = getattr(widget.winfo_toplevel(), "_airkeys_font", "Helvetica")
    return (family, size, weight)


def run(role: str | None = None) -> None:
    if role is None:
        role = "send" if sys.platform == "darwin" else "receive"
    if role == "send" and sys.platform != "darwin":
        role = "receive"
    if role == "receive":
        from airkeys.console import detach_from_console, relaunch_as_admin

        if relaunch_as_admin():
            return
        detach_from_console()
    root = tk.Tk()
    root.title("AirKeys")
    root.configure(bg=BG)
    root.resizable(False, False)
    families = set(tkfont.families(root))
    for name in (".AppleSystemUIFont", "Helvetica Neue", "Segoe UI", "Helvetica"):
        if name in families:
            root._airkeys_font = name
            break
    else:
        root._airkeys_font = "Helvetica"
    view = SenderView(root) if role == "send" else ReceiverView(root)
    root._airkeys_view = view
    view.pack(fill="both", expand=True)
    root.protocol("WM_DELETE_WINDOW", lambda: _quit(root))
    _place(root, 400, 560 if role == "send" else 460)
    root.mainloop()


def _quit(root: tk.Tk) -> None:
    view = getattr(root, "_airkeys_view", None)
    if view is not None:
        view.shutdown()
    root.destroy()


def _place(root: tk.Tk, width: int, height: int) -> None:
    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 3)
    root.geometry(f"{width}x{height}+{x}+{y}")


class ReceiverView(tk.Frame):
    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root, bg=BG)
        self.root = root
        self.pin = settings.receiver_pin()
        self.injector = None
        self.inject_error = ""
        try:
            self.injector = make_injector()
        except Exception as exc:
            self.inject_error = str(exc)
        self.server: Server | None = None
        self.audio = None
        self.beacon: Beacon | None = None
        self._closed = False
        self._inbox: queue.Queue = queue.Queue()

        box = tk.Frame(self, bg=BG)
        box.pack(expand=True)
        tk.Label(box, text="AirKeys", bg=BG, fg=INK, font=_font(self, 28, "bold")).pack()
        tk.Label(box, text="PIN", bg=BG, fg=MUTED, font=_font(self, 13)).pack(pady=(28, 0))
        tk.Label(box, text=" ".join(self.pin), bg=BG, fg=INK, font=_font(self, 42, "bold")).pack(pady=(4, 0))
        ips = local_ipv4()
        address = ips[0] if ips else "This computer"
        tk.Label(box, text=address, bg=BG, fg=MUTED, font=_font(self, 15)).pack(pady=(18, 0))
        self.status_var = tk.StringVar(value="Waiting")
        self.status_label = tk.Label(box, textvariable=self.status_var, bg=BG, fg=MUTED, font=_font(self, 17))
        self.status_label.pack(pady=(22, 0))
        self.audio_var = tk.StringVar(value="")
        tk.Label(box, textvariable=self.audio_var, bg=BG, fg=MUTED, font=_font(self, 13)).pack(pady=(8, 0))
        if self.inject_error:
            self.status_var.set(self.inject_error)
            return
        self._listen(address)
        self._tick()

    def _listen(self, address: str) -> None:
        try:
            self.server = Server(self.pin, self)
            self.server.start()
        except OSError as exc:
            self.status_var.set(str(exc))
            return
        try:
            from airkeys.audio_link import AudioServer

            self.audio = AudioServer(self.pin, on_status=self._audio_status)
            self.audio.start()
        except OSError:
            self.audio_var.set("Audio port is busy")
        try:
            self.beacon = Beacon(self.server.port, socket.gethostname(), DISCOVERY_PORT)
            self.beacon.start()
        except OSError:
            self.status_var.set(address)

    def _release_ports(self) -> None:
        if self.beacon is not None:
            self.beacon.stop()
            self.beacon = None
        if self.server is not None:
            self.server.stop()
            self.server = None
        if self.audio is not None:
            self.audio.stop()
            self.audio = None

    def _audio_status(self, text: str) -> None:
        self._inbox.put(("audio", text))

    def key(self, code: int, down: bool) -> None:
        if self.injector is not None:
            try:
                self.injector.press(code, down)
            except Exception:
                return
        if down:
            self._inbox.put(("status", "Connected"))

    def release_all(self) -> None:
        if self.injector is not None:
            try:
                self.injector.release_all()
            except Exception:
                return

    def status(self, text: str) -> None:
        self._inbox.put(("status", "Connected" if text.startswith("Connected") else "Waiting"))

    def _tick(self) -> None:
        if self._closed:
            return
        try:
            while True:
                kind, text = self._inbox.get_nowait()
                if kind == "status":
                    self.status_var.set(text)
                    self.status_label.configure(fg=BLUE if text == "Connected" else MUTED)
                elif kind == "audio":
                    self.audio_var.set(text)
        except queue.Empty:
            pass
        self.root.after(50, self._tick)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._release_ports()
        self.release_all()


class SenderView(tk.Frame):
    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root, bg=BG)
        self.root = root
        self.state = ShareState()
        self._closed = False
        self._inbox: queue.Queue = queue.Queue()
        self.peers: dict[tuple[str, int], str] = {}
        self.selected: tuple[str, int] | None = None
        self._rows: dict[tuple[str, int], tk.Frame] = {}
        self._connecting = False
        self._show_address = False
        saved = settings.load()
        self.map_cmd_to_ctrl = saved.get("map_cmd_to_ctrl", True) is not False

        from airkeys.grab_mac import Grabber

        self.grabber = Grabber(self.state, lambda: self.map_cmd_to_ctrl)
        self.client = Client(on_lost=self._on_lost)
        self.finder = Finder(self._found)
        self.finder.start()
        self.permitted = False

        self.column = tk.Frame(self, bg=BG)
        self.column.pack(fill="both", expand=True, padx=28, pady=36)

        self.title = tk.StringVar(value="AirKeys")
        tk.Label(self.column, textvariable=self.title, bg=BG, fg=INK, font=_font(self, 28, "bold")).pack(anchor="w")
        self.status = tk.StringVar(value="Looking for your PC")
        tk.Label(
            self.column,
            textvariable=self.status,
            bg=BG,
            fg=MUTED,
            font=_font(self, 14),
            wraplength=340,
            justify="left",
        ).pack(anchor="w", pady=(6, 18))

        self.perm = tk.Label(
            self.column,
            text="",
            bg=BG,
            fg=INK,
            font=_font(self, 12),
            wraplength=340,
            justify="left",
        )
        self.perm_button = _text_button(self.column, "Open Settings", self._open_privacy)

        self.list_card = tk.Frame(self.column, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        self.list_card.pack(fill="x")

        self.pin_label = tk.Label(self.column, text="PIN", bg=BG, fg=MUTED, font=_font(self, 12))
        self.pin = tk.Entry(
            self.column,
            relief="flat",
            bg=CARD,
            fg=INK,
            justify="center",
            font=_font(self, 26),
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            insertbackground=INK,
        )
        if isinstance(saved.get("last_pin"), str):
            self.pin.insert(0, saved["last_pin"])

        self.address = tk.Entry(
            self.column,
            relief="flat",
            bg=CARD,
            fg=INK,
            font=_font(self, 16),
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            insertbackground=INK,
        )
        if isinstance(saved.get("last_host"), str):
            self.address.insert(0, saved["last_host"])

        self.address_link = _text_button(self.column, "Enter an address", self._toggle_address)
        self.primary = _fill_button(self.column, "Connect", self._primary, BLUE)
        self.disconnect = _text_button(self.column, "Disconnect", self._disconnect)
        self._audio_on = False
        self._audio_starting = False
        self._audio_host = ""
        self._audio_pin = ""
        self.audio_link = _text_button(self.column, "Play PC audio", self._toggle_audio)
        self.audio_note = tk.StringVar(value="")
        self.audio_note_label = tk.Label(
            self.column,
            textvariable=self.audio_note,
            bg=BG,
            fg=MUTED,
            font=_font(self, 12),
            wraplength=340,
            justify="left",
        )
        from airkeys.audio_link import AudioClient

        self.audio_client = AudioClient(on_lost=self._audio_lost)

        self._check_permission()
        self._layout_idle()
        self._tick()

    def _check_permission(self) -> None:
        try:
            ok = self.grabber.ensure()
        except Exception as exc:
            self.grabber.permission_hint = str(exc)
            ok = False
        self.grabber.shutdown()
        self.permitted = ok
        if ok:
            self.perm.pack_forget()
            self.perm_button.pack_forget()
            return
        self.perm.configure(text=self.grabber.permission_hint)
        if not self.perm.winfo_ismapped():
            self.perm.pack(anchor="w", pady=(0, 8))
            self.perm_button.pack(anchor="w", pady=(0, 12))

    def _layout_idle(self) -> None:
        self.title.set("AirKeys")
        self.root.title("AirKeys")
        self.primary.set_text("Connect", BLUE)
        self.primary.pack_forget()
        self.disconnect.pack_forget()
        self.audio_link.pack_forget()
        self.audio_note_label.pack_forget()
        self.pin_label.pack_forget()
        self.pin.pack_forget()
        self.address.pack_forget()
        self.address_link.pack_forget()
        self.list_card.pack_forget()
        if self.peers:
            self.list_card.pack(fill="x")
        ready = bool(self.peers) or self._show_address
        if self._show_address:
            self.address.pack(fill="x", ipady=8, pady=(4, 0))
        if ready:
            self.pin_label.pack(anchor="w", pady=(16, 4))
            self.pin.pack(fill="x", ipady=6)
            self.primary.pack(fill="x", pady=(18, 0))
        if not self._show_address:
            self.address_link.pack(anchor="w", pady=(14, 0))
        if self.state.connected:
            self._layout_connected()

    def _layout_connected(self) -> None:
        self.list_card.pack_forget()
        self.pin_label.pack_forget()
        self.pin.pack_forget()
        self.address.pack_forget()
        self.address_link.pack_forget()
        self.primary.set_text("Share keyboard", BLUE)
        self.primary.pack(fill="x", pady=(8, 0))
        self._pack_audio()
        self.disconnect.pack(anchor="w", pady=(10, 0))
        name = self._target_name()
        self.status.set(name)

    def _layout_sharing(self) -> None:
        self.title.set("Sharing")
        self.root.title("Sharing")
        self.list_card.pack_forget()
        self.pin_label.pack_forget()
        self.pin.pack_forget()
        self.address.pack_forget()
        self.address_link.pack_forget()
        self.disconnect.pack_forget()
        self.primary.set_text("Stop", INK)
        self.primary.pack(fill="x", pady=(8, 0))
        self._pack_audio()
        self.status.set(self._target_name())

    def _pack_audio(self) -> None:
        self.audio_link.pack_forget()
        self.audio_note_label.pack_forget()
        self.audio_link.pack(anchor="w", pady=(12, 0))
        if self.audio_note.get():
            self.audio_note_label.pack(anchor="w", pady=(4, 0))

    def _toggle_audio(self) -> None:
        if self._audio_on or self._audio_starting:
            self._stop_audio()
            return
        if not self.state.connected or not self._audio_host or not self._audio_pin:
            return
        self._audio_starting = True
        self.audio_note.set("Starting PC audio")
        self._pack_audio()
        threading.Thread(target=self._audio_thread, daemon=True).start()

    def _audio_thread(self) -> None:
        from airkeys.audio import AudioError

        try:
            self.audio_client.connect(self._audio_host, self._audio_pin)
        except AuthError:
            if self._audio_starting:
                self._inbox.put(("audio-fail", "Wrong PIN"))
            return
        except AudioError as exc:
            if self._audio_starting:
                self._inbox.put(("audio-fail", str(exc)))
            return
        except OSError:
            if self._audio_starting:
                self._inbox.put(("audio-fail", "Could not play PC audio"))
            return
        if not self._audio_starting:
            self.audio_client.close()
            return
        self._inbox.put(("audio-on",))

    def _audio_lost(self, text: str) -> None:
        self._inbox.put(("audio-fail", text))

    def _stop_audio(self) -> None:
        self._audio_starting = False
        self._audio_on = False
        self.audio_client.close()
        self.audio_link.configure(text="Play PC audio")
        self.audio_note.set("")
        self.audio_note_label.pack_forget()

    def _target_name(self) -> str:
        if self.selected and self.selected in self.peers:
            return self.peers[self.selected]
        host = self.address.get().strip()
        return host or "Connected"

    def _toggle_address(self) -> None:
        self._show_address = True
        self._layout_idle()

    def _found(self, ip: str, port: int, name: str) -> None:
        self._inbox.put(("peer", ip, port, name))

    def _add_peer(self, ip: str, port: int, name: str) -> None:
        key = (ip, port)
        if self.peers.get(key) == name and key in self._rows:
            return
        first = not self.peers
        self.peers[key] = name
        if key not in self._rows:
            row = tk.Frame(self.list_card, bg=CARD, cursor="hand2")
            row.pack(fill="x")
            name_label = tk.Label(row, text=name, bg=CARD, fg=INK, font=_font(self, 17), anchor="w", padx=16, pady=0)
            name_label.pack(fill="x", pady=(14, 0))
            ip_label = tk.Label(row, text=ip, bg=CARD, fg=MUTED, font=_font(self, 12), anchor="w", padx=16)
            ip_label.pack(fill="x", pady=(2, 14))
            row.name_label = name_label
            row.ip_label = ip_label
            for widget in (row, name_label, ip_label):
                widget.bind("<Button-1>", lambda _e, key=key: self._select(key))
            self._rows[key] = row
        else:
            self._rows[key].name_label.configure(text=name)
        if self.selected is None:
            self._select(key)
        if first and not self.state.connected and not self.state.enabled:
            self.status.set("Enter the PIN shown on your PC")
            self._layout_idle()

    def _select(self, key: tuple[str, int]) -> None:
        self.selected = key
        for peer, row in self._rows.items():
            bg = SELECT if peer == key else CARD
            row.configure(bg=bg)
            row.name_label.configure(bg=bg)
            row.ip_label.configure(bg=bg)

    def _endpoint(self) -> tuple[str, int]:
        manual = self.address.get().strip() if self._show_address else ""
        if manual:
            return parse_host(manual, DEFAULT_PORT)
        if self.selected:
            return self.selected
        if len(self.peers) == 1:
            return next(iter(self.peers))
        raise ValueError("Still looking for your PC")

    def _primary(self) -> None:
        if self.state.enabled:
            self._set_sharing(False)
            return
        if self.state.connected:
            self._set_sharing(True)
            return
        self._connect()

    def _connect(self) -> None:
        if self._connecting:
            return
        try:
            host, port = self._endpoint()
        except ValueError as exc:
            self.status.set(str(exc))
            return
        pin = self.pin.get().strip()
        if len(pin) != 6 or not pin.isdigit():
            self.status.set("Enter the 6 digit PIN")
            return
        self._connecting = True
        self.status.set("Connecting")
        threading.Thread(target=self._connect_thread, args=(host, port, pin), daemon=True).start()

    def _connect_thread(self, host: str, port: int, pin: str) -> None:
        try:
            self.client.connect(host, port, pin)
        except AuthError:
            self._inbox.put(("fail", "Wrong PIN"))
            return
        except OSError:
            self._inbox.put(("fail", "Could not connect"))
            return
        self._inbox.put(("ok", host, port, pin))

    def _connect_ok(self, host: str, port: int, pin: str) -> None:
        self._connecting = False
        self.state.connected = True
        self.selected = (host, port)
        shown = host if port == DEFAULT_PORT else f"{host}:{port}"
        settings.update(last_host=shown, last_pin=pin, map_cmd_to_ctrl=True)
        self._audio_host = host
        self._audio_pin = pin
        self._layout_connected()

    def _connect_fail(self, text: str) -> None:
        self._connecting = False
        self.state.connected = False
        self.status.set(text)

    def _disconnect(self) -> None:
        self.state.enabled = False
        try:
            self.client.send_release()
        except OSError:
            pass
        self.grabber.shutdown()
        self.state.connected = False
        self.client.close()
        self._stop_audio()
        self.status.set("Enter the PIN shown on your PC" if self.peers else "Looking for your PC")
        self._layout_idle()

    def _set_sharing(self, on: bool) -> None:
        if on:
            if not self.state.connected:
                self.status.set("Connect first")
                return
            try:
                ready = self.grabber.ensure()
            except Exception as exc:
                self.status.set(str(exc))
                return
            if not ready:
                self.permitted = False
                self._check_permission()
                self.status.set("Allow Accessibility, then try again")
                return
            self.grabber.fuse.clear()
            self.state.enabled = True
            try:
                from airkeys.grab_mac import quiet_mac_modifiers

                quiet_mac_modifiers()
            except Exception:
                pass
            self._layout_sharing()
            return
        self._flush_keys()
        self.state.enabled = False
        try:
            self.client.send_release()
        except OSError:
            pass
        self.grabber.shutdown()
        if self.state.connected:
            self._layout_connected()
        else:
            self._layout_idle()

    def _flush_keys(self) -> None:
        pending = []
        while True:
            try:
                item = self.grabber.events.get_nowait()
            except queue.Empty:
                break
            if item[0] == "keys":
                pending.extend(item[1])
        for code, down in pending:
            try:
                self.client.send_key(code, down)
            except OSError:
                self.state.connected = False
                return

    def _on_lost(self) -> None:
        self.state.connected = False
        self.state.enabled = False
        self._inbox.put(("lost",))

    def _open_privacy(self) -> None:
        from airkeys.grab_mac import open_accessibility_settings

        open_accessibility_settings()
        self.status.set("After allowing access, click Share keyboard")

    def _tick(self) -> None:
        if self._closed:
            return
        try:
            self._drain()
        except Exception as exc:
            self.status.set(str(exc))
        self.root.after(16, self._tick)

    def _drain(self) -> None:
        while True:
            try:
                item = self.grabber.events.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "keys" and self.state.enabled:
                for code, down in item[1]:
                    try:
                        self.client.send_key(code, down)
                    except OSError:
                        self.state.connected = False
                        self.state.enabled = False
                        self._inbox.put(("lost",))
                        return
            elif kind == "stop":
                self._set_sharing(False)
            elif kind == "fuse":
                self._set_sharing(False)
                self.status.set("Sharing stopped")
        while True:
            try:
                item = self._inbox.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "peer" and not self.state.connected:
                _kind, ip, port, name = item
                self._add_peer(ip, port, name)
            elif kind == "ok":
                _kind, host, port, pin = item
                self._connect_ok(host, port, pin)
            elif kind == "fail":
                self._connect_fail(item[1])
            elif kind == "lost":
                self.grabber.shutdown()
                self._connecting = False
                self._stop_audio()
                self.status.set("Connection ended")
                self._layout_idle()
            elif kind == "audio-on":
                self._audio_starting = False
                self._audio_on = True
                self.audio_link.configure(text="Stop PC audio")
                self.audio_note.set("")
                if self.state.connected:
                    self._pack_audio()
            elif kind == "audio-fail":
                self._audio_starting = False
                self._audio_on = False
                self.audio_client.close()
                self.audio_link.configure(text="Play PC audio")
                self.audio_note.set(item[1] if self.state.connected else "")
                if self.state.connected:
                    self._pack_audio()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.state.enabled = False
        self.state.connected = False
        try:
            self.client.send_release()
        except OSError:
            pass
        self.client.close()
        self._stop_audio()
        self.finder.stop()
        self.grabber.shutdown()


def _fill_button(master, text: str, command, bg: str) -> "_Fill":
    return _Fill(master, text, command, bg)


def _text_button(master, text: str, command) -> tk.Label:
    # A native Mac button draws a white pill on a black box. A label does not.
    label = tk.Label(
        master,
        text=text,
        bg=BG,
        fg=BLUE,
        font=_font(master, 13),
        cursor="hand2",
        highlightthickness=0,
        bd=0,
        padx=0,
        pady=2,
    )
    label.bind("<Button-1>", lambda _event: command())
    return label


class _Fill(tk.Frame):
    def __init__(self, master, text: str, command, bg: str) -> None:
        super().__init__(master, bg=bg, cursor="hand2", highlightthickness=0)
        self.command = command
        self.label = tk.Label(
            self,
            text=text,
            bg=bg,
            fg="white",
            font=_font(master, 16, "bold"),
            pady=12,
        )
        self.label.pack(fill="x")
        self.bind("<Button-1>", self._fire)
        self.label.bind("<Button-1>", self._fire)

    def _fire(self, _event=None) -> None:
        if self.command:
            self.command()

    def set_text(self, text: str, bg: str) -> None:
        fg = "white" if bg != INK else "white"
        self.configure(bg=bg)
        self.label.configure(text=text, bg=bg, fg=fg)
