"""Codec tests use synthetic CloudStore values; they do not modify Windows settings."""
import unittest
from unittest.mock import patch
import nightlight as n


def synthetic(kind):
    if kind == n.SETTINGS:
        # Keep a schedule and two nested TimeBlock fields intact.
        inner = (n._make(0, n.BOOL, b"\x01")
                 + n._make(20, n.STRUCT, n._make(0, n.INT8, b"\x15") + b"\x00")
                 + n._make(30, n.STRUCT, b"\x00")
                 + n._make(40, n.INT16, n._zigzag(3200))
                 + b"\x00")
    else:
        inner = n._make(0, n.INT32, n._zigzag(0)) + b"\x00"
    inner = n.PREFIX + inner
    container = n._make(0, n.UINT64, n._packvar(12345))
    wrapper = n._make(1, n.LIST, bytes([n.INT8]) + n._packvar(len(inner)) + inner) + b"\x00"
    container += n._make(1, n.STRUCT, wrapper) + b"\x00"
    outer = n._make(0, n.STRUCT, n._make(0, n.BOOL, b"\x01") + b"\x00")
    return n.PREFIX + outer + n._make(1, n.STRUCT, container) + b"\x00"


class FakeRegistry:
    HKEY_CURRENT_USER = 1
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_BINARY = 3

    def __init__(self):
        self.values = {n.SETTINGS: synthetic(n.SETTINGS), n.STATE: synthetic(n.STATE)}

    class Key:
        def __init__(self, registry, kind):
            self.registry, self.kind = registry, kind

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def OpenKey(self, _root, path, *_):
        kind = path.split(r"\")[-1].split(".")[-1]
        if kind not in self.values:
            raise FileNotFoundError(path)
        return self.Key(self, kind)

    def QueryValueEx(self, key, name):
        assert name == "Data"
        return self.values[key.kind], self.REG_BINARY

    def SetValueEx(self, key, name, _reserved, typ, data):
        assert name == "Data" and typ == self.REG_BINARY
        self.values[key.kind] = data


class NightLightTests(unittest.TestCase):
    def setUp(self):
        self.registry = FakeRegistry()
        self.patch = patch.object(n, "winreg", self.registry)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.nl = n.NightLight()

    def test_decode_settings_and_state(self):
        self.assertEqual(self.nl.read()["enabled"], True)
        self.assertEqual(n._read_temp(n._unpack_record(self.registry.values[n.SETTINGS]).inner), 3200)
        self.assertEqual(n._unpack_record(self.registry.values[n.SETTINGS]).stamp, 12345)

    def test_change_strength_preserves_schedule_and_cleans_preview(self):
        before = n._unpack_record(self.registry.values[n.SETTINGS])
        self.nl.set_strength(73)
        after = n._unpack_record(self.registry.values[n.SETTINGS])
        self.assertEqual(_field_bytes(before.inner, 0), _field_bytes(after.inner, 0))
        self.assertEqual(_field_bytes(before.inner, 20), _field_bytes(after.inner, 20))
        self.assertEqual(_field_bytes(before.inner, 30), _field_bytes(after.inner, 30))
        self.assertEqual(n._read_temp(after.inner), n._strength_to_k(73))
        self.assertFalse(n._read_preview(after.inner))
        self.assertGreater(after.stamp, before.stamp)
        self.assertEqual(self.nl.read()["enabled"], True)

    def test_enable_disable_preserves_strength_and_schedule(self):
        original = self.registry.values[n.SETTINGS]
        self.nl.set_enabled(False)
        self.assertFalse(self.nl.read()["enabled"])
        self.assertEqual(self.registry.values[n.SETTINGS], original)
        self.nl.set_strength(45)
        self.assertFalse(self.nl.read()["enabled"])
        self.nl.set_enabled(True)
        self.assertTrue(self.nl.read()["enabled"])
        self.assertEqual(self.nl.read()["strength"], 45)

    def test_unavailable_does_not_create_keys(self):
        self.registry.values.clear()
        with self.assertRaises(n.NightLightError):
            self.nl.read()
        with self.assertRaises(n.NightLightError):
            self.nl.set_strength(50)
        self.assertFalse(self.registry.values)

    def test_invalid_record_refused(self):
        self.registry.values[n.SETTINGS] = b"garbage"
        with self.assertRaises(n.NightLightError):
            self.nl.read()
        with self.assertRaises(n.NightLightError):
            self.nl.set_strength(50)
        self.assertEqual(self.registry.values[n.SETTINGS], b"garbage")


def _field_bytes(inner, id_):
    fields, _ = n._scan(inner, len(n.PREFIX))
    f = next(f for f in fields if f.id == id_)
    return inner[f.start:f.end]


if __name__ == "__main__":
    unittest.main()
