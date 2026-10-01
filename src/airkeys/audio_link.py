"""Listen for one Mac and send the PC mix. The keyboard socket stays separate."""

from __future__ import annotations

import queue
import socket
import threading
import time
from collections.abc import Callable, Iterator

from airkeys.audio import AUDIO_PORT, pack_pcm, read_exact, read_line, frame_size, AudioError
from airkeys.link import listen_socket
from airkeys.protocol import AuthError, decode_line, encode, pins_match

Frames = Callable[[threading.Event], Iterator[bytes]]


class AudioServer:
    def __init__(self, pin: str, host: str = "0.0.0.0", port: int = AUDIO_PORT, frames: Frames | None = None, on_status: Callable[[str], None] | None = None) -> None:
        self.pin = pin
        self.host = host
        self.port = port
        self._frames = frames or _device_frames
        self._on_status = on_status or (lambda _text: None)
        self._stop = threading.Event()
        self._client_stop = threading.Event()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._active: socket.socket | None = None
        self._lock = threading.Lock()
        self._fails: dict[str, tuple[int, float]] = {}

    def start(self) -> int:
        sock = listen_socket(self.host, self.port)
        self.port = sock.getsockname()[1]
        self._sock = sock
        self._thread = threading.Thread(target=self._accept_loop, name="airkeys-audio", daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self._stop.set()
        self._client_stop.set()
        self._close_active()
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.5)

    def _accept_loop(self) -> None:
        sock = self._sock
        if sock is None:
            return
        sock.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle(conn, addr[0])
            except Exception:
                continue

    def _handle(self, conn: socket.socket, ip: str) -> None:
        self._client_stop.set()
        self._close_active()
        self._client_stop = threading.Event()
        with self._lock:
            self._active = conn
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.settimeout(5)
            if self._locked(ip):
                conn.sendall(encode({"op": "deny"}))
                return
            line, _rest = read_line(conn)
            msg = decode_line(line)
            if msg.get("op") != "auth" or not pins_match(msg.get("pin"), self.pin):
                self._note_failure(ip)
                time.sleep(0.3)
                conn.sendall(encode({"op": "deny"}))
                return
            self._fails.pop(ip, None)
            self._stream(conn)
        except (OSError, AudioError, ConnectionError):
            return
        finally:
            with self._lock:
                if self._active is conn:
                    self._active = None
            self._note("")
            try:
                conn.close()
            except OSError:
                pass

    def _stream(self, conn: socket.socket) -> None:
        try:
            frames = iter(self._frames(self._client_stop))
            first = next(frames)
        except StopIteration:
            conn.sendall(encode({"op": "ok"}))
            return
        except AudioError as exc:
            conn.sendall(encode({"op": "err", "text": str(exc)}))
            return
        except Exception:
            conn.sendall(encode({"op": "err", "text": "Could not capture PC audio"}))
            return
        conn.sendall(encode({"op": "ok"}))
        conn.settimeout(None)
        self._note("Sending audio")
        conn.sendall(pack_pcm(first))
        for pcm in frames:
            if self._client_stop.is_set() or self._stop.is_set():
                return
            conn.sendall(pack_pcm(pcm))

    def _note(self, text: str) -> None:
        try:
            self._on_status(text)
        except Exception:
            return

    def _close_active(self) -> None:
        with self._lock:
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

    def _locked(self, ip: str) -> bool:
        count, until = self._fails.get(ip, (0, 0.0))
        if time.monotonic() < until:
            return True
        if until:
            self._fails[ip] = (0, 0.0)
        return False

    def _note_failure(self, ip: str) -> None:
        count, _until = self._fails.get(ip, (0, 0.0))
        count += 1
        if count >= 8:
            self._fails[ip] = (0, time.monotonic() + 60)
        else:
            self._fails[ip] = (count, 0.0)


class AudioClient:
    def __init__(self, on_lost: Callable[[str], None] | None = None, on_pcm: Callable[[bytes], None] | None = None, play: bool = True) -> None:
        self.on_lost = on_lost
        self.on_pcm = on_pcm
        self.play = play
        self.playing = False
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._play_thread: threading.Thread | None = None
        self._queue: queue.Queue = queue.Queue(maxsize=6)
        self._lost_once = False

    def connect(self, host: str, pin: str, port: int = AUDIO_PORT, timeout: float = 5) -> None:
        self.close()
        self._stop = threading.Event()
        self._queue = queue.Queue(maxsize=6)
        self._lost_once = False
        sock = socket.create_connection((host, port), timeout=timeout)
        pending = b""
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(timeout)
            sock.sendall(encode({"op": "auth", "pin": pin}))
            line, pending = read_line(sock, pending)
            msg = decode_line(line)
        except Exception:
            sock.close()
            raise
        op = msg.get("op")
        if op == "err":
            sock.close()
            raise AudioError(str(msg.get("text") or "Could not play PC audio"))
        if op != "ok":
            sock.close()
            raise AuthError("That PIN was refused.")
        sock.settimeout(2)
        self._sock = sock
        self.playing = True
        self._pending = pending
        if self.play:
            self._play_thread = threading.Thread(target=self._play_loop, name="airkeys-play", daemon=True)
            self._play_thread.start()
        self._thread = threading.Thread(target=self._read_loop, name="airkeys-audio-in", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self.playing = False
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
        for thread in (self._thread, self._play_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=1)
        self._thread = None
        self._play_thread = None

    def _read_loop(self) -> None:
        sock = self._sock
        pending = getattr(self, "_pending", b"")
        if sock is None:
            return
        try:
            while not self._stop.is_set():
                header, pending = read_exact(sock, 4, pending)
                payload, pending = read_exact(sock, frame_size(header), pending)
                self._emit(payload)
        except (OSError, AudioError, ConnectionError, TimeoutError):
            self._fail("PC audio stopped")

    def _emit(self, payload: bytes) -> None:
        if self.on_pcm is not None:
            try:
                self.on_pcm(payload)
            except Exception:
                pass
        if not self.play:
            return
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(payload)
            except queue.Full:
                pass

    def _play_loop(self) -> None:
        try:
            from airkeys.audio_io import open_player, play_pcm
        except AudioError as exc:
            self._fail(str(exc))
            return
        try:
            opened = open_player()
        except AudioError as exc:
            self._fail(str(exc))
            return
        except Exception as exc:
            self._fail(str(exc))
            return
        with opened as player:
            while not self._stop.is_set():
                try:
                    pcm = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    play_pcm(player, pcm)
                except Exception:
                    self._fail("PC audio stopped")
                    return

    def _fail(self, text: str) -> None:
        if self._lost_once or self._stop.is_set():
            self.playing = False
            return
        self._lost_once = True
        self.playing = False
        if self.on_lost is not None:
            try:
                self.on_lost(text)
            except Exception:
                return


def _device_frames(stop: threading.Event):
    from airkeys.audio_io import capture_frames

    yield from capture_frames(stop)
