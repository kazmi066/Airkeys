"""Find the computer that is waiting for a keyboard, without typing its address."""

from __future__ import annotations

import socket
import threading
import time

DISCOVERY_PORT = 47778
PROBE = b"AIRKEYS?\n"


def safe_name(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch.isprintable() and ch not in "\r\n")
    cleaned = " ".join(cleaned.split())
    return (cleaned or "computer")[:40]


def beacon_reply(payload: bytes, tcp_port: int, name: str) -> bytes | None:
    if payload.strip() != b"AIRKEYS?":
        return None
    return f"AIRKEYS 1 {tcp_port} {safe_name(name)}\n".encode("utf-8")


def parse_beacon(payload: bytes) -> tuple[int, str] | None:
    try:
        text = payload.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    parts = text.split(" ", 3)
    if len(parts) != 4 or parts[0] != "AIRKEYS" or parts[1] != "1":
        return None
    try:
        port = int(parts[2])
    except ValueError:
        return None
    if not 0 < port < 65536 or not parts[3]:
        return None
    return port, parts[3]


def local_ipv4() -> list[str]:
    found: list[str] = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.2)
        # UDP connect picks the outbound interface and does not send a packet.
        sock.connect(("192.0.2.1", 9))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            found.append(ip)
    except OSError:
        pass
    try:
        for res in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = res[4][0]
            if not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


def parse_host(text: str, default_port: int) -> tuple[str, int]:
    raw = text.strip()
    if not raw:
        raise ValueError("Enter the address shown on the other computer.")
    if ":" in raw:
        host, port_text = raw.rsplit(":", 1)
        try:
            port = int(port_text)
        except ValueError as exc:
            raise ValueError("The port after the colon is not a number.") from exc
        if not 0 < port < 65536:
            raise ValueError("The port is out of range.")
        if not host:
            raise ValueError("Enter the address shown on the other computer.")
        return host, port
    return raw, default_port


def ask(ip: str, udp_port: int = DISCOVERY_PORT, timeout: float = 0.6) -> tuple[int, str] | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(PROBE, (ip, udp_port))
        data, _addr = sock.recvfrom(512)
    except (TimeoutError, OSError):
        return None
    finally:
        sock.close()
    return parse_beacon(data)


class Beacon:
    """Answer discovery probes on the computer that receives typing."""

    def __init__(self, tcp_port: int, name: str, udp_port: int = DISCOVERY_PORT) -> None:
        self.tcp_port = tcp_port
        self.name = safe_name(name)
        self.udp_port = udp_port
        self.error = ""
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self.udp_port))
        self.udp_port = sock.getsockname()[1]
        sock.settimeout(0.4)
        self._sock = sock
        self._thread = threading.Thread(target=self._run, name="airkeys-beacon", daemon=True)
        self._thread.start()
        return self.udp_port

    def stop(self) -> None:
        self._stop.set()
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1)

    def _run(self) -> None:
        sock = self._sock
        if sock is None:
            return
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(512)
            except socket.timeout:
                continue
            except OSError:
                break
            reply = beacon_reply(data, self.tcp_port, self.name)
            if reply:
                try:
                    sock.sendto(reply, addr)
                except OSError:
                    break


class Finder(threading.Thread):
    """Broadcast a probe and report every computer that answers."""

    def __init__(self, on_peer, udp_port: int = DISCOVERY_PORT) -> None:
        super().__init__(name="airkeys-finder", daemon=True)
        self.on_peer = on_peer
        self.udp_port = udp_port
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", 0))
            sock.settimeout(0.3)
            while not self._stop.is_set():
                try:
                    sock.sendto(PROBE, ("255.255.255.255", self.udp_port))
                except OSError:
                    pass
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline and not self._stop.is_set():
                    try:
                        data, addr = sock.recvfrom(512)
                    except socket.timeout:
                        continue
                    except OSError:
                        return
                    parsed = parse_beacon(data)
                    if parsed:
                        port, name = parsed
                        self.on_peer(addr[0], port, name)
        finally:
            sock.close()
