"""Portable tests of preset storage (no display access)."""
import unittest

import presets


class TestPresets(unittest.TestCase):
    def test_round_trip(self):
        st = presets.PresetStore()
        p = {"brightness": -10, "gamma": 120, "cap_on": True, "cap_nits": 150, "rtx_on": False}
        self.assertEqual(st.save("Night", p), "Night")
        again = presets.PresetStore(st.to_json())
        self.assertEqual(again.get("Night"), p)

    def test_clamps_and_drops_bad_values(self):
        p = presets.normalize({"brightness": 500, "gamma": "abc", "cap_knee": 10.6, "night_on": 1,
                               "sdr": True, "bogus": 3})
        self.assertEqual(p, {"brightness": 100, "cap_knee": 50, "night_on": True})

    def test_names_sorted_and_case_insensitive_overwrite(self):
        st = presets.PresetStore()
        st.save("gaming", {"gamma": 100})
        st.save("Night", {"gamma": 90})
        st.save("NIGHT", {"gamma": 80})
        self.assertEqual(st.names(), ["gaming", "NIGHT"])
        self.assertEqual(st.get("NIGHT"), {"gamma": 80})

    def test_rejects_empty_name_or_preset(self):
        st = presets.PresetStore()
        self.assertEqual(st.save("   ", {"gamma": 100}), "")
        self.assertEqual(st.save("x", {"bogus": 1}), "")
        self.assertEqual(st.names(), [])

    def test_name_cleanup(self):
        self.assertEqual(presets.clean_name("  late \n night  "), "late night")
        self.assertEqual(len(presets.clean_name("x" * 100)), presets.MAX_NAME)

    def test_delete(self):
        st = presets.PresetStore({"A": {"gamma": 100}})
        self.assertTrue(st.delete("A"))
        self.assertFalse(st.delete("A"))

    def test_tolerates_garbage_file(self):
        self.assertEqual(presets.PresetStore("nope").names(), [])
        self.assertEqual(presets.PresetStore({"ok": {"gamma": 100}, "bad": "x", "": {"gamma": 1}}).names(), ["ok"])


if __name__ == "__main__":
    unittest.main()
