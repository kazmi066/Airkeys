import unittest

from airkeys.protocol import ProtocolError, decode_line, encode, parse_key, pins_match


class ProtocolTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        raw = encode({"op": "key", "code": 12, "down": True})
        self.assertTrue(raw.endswith(b"\n"))
        msg = decode_line(raw[:-1])
        self.assertEqual(msg["v"], 1)
        self.assertEqual(parse_key(msg), (12, True))

    def test_pin(self) -> None:
        self.assertTrue(pins_match("004821", "004821"))
        self.assertFalse(pins_match("004821", "004822"))
        self.assertFalse(pins_match("00482", "004821"))
        self.assertFalse(pins_match(4821, "004821"))

    def test_rejects_junk(self) -> None:
        with self.assertRaises(ProtocolError):
            decode_line(b"not-json")
        with self.assertRaises(ProtocolError):
            decode_line(b'{"v":2,"op":"ping"}')
        self.assertIsNone(parse_key({"op": "key", "code": True, "down": True}))
        self.assertIsNone(parse_key({"op": "key", "code": 9999, "down": 1}))
        self.assertEqual(parse_key({"op": "key", "code": 4, "down": 0}), (4, False))


if __name__ == "__main__":
    unittest.main()
