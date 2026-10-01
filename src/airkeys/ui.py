"""Windows for the Mac that shares a keyboard and the computer that receives it."""

from __future__ import annotations

import socket
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

from airkeys.discover import DISCOVERY_PORT, Beacon, Finder, local_ipv4, parse_host
from airkeys.inject import make_injector
from airkeys.link import DEFAULT_PORT, Client, Server
from airkeys.protocol import AuthError
from airkeys import settings

BG = "#f3f0e8"
INK = "#1c1915"
MUTED = "#5c564c"
GREEN = "#0e6b45"
RED = "#8f2433"
CARD = "#fffdf8"
LINE = "#ddd6c8"


class ShareState:
    def __init__(self) -> None:
        self.enabled = False
        self.connected = False

    def active(self) -> bool:
        return self.enabled and self.connected


class ClickButton(tk.Frame):
    def __init__(self, master, text: str, command, bg: str, fg: str = "white") -> None:
        super().__init__(master, bg=bg, cursor="hand2", highlightthickness=0)
        self.command = command
        self._bg = bg
        self.label = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=fg,
            padx=16,
            pady=12,
            font=master_font(master, 15, "bold"),
        )
        self.label.pack(fill="x")
        self.bind("<Button-1>", self._fire)
        self.label.bind("<Button-1>", self._fire)

    def _fire(self, _event=None) -> None:
        if self.command:
            self.command()

    def set_text(self, text: str, bg: str) -> None:
        self._bg = bg
        self.configure(bg=bg)
        self.label.configure(text=text, bg=bg)


def master_font(widget, size: int, weight: str = "normal") -> tuple:
    root = widget.winfo_toplevel()
    family = getattr(root, "_airkeys_font", "Helvetica")
    return (family, size, weight)


def run(role: str | None = None) -> None:
    root = tk.Tk()
    root.title("AirKeys")
    root.configure(bg=BG)
    families = set(tkfont.families(root))
    for name in ("Helvetica Neue", "Segoe UI", "Helvetica", "Arial"):
        if name in families:
            root._airkeys_font = name
            break
    else:
        root._airkeys_font = "Helvetica"
    root._airkeys_view = None
    if role == "send":
        _show_sender(root)
    elif role == "receive":
        _show_receiver(root)
    else:
        _show_chooser(root)
    root.protocol("WM_DELETE_WINDOW", lambda: _quit(root))
    root.mainloop()


def _quit(root: tk.Tk) -> None:
    view = getattr(root, "_airkeys_view", None)
    if view is not None:
        view.shutdown()
    root.destroy()


def _swap(root: tk.Tk, view: tk.Frame, width: int, height: int) -> None:
    current = getattr(root, "_airkeys_view", None)
    if current is not None:
        current.shutdown()
        current.destroy()
    root._airkeys_view = view
    view.pack(fill="both", expand=True)
    root.geometry(f"{width}x{height}")
    root.minsize(width, min(height, 560))
    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 3)
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.attributes("-topmost", False)
    root.title("AirKeys")


def _show_chooser(root: tk.Tk) -> None:
    _swap(root, Chooser(root), 460, 340)


def _show_sender(root: tk.Tk) -> None:
    if sys.platform != "darwin":
        messagebox.showinfo(
            "AirKeys",
            "The keyboard side runs on the Mac. On this computer, choose the receive side.",
        )
        _show_chooser(root)
        return
    _swap(root, SenderView(root), 500, 760)


def _show_receiver(root: tk.Tk) -> None:
    _swap(root, ReceiverView(root), 480, 560)


class Chooser(tk.Frame):
    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root, bg=BG, padx=28, pady=28)
        self.root = root
        tk.Label(self, text="AirKeys", bg=BG, fg=INK, font=master_font(self, 28, "bold")).pack(anchor="w")
        tk.Label(
            self,
            text="Use a MacBook keyboard on another computer over Wi-Fi.",
            bg=BG,
            fg=MUTED,
            font=master_font(self, 13),
            wraplength=400,
            justify="left",
        ).pack(anchor="w", pady=(8, 22))
        ClickButton(self, "This MacBook is the keyboard", lambda: _show_sender(root), GREEN).pack(fill="x")
        tk.Frame(self, height=10, bg=BG).pack()
        ClickButton(self, "This computer needs a keyboard", lambda: _show_receiver(root), INK).pack(fill="x")
        tk.Label(
            self,
            text="Both machines join the same Wi-Fi. Guest networks usually block this.",
            bg=BG,
            fg=MUTED,
            font=master_font(self, 11),
            wraplength=400,
            justify="left",
        ).pack(anchor="w", pady=(18, 0))

    def shutdown(self) -> None:
        return None


class ReceiverView(tk.Frame):
    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root, bg=BG, padx=28, pady=22)
        self.root = root
        self.pin = settings.receiver_pin()
        self.count = 0
        self.injector = None
        self.inject_error = ""
        try:
            self.injector = make_injector()
        except Exception as exc:
            self.inject_error = str(exc)
        self.server: Server | None = None
        self.beacon: Beacon | None = None
        self._closed = False

        tk.Label(self, text="Waiting for a Mac", bg=BG, fg=INK, font=master_font(self, 22, "bold")).pack(anchor="w")
        tk.Label(
            self,
            text="Leave this window open on the computer that has no keyboard.",
            bg=BG,
            fg=MUTED,
            font=master_font(self, 12),
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))

        card = tk.Frame(self, bg=CARD, highlightbackground=LINE, highlightthickness=1, padx=16, pady=12)
        card.pack(fill="x")
        tk.Label(card, text="PIN", bg=CARD, fg=MUTED, font=master_font(self, 11)).pack(anchor="w")
        self.pin_label = tk.Label(
            card,
            text=" ".join(self.pin),
            bg=CARD,
            fg=INK,
            font=master_font(self, 40, "bold"),
        )
        self.pin_label.pack(anchor="w", pady=(2, 6))
        row = tk.Frame(card, bg=CARD)
        row.pack(anchor="w")
        _small(row, "Copy PIN", self._copy_pin).pack(side="left")
        _small(row, "New PIN", self._new_pin).pack(side="left", padx=(8, 0))

        ips = local_ipv4()
        tk.Label(self, text="Address", bg=BG, fg=MUTED, font=master_font(self, 11)).pack(anchor="w", pady=(16, 4))
        shown = ", ".join(ips) if ips else "No network address yet"
        self.addr = tk.Entry(self, relief="flat", font=master_font(self, 14), readonlybackground=CARD, fg=INK)
        self.addr.insert(0, shown)
        self.addr.configure(state="readonly")
        self.addr.pack(fill="x", ipady=6)

        self.status_var = tk.StringVar(value="Waiting for the Mac.")
        tk.Label(
            self,
            textvariable=self.status_var,
            bg=BG,
            fg=INK,
            font=master_font(self, 13),
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=(16, 4))
        self.count_var = tk.StringVar(value="Keys received: 0")
        tk.Label(self, textvariable=self.count_var, bg=BG, fg=MUTED, font=master_font(self, 12)).pack(anchor="w")
        if self.inject_error:
            self.status_var.set(self.inject_error)

        tk.Label(
            self,
            text=f"This computer is {socket.gethostname()}. Keys type into whatever app is focused.",
            bg=BG,
            fg=MUTED,
            font=master_font(self, 11),
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=(16, 8))
        _small(self, "Back", lambda: _show_chooser(root)).pack(anchor="w")

        if self.inject_error:
            return
        try:
            self.server = Server(self.pin, self)
            self.server.start()
        except OSError as exc:
            self.status_var.set(f"Could not listen on port {DEFAULT_PORT}. {exc}")
            return
        try:
            self.beacon = Beacon(self.server.port, socket.gethostname(), DISCOVERY_PORT)
            self.beacon.start()
        except OSError:
            self.status_var.set(
                "Waiting for the Mac. Discovery is off because the port is busy. Type the address by hand on the Mac."
            )

    def key(self, code: int, down: bool) -> None:
        if self.injector is not None:
            self.injector.press(code, down)
        if down:
            self.count += 1
            self.root.after(0, self._show_count)

    def release_all(self) -> None:
        if self.injector is not None:
            self.injector.release_all()

    def status(self, text: str) -> None:
        if self._closed:
            return
        try:
            self.root.after(0, lambda text=text: self.status_var.set(text))
        except tk.TclError:
            return

    def _show_count(self) -> None:
        self.count_var.set(f"Keys received: {self.count}")

    def _copy_pin(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.pin)

    def _new_pin(self) -> None:
        pin = settings.new_pin()
        self.pin = pin
        self.pin_label.configure(text=" ".join(pin))
        if self.server is not None:
            self.server.pin = pin
            self.server.drop_client()
        self.status_var.set("New PIN ready. Connect again from the Mac.")

    def shutdown(self) -> None:
        self._closed = True
        if self.beacon is not None:
            self.beacon.stop()
            self.beacon = None
        if self.server is not None:
            self.server.stop()
            self.server = None
        self.release_all()


class SenderView(tk.Frame):
    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root, bg=BG, padx=28, pady=18)
        self.root = root
        self.state = ShareState()
        self._closed = False
        self._pump_id = None
        self.peers: dict[tuple[str, int], str] = {}
        saved = settings.load()

        from airkeys.grab_mac import Grabber

        self.grabber = Grabber(
            self.state,
            map_cmd=lambda: bool(self.map_cmd.get()),
            on_toggle=self._toggle_from_hotkey,
            on_forward=self._forward,
            on_fuse=self._trip_fuse,
        )
        self.client = Client(on_lost=self._on_lost)
        self.finder = Finder(self._found)
        self._tap_generation = 0
        self._connecting = False
        self.finder.start()

        tk.Label(self, text="MacBook keyboard", bg=BG, fg=INK, font=master_font(self, 22, "bold")).pack(anchor="w")
        tk.Label(
            self,
            text="The trackpad stays on this Mac. Only the keys are sent, and only while sharing is on.",
            bg=BG,
            fg=MUTED,
            font=master_font(self, 12),
            wraplength=440,
            justify="left",
        ).pack(anchor="w", pady=(4, 10))

        self.perm = tk.Text(
            self,
            height=4,
            wrap="word",
            relief="flat",
            bg="#f6e4cf",
            fg=INK,
            font=master_font(self, 11),
            highlightthickness=0,
        )
        self.perm_button = _small(self, "Open Accessibility settings", self._open_privacy)
        self._check_permission()

        tk.Label(self, text="Computers on this network", bg=BG, fg=MUTED, font=master_font(self, 11)).pack(anchor="w")
        self.listbox = tk.Listbox(
            self,
            height=4,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            font=master_font(self, 13),
            activestyle="none",
        )
        self.listbox.pack(fill="x", pady=(4, 4))
        self.listbox.bind("<<ListboxSelect>>", self._pick_peer)
        _small(self, "Search again", self._search_status).pack(anchor="w", pady=(0, 8))

        tk.Label(self, text="Address", bg=BG, fg=MUTED, font=master_font(self, 11)).pack(anchor="w")
        self.host = tk.Entry(self, relief="flat", font=master_font(self, 14), bg=CARD, fg=INK)
        self.host.pack(fill="x", ipady=6, pady=(4, 8))
        if isinstance(saved.get("last_host"), str):
            self.host.insert(0, saved["last_host"])

        tk.Label(self, text="PIN shown on the other screen", bg=BG, fg=MUTED, font=master_font(self, 11)).pack(anchor="w")
        self.pin = tk.Entry(self, relief="flat", font=master_font(self, 18), bg=CARD, fg=INK, justify="center")
        self.pin.pack(fill="x", ipady=4, pady=(4, 8))
        if isinstance(saved.get("last_pin"), str):
            self.pin.insert(0, saved["last_pin"])

        self.map_cmd = tk.BooleanVar(value=saved.get("map_cmd_to_ctrl", True) is not False)
        tk.Checkbutton(
            self,
            text="Command key acts as Ctrl",
            variable=self.map_cmd,
            bg=BG,
            fg=INK,
            activebackground=BG,
            selectcolor=CARD,
            font=master_font(self, 12),
        ).pack(anchor="w", pady=(0, 10))

        self.connect_button = ClickButton(self, "Connect", self._connect, INK)
        self.connect_button.pack(fill="x")
        tk.Frame(self, height=8, bg=BG).pack()
        self.share_button = ClickButton(self, "Start sharing", self._toggle_share, GREEN)
        self.share_button.pack(fill="x")

        self.status = tk.StringVar(value="Not connected.")
        tk.Label(
            self,
            textvariable=self.status,
            bg=BG,
            fg=INK,
            font=master_font(self, 12),
            wraplength=440,
            justify="left",
        ).pack(anchor="w", pady=(12, 4))
        tk.Label(
            self,
            text="Stop sharing with the trackpad, or press Control+Option+K.",
            bg=BG,
            fg=MUTED,
            font=master_font(self, 11),
            wraplength=440,
            justify="left",
        ).pack(anchor="w")
        _small(self, "Back", lambda: _show_chooser(root)).pack(anchor="w", pady=(8, 0))
        self._pump()

    def _check_permission(self) -> None:
        # Probe, then remove the tap. It is installed again only while sharing is on.
        try:
            ok = self.grabber.ensure()
        except Exception as exc:
            self.grabber.permission_hint = str(exc)
            ok = False
        self.grabber.shutdown()
        if ok:
            self.perm.pack_forget()
            self.perm_button.pack_forget()
            return
        self._show_permission_banner()

    def _show_permission_banner(self) -> None:
        self.perm.configure(state="normal")
        self.perm.delete("1.0", "end")
        self.perm.insert("1.0", self.grabber.permission_hint)
        self.perm.configure(state="disabled")
        if not self.perm.winfo_ismapped():
            self.perm.pack(fill="x", pady=(0, 6))
            self.perm_button.pack(anchor="w", pady=(0, 10))

    def _open_privacy(self) -> None:
        from airkeys.grab_mac import open_accessibility_settings

        open_accessibility_settings()
        self.status.set("After you allow access, click Start sharing again.")

    def _found(self, ip: str, port: int, name: str) -> None:
        if self._closed:
            return
        self.root.after(0, lambda ip=ip, port=port, name=name: self._add_peer(ip, port, name))

    def _add_peer(self, ip: str, port: int, name: str) -> None:
        key = (ip, port)
        if self.peers.get(key) == name:
            return
        self.peers[key] = name
        self._fill_list()

    def _fill_list(self) -> None:
        self.listbox.delete(0, "end")
        for (ip, port), name in self.peers.items():
            label = f"{name}  {ip}" if port == DEFAULT_PORT else f"{name}  {ip}:{port}"
            self.listbox.insert("end", label)

    def _pick_peer(self, _event=None) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        ip, port = list(self.peers.keys())[selection[0]]
        self.host.delete(0, "end")
        if port == DEFAULT_PORT:
            self.host.insert(0, ip)
        else:
            self.host.insert(0, f"{ip}:{port}")

    def _search_status(self) -> None:
        self.status.set("Searching the network. If nothing shows up, type the address from the other screen.")

    def _connect(self) -> None:
        if self._connecting:
            return
        if self.state.connected:
            self._disconnect()
            return
        try:
            host, port = parse_host(self.host.get(), DEFAULT_PORT)
        except ValueError as exc:
            self.status.set(str(exc))
            return
        pin = self.pin.get().strip()
        if len(pin) != 6 or not pin.isdigit():
            self.status.set("Enter the 6 digit PIN from the other screen.")
            return
        self._connecting = True
        self.status.set(f"Connecting to {host}...")
        self.connect_button.set_text("Connecting", MUTED)
        threading.Thread(target=self._connect_thread, args=(host, port, pin), daemon=True).start()

    def _connect_thread(self, host: str, port: int, pin: str) -> None:
        try:
            self.client.connect(host, port, pin)
        except AuthError as exc:
            self.root.after(0, lambda exc=exc: self._connect_failed(str(exc)))
            return
        except OSError as exc:
            self.root.after(0, lambda exc=exc: self._connect_failed(f"Could not connect to {host}. {exc}"))
            return
        self.root.after(0, lambda host=host, port=port, pin=pin: self._connect_ok(host, port, pin))

    def _connect_failed(self, text: str) -> None:
        self._connecting = False
        self.state.connected = False
        self.connect_button.set_text("Connect", INK)
        self.status.set(text)

    def _connect_ok(self, host: str, port: int, pin: str) -> None:
        self._connecting = False
        self.state.connected = True
        shown = host if port == DEFAULT_PORT else f"{host}:{port}"
        settings.update(last_host=shown, last_pin=pin, map_cmd_to_ctrl=bool(self.map_cmd.get()))
        self.connect_button.set_text("Disconnect", INK)
        self.status.set(f"Connected to {shown}. Start sharing when you want keys to go there.")

    def _disconnect(self) -> None:
        self._set_sharing(False)
        self.state.connected = False
        self.client.close()
        self.connect_button.set_text("Connect", INK)
        self.status.set("Disconnected. This keyboard is local.")

    def _toggle_share(self) -> None:
        self._set_sharing(not self.state.enabled)

    def _toggle_from_hotkey(self) -> None:
        self._set_sharing(not self.state.enabled)

    def _set_sharing(self, on: bool) -> None:
        if on:
            if not self.state.connected:
                self.status.set("Connect to the other computer before sharing.")
                return
            try:
                ready = self.grabber.ensure()
            except Exception as exc:
                self.status.set(str(exc))
                return
            if not ready:
                self._show_permission_banner()
                self.status.set("Allow Accessibility access, then start sharing again.")
                return
            # Invalidates a tap release that was queued when sharing last stopped.
            self._tap_generation += 1
            self.grabber.fuse.clear()
            self.state.enabled = True
            self.share_button.set_text("Stop sharing", RED)
            self.root.attributes("-topmost", True)
            self.root.title("AirKeys sharing")
            self.status.set("Sharing is on. Keys are going to the other computer.")
            settings.update(map_cmd_to_ctrl=bool(self.map_cmd.get()))
            return
        was = self.state.enabled
        self.state.enabled = False
        self._tap_generation += 1
        generation = self._tap_generation
        if was:
            try:
                self.client.send_release()
            except OSError:
                pass
        # Release the tap outside the key callback. A matching generation means
        # sharing was not turned straight back on.
        self.root.after(0, lambda generation=generation: self._release_tap(generation))
        self.share_button.set_text("Start sharing", GREEN)
        try:
            self.root.attributes("-topmost", False)
            self.root.title("AirKeys")
        except tk.TclError:
            return
        if was:
            self.status.set("Sharing is off. Keys stay on this Mac.")

    def _release_tap(self, generation: int) -> None:
        if self._closed or generation != self._tap_generation:
            return
        self.grabber.shutdown()

    def _forward(self, pairs: list[tuple[int, bool]]) -> None:
        for code, down in pairs:
            try:
                self.client.send_key(code, down)
            except OSError:
                self.state.connected = False
                self.state.enabled = False
                self.root.after(0, self._show_dropped)
                return

    def _show_dropped(self) -> None:
        if self._closed:
            return
        if not self.state.enabled:
            self.grabber.shutdown()
        self.share_button.set_text("Start sharing", GREEN)
        self.root.attributes("-topmost", False)
        self.root.title("AirKeys")
        self.connect_button.set_text("Connect", INK)
        self.status.set("Connection dropped. This keyboard is local again.")

    def _trip_fuse(self) -> None:
        self.state.enabled = False
        try:
            self.client.send_release()
        except OSError:
            pass
        self.root.after(0, self._show_fuse)

    def _show_fuse(self) -> None:
        if self._closed:
            return
        if not self.state.enabled:
            self.grabber.shutdown()
        self.share_button.set_text("Start sharing", GREEN)
        self.root.attributes("-topmost", False)
        self.root.title("AirKeys")
        self.status.set("Sharing stopped because keys were looping. This keyboard is local again.")

    def _on_lost(self) -> None:
        self.state.connected = False
        self.state.enabled = False
        if not self._closed:
            self.root.after(0, self._show_dropped)

    def _pump(self) -> None:
        if self._closed:
            return
        try:
            self.grabber.pump()
        except Exception as exc:
            self.status.set(f"Keyboard capture error: {exc}")
        self._pump_id = self.root.after(8, self._pump)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.state.enabled = False
        self.state.connected = False
        if self._pump_id is not None:
            try:
                self.root.after_cancel(self._pump_id)
            except tk.TclError:
                pass
        try:
            self.client.send_release()
        except OSError:
            pass
        self.client.close()
        self.finder.stop()
        self.grabber.shutdown()


def _small(master, text: str, command) -> tk.Button:
    return tk.Button(
        master,
        text=text,
        command=command,
        relief="flat",
        bg=BG,
        fg=INK,
        activebackground=BG,
        font=master_font(master, 11),
        padx=0,
    )
