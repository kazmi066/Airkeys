import threading
import unittest

from airkeys.audio import AudioError, frame_size, pack_pcm
from airkeys.audio_link import AudioClient, AudioServer
from airkeys.protocol import AuthError


def _tone(stop: threading.Event):
    yield b"\x10\x00\xf0\xff" * 12
    stop.wait(2)


def _no_device(_stop: threading.Event):
    raise AudioError("This PC has no playback device")
    yield b""


class AudioTests(unittest.TestCase):
    def test_frame_roundtrip(self) -> None:
        payload = b"\x01\x00\x02\x00" * 8
        packed = pack_pcm(payload)
        self.assertEqual(frame_size(packed[:4]), len(payload))
        self.assertEqual(packed[4:], payload)
        with self.assertRaises(AudioError):
            pack_pcm(b"\x00")

    def test_stream_reaches_the_mac(self) -> None:
        notes: list[str] = []
        server = AudioServer("361549", host="127.0.0.1", port=0, frames=_tone, on_status=notes.append)
        server.start()
        got: list[bytes] = []
        done = threading.Event()

        def on_pcm(pcm: bytes) -> None:
            got.append(pcm)
            done.set()

        client = AudioClient(on_pcm=on_pcm, play=False)
        try:
            client.connect("127.0.0.1", "361549", port=server.port)
            self.assertTrue(done.wait(2))
            self.assertEqual(got[0], b"\x10\x00\xf0\xff" * 12)
            self.assertIn("Sending audio", notes)
        finally:
            client.close()
            server.stop()

    def test_missing_playback_device(self) -> None:
        server = AudioServer("361549", host="127.0.0.1", port=0, frames=_no_device)
        server.start()
        client = AudioClient(play=False)
        try:
            with self.assertRaises(AudioError) as caught:
                client.connect("127.0.0.1", "361549", port=server.port)
            self.assertIn("playback device", str(caught.exception))
        finally:
            client.close()
            server.stop()

    def test_wrong_pin(self) -> None:
        server = AudioServer("361549", host="127.0.0.1", port=0, frames=_tone)
        server.start()
        client = AudioClient(play=False)
        try:
            with self.assertRaises(AuthError):
                client.connect("127.0.0.1", "000000", port=server.port)
        finally:
            client.close()
            server.stop()


if __name__ == "__main__":
    unittest.main()
