"""Emergency reset: identity gamma ramp on the primary display (does not touch SDR brightness)."""
import displaycore as dc

d = dc.primary_display()
d.set_ramp(dc.build_ramp())
r = d.get_ramp()
print("Reset", d.friendly, "ramp R[0,128,255]:", [r[0][i] for i in (0, 128, 255)])
