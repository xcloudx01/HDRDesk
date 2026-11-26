"""Portable tests of the HDR highlight-cap curve (no display access)."""
import unittest

import displaycore as dc
import hdrcap


class TestPQ(unittest.TestCase):
    def test_reference_points(self):
        self.assertAlmostEqual(hdrcap.pq_to_nits(0.0), 0.0)
        self.assertAlmostEqual(hdrcap.pq_to_nits(1.0), 10000.0, places=3)
        self.assertAlmostEqual(hdrcap.pq_to_nits(0.60), 244, delta=1)
        # The ramp index whose clamp was photographed cutting at desktop code ~193-195 (SDR 480).
        self.assertAlmostEqual(hdrcap.pq_to_nits(154 / 255), 253, delta=1)

    def test_round_trip(self):
        for nits in (0.05, 1, 50, 100, 203, 480, 1000, 4000):
            with self.subTest(nits=nits):
                self.assertAlmostEqual(hdrcap.pq_to_nits(hdrcap.nits_to_pq(nits)), nits, delta=nits * 1e-6)


class TestRollOff(unittest.TestCase):
    def test_identity_below_knee(self):
        for nits in (0, 10, 50, 104.9):
            self.assertEqual(hdrcap.roll_off(nits, 150, 70), nits)

    def test_never_reaches_cap_and_is_monotonic(self):
        prev = -1.0
        for nits in range(0, 10001, 5):
            out = hdrcap.roll_off(nits, 150, 70)
            self.assertLess(out, 150 + 1e-9)
            self.assertGreaterEqual(out, prev)
            prev = out

    def test_smooth_at_knee(self):
        knee, d = 105.0, 1e-4
        slope = (hdrcap.roll_off(knee + d, 150, 70) - hdrcap.roll_off(knee, 150, 70)) / d
        self.assertAlmostEqual(slope, 1.0, places=3)

    def test_knee_at_cap_is_hard_clip(self):
        self.assertEqual(hdrcap.roll_off(500, 150, 100), 150)


class TestRamp(unittest.TestCase):
    def test_identity_ramp(self):
        out = hdrcap.apply_to_ramp(dc.build_ramp(), 150, 70)
        knee_idx = max(i for i in range(256) if hdrcap.pq_to_nits(i / 255) <= 105)
        for c in range(3):
            ch = list(out[c])
            self.assertEqual(ch, sorted(ch))                       # monotonic
            for i in range(knee_idx + 1):                          # untouched below the knee
                self.assertLessEqual(abs(ch[i] - round(i / 255 * 65535)), 1)
            self.assertLess(hdrcap.pq_to_nits(ch[255] / 65535), 150.1)   # 16-bit rounding only


if __name__ == "__main__":
    unittest.main()
