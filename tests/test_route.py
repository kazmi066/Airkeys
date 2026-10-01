import unittest

from airkeys.route import (
    FLAG_ALT,
    FLAG_CMD,
    FLAG_CTRL,
    FLAGS_CHANGED,
    KEY_DOWN,
    KEY_UP,
    FloodFuse,
    route_event,
)


def route(event_type, keycode, flags=0, **kwargs):
    defaults = dict(
        sharing=False,
        is_ours=False,
        repeat=False,
        held_mods=set(),
        map_cmd_to_ctrl=True,
    )
    defaults.update(kwargs)
    return route_event(event_type, keycode, flags, **defaults)


class RouteTests(unittest.TestCase):
    def test_idle_keys_stay_local(self) -> None:
        decision, held = route(KEY_DOWN, 0)
        self.assertFalse(decision.swallow)
        self.assertEqual(decision.forward, [])
        self.assertEqual(held, set())

    def test_shared_letter(self) -> None:
        down, _held = route(KEY_DOWN, 0, sharing=True)
        up, _held = route(KEY_UP, 0, sharing=True)
        self.assertEqual(down.forward, [(0, True)])
        self.assertTrue(down.swallow)
        self.assertEqual(up.forward, [(0, False)])

    def test_command_becomes_ctrl(self) -> None:
        down, held = route(FLAGS_CHANGED, 55, sharing=True)
        self.assertEqual(down.forward, [(59, True)])
        self.assertEqual(held, {55})
        up, held = route(FLAGS_CHANGED, 55, sharing=True, held_mods=held)
        self.assertEqual(up.forward, [(59, False)])
        self.assertEqual(held, set())

    def test_modifier_state_survives_while_idle(self) -> None:
        _decision, held = route(FLAGS_CHANGED, 55, sharing=False)
        self.assertEqual(held, {55})
        released, held = route(FLAGS_CHANGED, 55, sharing=True, held_mods=held)
        self.assertEqual(released.forward, [(59, False)])
        self.assertEqual(held, set())

    def test_toggle_hotkey(self) -> None:
        decision, _held = route(KEY_DOWN, 40, FLAG_CTRL | FLAG_ALT, sharing=True)
        self.assertTrue(decision.toggle)
        self.assertTrue(decision.swallow)
        self.assertEqual(decision.forward, [])
        repeated, _held = route(KEY_DOWN, 40, FLAG_CTRL | FLAG_ALT, sharing=True, repeat=True)
        self.assertFalse(repeated.toggle)
        self.assertTrue(repeated.swallow)

    def test_command_k_is_not_the_hotkey(self) -> None:
        decision, _held = route(KEY_DOWN, 40, FLAG_CMD, sharing=True)
        self.assertFalse(decision.toggle)
        self.assertEqual(decision.forward, [(40, True)])

    def test_unknown_key_is_not_eaten(self) -> None:
        decision, _held = route(KEY_DOWN, 999, sharing=True)
        self.assertFalse(decision.swallow)
        self.assertEqual(decision.forward, [])

    def test_injected_events_pass_through(self) -> None:
        decision, _held = route(KEY_DOWN, 0, sharing=True, is_ours=True)
        self.assertFalse(decision.swallow)
        self.assertEqual(decision.forward, [])

    def test_caps_is_a_tap(self) -> None:
        decision, _held = route(FLAGS_CHANGED, 57, sharing=True)
        self.assertEqual(decision.forward, [(57, True), (57, False)])

    def test_fuse(self) -> None:
        fuse = FloodFuse(limit=3, window=0.1)
        self.assertFalse(fuse.add(1.0))
        self.assertFalse(fuse.add(1.0))
        self.assertFalse(fuse.add(1.0))
        self.assertTrue(fuse.add(1.0))
        self.assertFalse(fuse.add(2.0))


if __name__ == "__main__":
    unittest.main()
