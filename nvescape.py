"""Live RTX Video HDR control: replays the driver-private D3DKMTEscape that NVIDIA's nvcontainer sends
when a slider moves in NVIDIA App > System > Video > HDR (captured with Frida; see tools/escape_hook.js).

Buffer layout (112 bytes), as captured:
  +00 'ADVN' magic, +04 0x00010002, +08 size 0x70, +0C 'NV**', +10 command 0x0100003B
  +30 0x00010040 payload header, +34 setting id, +38/+3C/+40 scope, +44 value
  scope (2,0,0) = global, (0,1,1) = per-display. On return +14 == 1 means the driver accepted it.
"""
import ctypes
import struct
from ctypes import wintypes as W

gdi32 = ctypes.WinDLL("gdi32")

ID = {"enabled": 0x1E, "contrast": 0x1F, "saturation": 0x20, "midgrey": 0x21, "peak": 0x22, "flags": 0x23}
GLOBAL, DISPLAY = (2, 0, 0), (0, 1, 1)
OFFSET = {"contrast": 100, "saturation": 100}
RANGES = {"peak": (400, 1000), "midgrey": (10, 100), "contrast": (-100, 100), "saturation": (-100, 100)}
ORDER = ["enabled", "peak", "midgrey", "saturation", "contrast"]
COMMIT_FLAGS = 257

HEADER = bytes.fromhex("4144564e 02000100 70000000 2a2a564e 3b000001".replace(" ", "")) + bytes(0x1C)


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", W.DWORD), ("HighPart", W.LONG)]


class OPEN_FROM_LUID(ctypes.Structure):
    _fields_ = [("AdapterLuid", LUID), ("hAdapter", ctypes.c_uint32)]


class CLOSE_ADAPTER(ctypes.Structure):
    _fields_ = [("hAdapter", ctypes.c_uint32)]


class ESCAPE(ctypes.Structure):
    _fields_ = [("hAdapter", ctypes.c_uint32), ("hDevice", ctypes.c_uint32), ("Type", ctypes.c_uint32),
                ("Flags", ctypes.c_uint32), ("pPrivateDriverData", ctypes.c_void_p),
                ("PrivateDriverDataSize", ctypes.c_uint32), ("hContext", ctypes.c_uint32)]


ESCAPE_FLAGS = 0x8  # as captured (NoAdapterSynchronization)
for fn in ("D3DKMTOpenAdapterFromLuid", "D3DKMTEscape", "D3DKMTCloseAdapter"):
    getattr(gdi32, fn).restype = ctypes.c_long
    getattr(gdi32, fn).argtypes = [ctypes.c_void_p]


class EscapeError(OSError):
    pass


def _send(luid, setting_id, scope, value):
    buf = bytearray(HEADER + struct.pack("<IIIIII", 0x00010040, setting_id, *scope, value & 0xFFFFFFFF))
    buf += bytes(0x70 - len(buf))
    cbuf = (ctypes.c_ubyte * len(buf)).from_buffer(buf)
    op = OPEN_FROM_LUID(AdapterLuid=LUID(luid.LowPart, luid.HighPart))
    st = gdi32.D3DKMTOpenAdapterFromLuid(ctypes.byref(op))
    if st != 0:
        raise EscapeError(f"D3DKMTOpenAdapterFromLuid failed: {st & 0xFFFFFFFF:#x}")
    try:
        esc = ESCAPE(hAdapter=op.hAdapter, Type=0, Flags=ESCAPE_FLAGS,
                     pPrivateDriverData=ctypes.addressof(cbuf), PrivateDriverDataSize=len(buf))
        st = gdi32.D3DKMTEscape(ctypes.byref(esc))
        if st != 0:
            raise EscapeError(f"D3DKMTEscape(id={setting_id:#x}) NTSTATUS {st & 0xFFFFFFFF:#x}")
        ok = struct.unpack_from("<I", buf, 0x14)[0]
        if ok != 1:
            raise EscapeError(f"driver rejected id={setting_id:#x} (status field {ok})")
    finally:
        gdi32.D3DKMTCloseAdapter(ctypes.byref(CLOSE_ADAPTER(op.hAdapter)))


def raw_value(key, ui):
    if key == "enabled":
        return 1 if ui else 0
    lo, hi = RANGES[key]
    return max(lo, min(hi, int(ui))) + OFFSET.get(key, 0)


def apply(luid, state):
    """Push a full settings block live, in the NVIDIA App's order, then commit.
    state: dict with enabled, peak, midgrey, contrast, saturation (UI units)."""
    for key in ORDER:
        raw = raw_value(key, state[key])
        if key == "enabled":
            _send(luid, ID[key], DISPLAY, raw)
        else:
            _send(luid, ID[key], GLOBAL, raw)
            _send(luid, ID[key], DISPLAY, raw)
    _send(luid, ID["flags"], DISPLAY, COMMIT_FLAGS)


if __name__ == "__main__":
    import sys
    import displaycore as dc
    import nvhdr

    d = dc.primary_display()
    state = nvhdr.read()
    for a in sys.argv[1:]:
        k, v = a.split("=")
        state[k] = (v.lower() in ("1", "on", "true")) if k == "enabled" else int(v)
    apply(d.tgt_adapter, state)
    print("applied live:", state)
