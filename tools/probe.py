import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import displaycore as dc  # noqa: E402

print("Primary GDI:", dc.primary_gdi_name())
for d in dc.active_displays():
    print(f"\n{d.gdi_name}  [{d.friendly}]")
    for label, fn in (("advanced colour", d.advanced_color), ("SDR white nits", d.sdr_white_nits)):
        try:
            print(f"  {label}:", fn())
        except OSError as e:
            print(f"  {label}: ERROR {e}")
    try:
        r = d.get_ramp()
        print("  ramp R[0,64,128,192,255]:", [r[0][i] for i in (0, 64, 128, 192, 255)])
    except OSError as e:
        print("  ramp: ERROR", e)
