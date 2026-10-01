"""PC audio frames on their own socket, so sound never blocks the keyboard."""

from __future__ import annotations

import socket

AUDIO_PORT = 47779
RATE = 48000
CHANNELS = 2
CHUNK_FRAMES = 256
MAX_FRAME = 16384


class AudioError(Exception):
    pass


def pack_pcm(payload: bytes) -> bytes:
    if not payload or len(payload) > MAX_FRAME or len(payload) % (CHANNELS * 2):
        raise AudioError("bad audio frame")
    return len(payload).to_bytes(4, "little") + payload


def frame_size(header: bytes) -> int:
    if len(header) != 4:
        raise AudioError("bad audio frame")
    size = int.from_bytes(header, "little")
    if size <= 0 or size > MAX_FRAME or size % (CHANNELS * 2):
        raise AudioError("bad audio frame")
    return size


def read_exact(sock: socket.socket, size: int, pending: bytes = b"") -> tuple[bytes, bytes]:
    buf = pending
    while len(buf) < size:
        chunk = sock.recv(max(4096, size - len(buf)))
        if not chunk:
            raise ConnectionError("connection closed")
        buf += chunk
    return buf[:size], buf[size:]


def read_line(sock: socket.socket, pending: bytes = b"") -> tuple[bytes, bytes]:
    buf = pending
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed")
        buf += chunk
        if len(buf) > 8192:
            raise AudioError("bad audio frame")
    line, rest = buf.split(b"\n", 1)
    return line, rest
