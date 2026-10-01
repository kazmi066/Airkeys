import unittest

from airkeys.keymap import KEYS, linux_parts, remap_command

PYNPUT_KEYS = {
    "alt",
    "alt_r",
    "backspace",
    "caps_lock",
    "cmd",
    "cmd_r",
    "ctrl",
    "ctrl_r",
    "delete",
    "down",
    "end",
    "enter",
    "esc",
    "f1",
    "f2",
    "f3",
    "f4",
    "f5",
    "f6",
    "f7",
    "f8",
    "f9",
    "f10",
    "f11",
    "f12",
    "home",
    "insert",
    "left",
    "page_down",
    "page_up",
    "right",
    "shift",
    "shift_r",
    "space",
    "tab",
    "up",
}


class KeymapTests(unittest.TestCase):
    def test_physical_anchors(self) -> None:
        self.assertEqual(KEYS[0].name, "a")
        self.assertEqual(KEYS[0].win_scan, 0x1E)
        self.assertFalse(KEYS[0].win_ext)
        self.assertEqual(KEYS[12].win_scan, 0x10)  # q
        self.assertEqual(KEYS[6].win_scan, 0x2C)  # z
        self.assertEqual(KEYS[18].win_scan, 0x02)  # 1
        self.assertEqual(KEYS[49].win_scan, 0x39)  # space
        self.assertEqual(KEYS[36].win_scan, 0x1C)  # return
        self.assertEqual(KEYS[123].win_scan, 0x4B)  # left
        self.assertTrue(KEYS[123].win_ext)
        self.assertEqual(KEYS[59].win_scan, 0x1D)  # left ctrl
        self.assertFalse(KEYS[59].win_ext)
        self.assertTrue(KEYS[62].win_ext)  # right ctrl
        self.assertEqual(KEYS[122].win_scan, 0x3B)  # f1

    def test_command_remap(self) -> None:
        self.assertEqual(remap_command(55, True), 59)
        self.assertEqual(remap_command(54, True), 62)
        self.assertEqual(remap_command(55, False), 55)
        self.assertEqual(remap_command(0, True), 0)

    def test_linux_tokens(self) -> None:
        for info in KEYS.values():
            kind, value = linux_parts(info)
            self.assertIn(kind, {"char", "key"})
            if kind == "key":
                self.assertIn(value, PYNPUT_KEYS)
            else:
                self.assertTrue(value)


if __name__ == "__main__":
    unittest.main()
