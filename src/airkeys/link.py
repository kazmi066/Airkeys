"""TCP session between the Mac keyboard and the computer that receives keys."""

from __future__ import annotations

import queue
import socket
import threading
import time
from typing import Callable, Protocol

from airkeys.protocol import AuthError, ProtocolError, decode_line, encode, parse_key, pins_match

DEFAULT_PORT = 47777
HEARTBEAT_S = 2.0
READ_TIMEOUT_S = 8.0


def listen_socket(host: str, port: int) -> socket.socket:
    """Bind a listening socket. An admin relaunch retries while the old process lets go of the port."""
    import os

    attempts = 12 if os.environ.get("AIRKEYS_ELEVATED_HANDOFF") == "1" else 1
    error: OSError | None = None
    for attempt in range(attempts):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            sock.listen(1)
            return sock
        except OSError as exc:
            error = exc
            sock.close()
            if attempt + 1 == attempts:
                raise
            time.sleep(0.25)
    raise error or OSError("could not listen")


class KeySink(Protocol):
    def key(self, code: int, down: bool) -> None: ...

    def release_all(self) -> None: ...

    def status(self, text: str) -> None: ...


class Server:
    def __init__(self, pin: str, sink: KeySink, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        self.pin = pin
        self.sink = sink
        self.host = host
        self.port = port
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._fails: dict[str, tuple[int, float]] = {}
        self._active: socket.socket | None = None
        self._active_lock = threading.Lock()

    def start(self) -> int:
        sock = listen_socket(self.host, self.port)
        self.port = sock.getsockname()[1]
        self._sock = sock
        self._thread = threading.Thread(target=self._accept_loop, name="airkeys-accept", daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self._stop.set()
        self.drop_client()
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.5)
        self.sink.release_all()

    def drop_client(self) -> None:
        with self._active_lock:
            conn = self._active
            self._active = None
        if conn is None:
            return
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass

    def _accept_loop(self) -> None:
        sock = self._sock
        if sock is None:
            return
        while not self._stop.is_set():
            try:
                sock.settimeout(0.5)
                conn, addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle_client(conn, addr[0])
            except Exception:
                continue

    def _locked(self, ip: str) -> bool:
        count, until = self._fails.get(ip, (0, 0.0))
        if time.monotonic() < until:
            return True
        if until and time.monotonic() >= until:
            self._fails[ip] = (0, 0.0)
        return False

    def _note_failure(self, ip: str) -> None:
        count, _until = self._fails.get(ip, (0, 0.0))
        count += 1
        if count >= 8:
            self._fails[ip] = (0, time.monotonic() + 60)
        else:
            self._fails[ip] = (count, 0.0)

    def _tell(self, text: str) -> None:
        try:
            self.sink.status(text)
        except Exception:
            return

    def _handle_client(self, conn: socket.socket, ip: str) -> None:
        with self._active_lock:
            self._active = conn
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if self._locked(ip):
                _send(conn, {"op": "deny"})
                return
            conn.settimeout(5)
            msg = _read_one(conn)
            if msg.get("op") != "auth" or not pins_match(msg.get("pin"), self.pin):
                self._note_failure(ip)
                time.sleep(0.3)
                _send(conn, {"op": "deny"})
                self._tell("A connection used the wrong PIN.")
                return
            self._fails.pop(ip, None)
            _send(conn, {"op": "ok"})
            self._tell(f"Connected to {ip}. Type into the focused app.")
            self._read_session(conn)
        except (OSError, ProtocolError, TimeoutError):
            self._tell("Waiting for the Mac.")
        finally:
            with self._active_lock:
                if self._active is conn:
                    self._active = None
            self.sink.release_all()
            try:
                conn.close()
            except OSError:
                pass

    def _read_session(self, conn: socket.socket) -> None:
        buf = b""
        conn.settimeout(READ_TIMEOUT_S)
        while not self._stop.is_set():
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                self.sink.release_all()
                self._tell("The Mac went quiet. Held keys were released.")
                return
            except OSError:
                return
            if not chunk:
                self._tell("Waiting for the Mac.")
                return
            buf += chunk
            if len(buf) > 65536:
                return
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line:
                    continue
                try:
                    msg = decode_line(line)
                except ProtocolError:
                    continue
                op = msg.get("op")
                if op == "ping":
                    continue
                if op == "release":
                    self.sink.release_all()
                    continue
                parsed = parse_key(msg)
                if parsed is not None:
                    code, down = parsed
                    self.sink.key(code, down)


class Client:
    def __init__(self, on_lost: Callable[[], None] | None = None) -> None:
        self.on_lost = on_lost
        self.connected = False
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._out: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None
        self._writer: threading.Thread | None = None
        self._heart: threading.Thread | None = None
        self._lost_once = False

    def connect(self, host: str, port: int, pin: str, timeout: float = 5) -> None:
        self.close()
        self._stop = threading.Event()
        self._out = queue.Queue()
        self._lost_once = False
        sock = socket.create_connection((host, port), timeout=timeout)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(timeout)
            _send(sock, {"op": "auth", "pin": pin})
            msg = _read_one(sock)
        except Exception:
            sock.close()
            raise
        if msg.get("op") != "ok":
            sock.close()
            raise AuthError("That PIN was refused.")
        sock.settimeout(None)
        self._sock = sock
        self.connected = True
        self._reader = threading.Thread(target=self._read_loop, name="airkeys-reader", daemon=True)
        self._writer = threading.Thread(target=self._write_loop, name="airkeys-writer", daemon=True)
        self._heart = threading.Thread(target=self._heartbeat, name="airkeys-heartbeat", daemon=True)
        self._reader.start()
        self._writer.start()
        self._heart.start()

    def send_key(self, code: int, down: bool) -> None:
        self._enqueue({"op": "key", "code": int(code), "down": bool(down)})

    def send_release(self) -> None:
        if self._sock is None:
            return
        try:
            self._enqueue({"op": "release"})
        except OSError:
            self._lost()

    def close(self) -> None:
        self._stop.set()
        self.connected = False
        try:
            self._out.put_nowait(None)
        except Exception:
            pass
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        for thread in (self._reader, self._writer, self._heart):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=1)
        self._reader = None
        self._writer = None
        self._heart = None

    def _enqueue(self, payload: dict) -> None:
        if self._sock is None or not self.connected:
            raise OSError("not connected")
        self._out.put(payload)

    def _write_loop(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._out.get(timeout=0.2)
            except queue.Empty:
                continue
            if payload is None or self._stop.is_set():
                return
            sock = self._sock
            if sock is None:
                return
            try:
                _send(sock, payload)
            except OSError:
                self._lost()
                return

    def _heartbeat(self) -> None:
        while not self._stop.wait(HEARTBEAT_S):
            try:
                self._enqueue({"op": "ping"})
            except OSError:
                self._lost()
                return

    def _read_loop(self) -> None:
        sock = self._sock
        if sock is None:
            return
        try:
            while not self._stop.is_set():
                chunk = sock.recv(4096)
                if not chunk:
                    break
        except OSError:
            pass
        self._lost()

    def _lost(self) -> None:
        if self._lost_once or self._stop.is_set():
            self.connected = False
            return
        self._lost_once = True
        self.connected = False
        if self.on_lost is not None:
            try:
                self.on_lost()
            except Exception:
                return


def _send(sock: socket.socket, payload: dict) -> None:
    sock.sendall(encode(payload))


def _read_one(sock: socket.socket) -> dict:
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed")
        buf += chunk
        if len(buf) > 8192:
            raise ProtocolError("message is too long")
    line, _rest = buf.split(b"\n", 1)
    return decode_line(line)
