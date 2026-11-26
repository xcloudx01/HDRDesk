"""Portable tests of hotkey rules (no hotkeys are registered)."""
import unittest

import hotkeys as hk

A, C, S, W = hk.MOD_ALT, hk.MOD_CONTROL, hk.MOD_SHIFT, hk.MOD_WIN


class TestRules(unittest.TestCase):
    def test_only_lone_modifiers_are_invalid(self):
        self.assertTrue(hk.invalid_reason(C, 0x11))
        self.assertTrue(hk.invalid_reason(0, 0))
        for mods, vk in [(0, ord("C")), (C, ord("C")), (A, hk.VK_TAB), (C | A, hk.VK_DELETE), (0, hk.VK_F12),
                         (W | A, ord("B")), (0, 0x14)]:
            self.assertEqual(hk.invalid_reason(mods, vk), "")

    def test_risky_combos_get_a_warning(self):
        for mods, vk in [(C | A, hk.VK_DELETE), (A, hk.VK_TAB), (W | A, ord("B")), (W | C | S, ord("B")),
                         (W, ord("L")), (C, ord("C")), (0, ord("K")), (0, hk.VK_F12)]:
            with self.subTest(combo=hk.combo_text(mods, vk)):
                self.assertTrue(hk.warning(mods, vk))

    def test_quiet_combos_have_no_warning(self):
        for mods, vk in [(C | A, ord("K")), (C, hk.VK_UP), (0, hk.VK_F13), (A, hk.VK_F1 + 5)]:
            self.assertEqual(hk.warning(mods, vk), "")

    def test_combo_text(self):
        self.assertEqual(hk.combo_text(C | A | W, ord("K")), "Win+Ctrl+Alt+K")
        self.assertEqual(hk.combo_text(S, hk.VK_F1 + 7), "Shift+F8")


class TestNormalize(unittest.TestCase):
    def test_filters(self):
        targets = {"brightness", "gamma"}
        entries = [
            {"mods": C | A, "vk": ord("K"), "target": "brightness", "mode": "nudge", "value": -5},
            {"mods": A, "vk": hk.VK_TAB, "target": "gamma", "mode": "set", "value": 100},     # risky but kept
            {"mods": C | A, "vk": ord("K"), "target": "gamma", "mode": "set", "value": 100},   # duplicate keys
            {"mods": C, "vk": 0x11, "target": "gamma", "mode": "set", "value": 100},          # lone modifier
            {"mods": C | A, "vk": ord("J"), "target": "nope", "mode": "set", "value": 1},      # unknown target
            {"mods": C | A, "vk": ord("L"), "target": "gamma", "mode": "jump", "value": 1},    # bad mode
            "garbage",
        ]
        self.assertEqual(hk.normalize(entries, targets), entries[:2])
        self.assertEqual(hk.normalize("x", targets), [])


if __name__ == "__main__":
    unittest.main()
