import time
import unittest

from airkeys.discover import Beacon, ask, beacon_reply, parse_beacon, parse_host
from airkeys.link import Client, Server
from airkeys.protocol import AuthError


class ListSink:
    def __init__(self) -> None:
        self.keys: list[tuple[int, bool]] = []
        self.notes: list[str] = []
        self.released = 0

    def key(self, code: int, down: bool) -> None:
        self.keys.append((code, down))

    def release_all(self) -> None:
        self.released += 1

    def status(self, text: str) -> None:
        self.notes.append(text)


class DiscoverTests(unittest.TestCase):
    def test_beacon_text(self) -> None:
        reply = beacon_reply(b"AIRKEYS?\n", 47777, "Desk PC")
        self.assertEqual(parse_beacon(reply or b""), (47777, "Desk PC"))
        self.assertIsNone(beacon_reply(b"nope", 1, "x"))
        self.assertIsNone(parse_beacon(b"AIRKEYS 2 1 name"))

    def test_parse_host(self) -> None:
        self.assertEqual(parse_host("192.168.1.20", 47777), ("192.168.1.20", 47777))
        self.assertEqual(parse_host("192.168.1.20:5000", 47777), ("192.168.1.20", 5000))
        with self.assertRaises(ValueError):
            parse_host("   ", 47777)

    def test_udp_roundtrip(self) -> None:
        beacon = Beacon(4321, "Desk", udp_port=0)
        beacon.start()
        try:
            found = None
            for _ in range(20):
                found = ask("127.0.0.1", beacon.udp_port, timeout=0.2)
                if found:
                    break
                time.sleep(0.05)
            self.assertEqual(found, (4321, "Desk"))
        finally:
            beacon.stop()


class LinkTests(unittest.TestCase):
    def test_key_roundtrip(self) -> None:
        sink = ListSink()
        server = Server("111111", sink, host="127.0.0.1", port=0)
        server.start()
        client = Client()
        try:
            client.connect("127.0.0.1", server.port, "111111")
            client.send_key(0, True)
            client.send_key(0, False)
            deadline = time.time() + 2
            while time.time() < deadline and len(sink.keys) < 2:
                time.sleep(0.01)
            self.assertEqual(sink.keys, [(0, True), (0, False)])
            self.assertTrue(any("Connected" in note for note in sink.notes))
        finally:
            client.close()
            server.stop()

    def test_bad_pin(self) -> None:
        sink = ListSink()
        server = Server("111111", sink, host="127.0.0.1", port=0)
        server.start()
        client = Client()
        try:
            with self.assertRaises(AuthError):
                client.connect("127.0.0.1", server.port, "000000")
        finally:
            client.close()
            server.stop()


if __name__ == "__main__":
    unittest.main()
