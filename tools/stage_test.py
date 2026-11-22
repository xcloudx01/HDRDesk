"""Stage tester: python stage_test.py <brightness|contrast|gamma|sdr> <value>"""
import sys
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import displaycore as dc  # noqa: E402

kind, val = sys.argv[1], float(sys.argv[2])
d = dc.primary_display()
if kind == "sdr":
    before = d.sdr_white_nits()
    d.set_sdr_white_nits(val)
    print(f"SDR white: {before} -> requested {val} -> readback {d.sdr_white_nits()} nits")
else:
    params = {"brightness": 0.0, "contrast": 0.0, "gamma": 1.0}
    params[kind] = val
    want = dc.build_ramp(**params)
    d.set_ramp(want)
    got = d.get_ramp()
    idx = (0, 32, 64, 128, 192, 255)
    print(f"{kind}={val} on {d.friendly}")
    print("  expected:", [want[0][i] for i in idx])
    print("  readback:", [got[0][i] for i in idx])
    print("  match:", all(want[c][i] == got[c][i] for c in range(3) for i in range(256)))
