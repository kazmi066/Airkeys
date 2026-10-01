"""Capture the PC mix and play it on the Mac.

Windows loopback records whatever is sent to the default speaker. A PC with
no playback device at all has nothing to capture until a virtual cable exists.
"""

from __future__ import annotations

from airkeys.audio import CHANNELS, CHUNK_FRAMES, RATE, AudioError

INSTALL = "Audio needs an extra install. From the airkeys folder run: python3 -m pip install soundcard"
NO_DEVICE = (
    "This PC has no playback device. Install VB-Audio Cable, set it as the default speaker, and try again."
)


def _imports():
    try:
        import numpy
        import soundcard as sc
    except ImportError as exc:
        raise AudioError(INSTALL) from exc
    return numpy, sc


def find_loopback():
    _numpy, sc = _imports()
    try:
        speaker = sc.default_speaker()
    except Exception as exc:
        raise AudioError(NO_DEVICE) from exc
    loops = [mic for mic in _microphones(sc) if getattr(mic, "isloopback", False)]
    if not loops:
        try:
            found = sc.get_microphone(speaker.name, include_loopback=True)
        except Exception:
            found = None
        if found is not None and getattr(found, "isloopback", False):
            loops = [found]
    if not loops:
        raise AudioError(NO_DEVICE)
    speaker_name = getattr(speaker, "name", "") or ""
    for mic in loops:
        if speaker_name and speaker_name in (getattr(mic, "name", "") or ""):
            return mic
    return loops[0]


def _microphones(sc):
    try:
        return list(sc.all_microphones(include_loopback=True))
    except TypeError:
        return list(sc.all_microphones())


def capture_frames(stop):
    numpy, _sc = _imports()
    mic = find_loopback()
    with mic.recorder(RATE, channels=CHANNELS, blocksize=512) as recorder:
        while not stop.is_set():
            data = recorder.record(numframes=CHUNK_FRAMES)
            yield _to_s16(numpy, data)


def play_pcm(player, pcm: bytes) -> None:
    numpy, _sc = _imports()
    player.play(_to_float(numpy, pcm))


def open_player():
    _numpy, sc = _imports()
    try:
        speaker = sc.default_speaker()
    except Exception as exc:
        raise AudioError("This Mac has no speaker to play on.") from exc
    return speaker.player(RATE, channels=CHANNELS, blocksize=512)


def _to_s16(numpy, data) -> bytes:
    array = numpy.asarray(data, dtype=numpy.float32)
    if array.ndim == 1:
        array = array.reshape(-1, 1)
    if array.shape[1] == 1:
        array = numpy.repeat(array, CHANNELS, axis=1)
    elif array.shape[1] > CHANNELS:
        array = array[:, :CHANNELS]
    clipped = numpy.clip(array, -1.0, 1.0)
    return (clipped * 32767.0).astype(numpy.int16).tobytes()


def _to_float(numpy, pcm: bytes):
    samples = numpy.frombuffer(pcm, dtype=numpy.int16)
    usable = samples.size - (samples.size % CHANNELS)
    frames = samples[:usable].reshape(-1, CHANNELS).astype(numpy.float32)
    return frames / 32767.0
