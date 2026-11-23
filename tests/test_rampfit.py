"""Portable, read-only tests of GPU LUT state inference."""
import unittest
import rampfit


def ramp(b, c, g):
    ch = rampfit._samples(b, c, g)
    return (ch, ch, ch)


class TestRampFit(unittest.TestCase):
    def test_neutral(self):
        self.assertEqual(rampfit.infer_controls(ramp(0, 0, 100)), (0, 0, 100))

    def test_existing_settings_are_read_not_applied(self):
        settings = (0, 0, 100)
        actual = (-25, 30, 145)
        self.assertEqual(rampfit.infer_controls(ramp(*actual), settings), actual)

    def test_known_luts(self):
        for values in [(17, -15, 90), (-10, 20, 130), (40, -35, 250),
                       (-45, 70, 64), (0, 0, 280), (0, 0, 30), (5, 5, 100)]:
            with self.subTest(values=values):
                self.assertEqual(rampfit.infer_controls(ramp(*values), values), values)

    def test_signature_detects_external_edits(self):
        self.assertNotEqual(rampfit.signature(ramp(0, 0, 100)),
                            rampfit.signature(ramp(12, 0, 100)))

    def test_malformed_lut(self):
        self.assertIsNone(rampfit.infer_controls(([1], [1], [1])))

    def test_external_custom_rgb_lut(self):
        a = rampfit._samples(0, 0, 100)
        b = rampfit._samples(20, 0, 100)
        self.assertIsNone(rampfit.infer_controls((a, b, a)))

    def test_nonmodel_lut(self):
        ch = tuple(round(65535 * (i / 255.0) ** 1.6) if i < 128 else
                   round(65535 * (i / 255.0) ** 0.7) for i in range(256))
        self.assertIsNone(rampfit.infer_controls((ch, ch, ch)))

    def test_unidentifiable_flat_ramp(self):
        ch = (0,) * 256
        self.assertIsNone(rampfit.infer_controls((ch, ch, ch)))


if __name__ == '__main__':
    unittest.main()
