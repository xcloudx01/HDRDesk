"""Drives the real App's sliders programmatically and verifies the system state after each."""
import importlib.util
import os
import time
import tkinter as tk

import displaycore as dc

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ms", os.path.join(HERE, "HDRDesk.pyw"))
ms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ms)

root = tk.Tk()
app = ms.App(root)
d = dc.primary_display()
orig_sdr = d.sdr_white_nits()


def settle():
    for _ in range(10):
        root.update()
        root.after(10)
    root.after(60, root.quit)
    root.mainloop()


def check_ramp(b, c, g):
    want = dc.build_ramp(b / 100, c / 100, g / 100)
    got = d.get_ramp()
    return all(want[0][i] == got[0][i] for i in range(256))


results = []
for key, val, combo in (("brightness", -20, (-20, 0, 100)),
                        ("contrast", 30, (-20, 30, 100)),
                        ("gamma", 140, (-20, 30, 140))):
    app.sliders[key].set(val)
    settle()
    results.append((key, val, check_ramp(*combo)))

app.sliders["sdr"].set(50)
settle()
results.append(("sdr", "50 -> 280 nits", d.sdr_white_nits() == 280.0))

# RTX Video HDR side panel: driver persists accepted escapes to the registry, so read that back
import nvhdr  # noqa: E402

hdr_orig = nvhdr.read()
if not app.hdr_open:  # settings.json may already have it open
    app.toggle_hdr_panel()
settle()
results.append(("hdr panel", "visible", bool(app.side.winfo_ismapped())))
for key, val in (("peak", 820), ("midgrey", 44), ("contrast", -20), ("saturation", 25)):
    app.sliders["hdr_" + key].set(val)
    settle()
    results.append((f"hdr {key}", val, nvhdr.read()[key] == val))
app.hdr_on.set(not hdr_orig["enabled"])
app.on_hdr_change()
settle()
results.append(("hdr toggle", not hdr_orig["enabled"], nvhdr.read()["enabled"] == (not hdr_orig["enabled"])))
app.hdr_on.set(hdr_orig["enabled"])
for key in ("peak", "midgrey", "contrast", "saturation"):
    app.sliders["hdr_" + key].set(hdr_orig[key])
settle()
results.append(("restore hdr", "orig", nvhdr.read() == hdr_orig))

# RTX HDR reset button -> 400 / 50 / 0 / 0, state untouched
app.reset_hdr()
settle()
got = nvhdr.read()
results.append(("hdr reset", "400/50/0/0", (got["peak"], got["midgrey"], got["contrast"], got["saturation"]) == (400, 50, 0, 0)
                and got["enabled"] == hdr_orig["enabled"]))

# ---- keyboard ----
def tap(widget, ks, release=True, **kw):
    if root.focus_get() is not widget:  # Tk routes key events to the focus widget
        widget.focus_force()
        settle()
    widget.event_generate(f"<KeyPress-{ks}>", **kw)
    if release:
        widget.event_generate(f"<KeyRelease-{ks}>", **kw)
    settle()


app.reset_ramp()
settle()
b, g, mg = app.rows["brightness"], app.rows["gamma"], app.side_rows["hdr_midgrey"]
b.scale.focus_force()
settle()
tap(b.scale, "Right")
results.append(("key tap", "brightness +2 (1% of 200)", b.value == 2))
tap(g.scale, "Right"); tap(g.scale, "Right")
results.append(("key tap x2", "gamma +5 (2x 1% of 250)", g.value == 105))
mg.set(50, notify=False)
for _ in range(10):
    tap(mg.scale, "Right")
results.append(("key tap x10", "midgrey +9 (10x 0.9)", mg.value == 59))
tap(b.scale, "Right", state=0x1)
results.append(("shift fine", "brightness +1", b.value == 3))
tap(b.scale, "Left", state=0x4)
results.append(("ctrl coarse", "brightness -10", b.value == -7))

# hold: first press steps once, OS auto-repeat ignored until hold delay, then slides; release stops
start = b.value
b.scale.event_generate("<KeyPress-Right>")
b.scale.event_generate("<KeyPress-Right>")  # simulated OS auto-repeat
settle()
results.append(("hold <delay", "1 step only", b.value == start + 2))
t_end = time.time() + 0.7
while time.time() < t_end:
    root.update()
held = b.value
b.scale.event_generate("<KeyRelease-Right>")
settle()
after_release = b.value
for _ in range(10):
    root.update()
    time.sleep(0.02)
results.append(("hold >delay", f"slid to {held}", held > start + 10))
results.append(("release stops", "no drift", b.value == after_release))

# focus navigation
b.scale.focus_force(); settle()
tap(b.scale, "Down")
results.append(("down -> next", "contrast focused", root.focus_get() is app.rows["contrast"].scale))
tap(app.rows["contrast"].scale, "Up")
results.append(("up -> prev", "brightness focused", root.focus_get() is b.scale))

# restore HDR to what it was before the test
for key_ in ("peak", "midgrey", "contrast", "saturation"):
    app.side_rows["hdr_" + key_].set(hdr_orig[key_], notify=False)
app.on_hdr_change()
settle()
results.append(("restore hdr 2", "orig", nvhdr.read() == hdr_orig))
app.toggle_hdr_panel()

# restore
app.reset_ramp()
app.sliders["sdr"].set(round((orig_sdr - 80) / 4))
settle()
results.append(("restore ramp", "identity", check_ramp(0, 0, 100)))
results.append(("restore sdr", orig_sdr, d.sdr_white_nits() == orig_sdr))
root.destroy()

for r in results:
    print(f"{r[0]:13} {str(r[1]):16} {'PASS' if r[2] else 'FAIL'}")
