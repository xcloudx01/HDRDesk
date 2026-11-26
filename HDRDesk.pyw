"""Monitor Sliders: floating always-on-top display control for the primary monitor.

Main panel  : Brightness / Contrast / Gamma (GPU gamma LUT, like NVCP 'Adjust desktop colour settings')
              + Windows SDR content brightness (HDR mode) + Windows Night Light warmth/on-off
              + highlight cap (HDR mode): soft nits ceiling folded into the same GPU LUT (see hdrcap.py).
Side panel  : RTX Video HDR (NVIDIA App > System > Video > HDR), applied live through the same
              driver escape the NVIDIA App uses (see nvescape.py).

Keyboard    : Up/Down select slider, Left/Right nudge (1% of range), Shift = fine (1 unit),
              Ctrl = coarse (5%), hold to slide, Delete = slider default.
"""
import ctypes
import json
import os
import sys
import time
import tkinter as tk
from tkinter import ttk

import displaycore as dc
import hdrcap
import nvescape
import nvhdr
import nightlight
import rampfit

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
STATE = os.path.join(HERE, "settings.json")
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "HDRDesk.ico")
DEFAULTS = {"brightness": 0, "contrast": 0, "gamma": 100, "x": None, "y": None, "hdr_open": False,
            "cap_on": False, "cap_nits": hdrcap.CAP_DEFAULT, "cap_knee": hdrcap.KNEE_DEFAULT}
RAMP_KEYS = ("brightness", "contrast", "gamma")

HDR_KEYS = ("peak", "midgrey", "contrast", "saturation")
HDR_RESET = {"peak": 400, "midgrey": 50, "contrast": 0, "saturation": 0}  # 400-nit True Black baseline

HOLD_DELAY_MS = 350   # tap = one step; hold longer than this to start sliding
REPEAT_MS = 35        # slide rate once repeating (1% per tick -> full range in ~3.5 s)

# ---- palette (Windows 11 dark) ----
BG, PANEL, TROUGH, FG, MUTED = "#202020", "#2b2b2b", "#3c3c3c", "#e8e8e8", "#8f8f8f"
ACCENT, ACCENT_HI = "#4cc2ff", "#99ebff"   # Windows blue
NV, NV_HI = "#76b900", "#a6e22e"           # NVIDIA green
ERR = "#ff6b6b"
FONT, FONT_B, FONT_V = ("Segoe UI", 9), ("Segoe UI Semibold", 10), ("Cascadia Mono", 9)


def load_state():
    try:
        with open(STATE) as f:
            return {**DEFAULTS, **json.load(f)}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def fmt_signed(v):
    return f"{v:+d}" if v else "0"


def setup_style(root):
    root.configure(bg=BG)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=FG, font=FONT, bordercolor=BG, focuscolor=BG)
    s.configure("TFrame", background=BG)
    s.configure("Side.TFrame", background=PANEL)
    for prefix, bg in (("", BG), ("Side.", PANEL)):
        s.configure(f"{prefix}TLabel", background=bg, foreground=FG)
        s.configure(f"{prefix}Name.TLabel", background=bg, foreground=MUTED)
        s.configure(f"{prefix}Value.TLabel", background=bg, foreground=FG, font=FONT_V)
        s.configure(f"{prefix}Head.TLabel", background=bg, foreground=FG, font=FONT_B)
    s.configure("NameFocus.TLabel", background=BG, foreground=ACCENT)
    s.configure("Side.NameFocus.TLabel", background=PANEL, foreground=NV)
    s.configure("Hint.TLabel", background=BG, foreground="#6a6a6a", font=("Segoe UI", 8))
    s.configure("Status.TLabel", background=BG, foreground=ERR, font=("Segoe UI", 8))

    # flat trough (from the 'default' theme) + clam thumb in accent colour, no bevels/outlines
    s.element_create("Flat.Horizontal.Scale.trough", "from", "default")
    layout = [("Flat.Horizontal.Scale.trough", {"sticky": "nswe", "children": [
        ("Horizontal.Scale.slider", {"side": "left", "sticky": ""})]})]
    for name, bg, acc, hi in (("Horizontal.TScale", BG, ACCENT, ACCENT_HI),
                              ("Side.Horizontal.TScale", PANEL, NV, NV_HI)):
        s.layout(name, layout)
        s.configure(name, troughcolor=TROUGH, background=acc, lightcolor=acc, darkcolor=acc,
                    bordercolor=acc, borderwidth=0, troughrelief="flat", sliderrelief="flat", gripcount=0)
        s.map(name, background=[("disabled", "#555555"), ("focus", hi), ("active", hi)],
              lightcolor=[("disabled", "#555555"), ("focus", hi), ("active", hi)],
              darkcolor=[("disabled", "#555555"), ("focus", hi), ("active", hi)],
              bordercolor=[("disabled", "#555555"), ("focus", hi), ("active", hi)])

    s.configure("TButton", background="#333333", foreground=FG, bordercolor="#3d3d3d",
                lightcolor="#333333", darkcolor="#333333", padding=(10, 3), relief="flat")
    s.map("TButton", background=[("pressed", "#262626"), ("active", "#3d3d3d")],
          lightcolor=[("active", "#3d3d3d")], darkcolor=[("active", "#3d3d3d")])
    s.configure("Side.TButton", background="#383838", lightcolor="#383838", darkcolor="#383838")
    s.map("Side.TButton", background=[("pressed", "#2a2a2a"), ("active", "#444444")])

    for prefix, bg, acc in (("", BG, ACCENT), ("Side.", PANEL, NV)):
        s.configure(f"{prefix}TCheckbutton", background=bg, foreground=FG, indicatorbackground=TROUGH,
                    indicatorforeground=BG, indicatorrelief="flat", indicatormargin=(0, 0, 6, 0))
        s.map(f"{prefix}TCheckbutton", background=[("active", bg)],
              indicatorbackground=[("selected", acc), ("active", "#4a4a4a")])
    s.configure("Side.TCheckbutton", font=FONT_B)


def app_icon(root):
    """32x32 monitor glyph: blue-to-green screen (display controls -> RTX HDR) on a grey stand."""
    img = tk.PhotoImage(width=32, height=32)
    (r1, g1, b1), (r2, g2, b2) = (0x4c, 0xc2, 0xff), (0x76, 0xb9, 0x00)
    for x in range(2, 30):
        t = (x - 2) / 27
        col = "#%02x%02x%02x" % (round(r1 + (r2 - r1) * t), round(g1 + (g2 - g1) * t), round(b1 + (b2 - b1) * t))
        img.put(col, to=(x, 5, x + 1, 23))
    img.put("#9a9a9a", to=(14, 23, 18, 27))
    img.put("#9a9a9a", to=(9, 27, 23, 29))
    root.iconphoto(True, img)
    root._icon = img  # keep a reference


def dark_titlebar(root):
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
    except Exception:
        pass


class Row:
    """One labelled slider: name | scale | value. Keeps a float position so keyboard steps are
    a constant fraction of the track regardless of the slider's range."""

    def __init__(self, app, parent, r, key, text, lo, hi, fmt, init, default, on_change, side=False):
        self.app, self.key, self.lo, self.hi, self.fmt = app, key, lo, hi, fmt
        self.default, self.on_change = default, on_change
        self.value = int(init)
        self.pos = float(init)
        pre = "Side." if side else ""
        self.style_name, self.style_focus = f"{pre}Name.TLabel", f"{pre}NameFocus.TLabel"
        self.name = ttk.Label(parent, text=text, style=self.style_name, width=12)
        self.name.grid(row=r, column=0, sticky="w")
        self.scale = ttk.Scale(parent, from_=lo, to=hi, orient="horizontal", length=230,
                               style=f"{pre}Horizontal.TScale", takefocus=1)
        self.scale.set(self.value)
        self.scale.grid(row=r, column=1, padx=8, pady=4)
        self.val = ttk.Label(parent, text=fmt(self.value), style=f"{pre}Value.TLabel", width=13, anchor="e")
        self.val.grid(row=r, column=2, sticky="e")
        self.scale.configure(command=self._moved)
        sc = self.scale
        sc.bind("<ButtonPress-1>", lambda e: sc.focus_set(), add="+")
        sc.bind("<Double-Button-1>", lambda e: self.reset())
        sc.bind("<FocusIn>", lambda e: self.name.configure(style=self.style_focus))
        sc.bind("<FocusOut>", lambda e: (self.name.configure(style=self.style_name), app.cancel_repeat()))
        sc.bind("<Delete>", lambda e: (self.reset(), "break")[1])
        for ks, d in (("Left", -1), ("Right", +1)):
            sc.bind(f"<KeyPress-{ks}>", lambda e, d=d: app.key_press(self, d, e))
            sc.bind(f"<KeyRelease-{ks}>", lambda e: app.key_release(e))
        sc.bind("<Up>", lambda e: app.move_focus(self, -1))
        sc.bind("<Down>", lambda e: app.move_focus(self, +1))

    @property
    def enabled(self):
        return not self.scale.instate(["disabled"])

    def set_enabled(self, on):
        self.scale.state(["!disabled"] if on else ["disabled"])

    def _moved(self, _v):
        v = int(round(float(self.scale.get())))
        if v != self.value:
            self.value, self.pos = v, float(v)
            self.val.configure(text=self.fmt(v))
            self.on_change()

    def set(self, v, notify=True):
        v = max(self.lo, min(self.hi, int(v)))
        changed = v != self.value
        self.value, self.pos = v, float(v)
        self.scale.set(v)
        self.val.configure(text=self.fmt(v))
        if changed and notify:
            self.on_change()

    def nudge(self, direction, mult):
        if not self.enabled:
            return
        step = 1.0 if mult == "fine" else (self.hi - self.lo) / 100.0 * mult
        self.pos = max(self.lo, min(self.hi, self.pos + direction * step))
        v = int(round(self.pos))
        if v != self.value:
            pos = self.pos
            self.set(v)
            self.pos = pos  # keep sub-unit remainder so every press advances the bar evenly

    def reset(self):
        if self.default is not None and self.enabled:
            self.set(self.default)


class App:
    def __init__(self, root):
        self.root = root
        self.disp = dc.primary_display()
        self.state = load_state()
        # Read the live GPU LUT. Saved slider values are merely an exact-match
        # hint for ambiguous/clipped ramps, never instructions to overwrite it.
        self.ramp_last_apply = 0.0
        live_cap = False
        try:
            current_ramp = self.disp.get_ramp()
            self.ramp_signature = rampfit.signature(current_ramp)
            live = self.match_live_ramp(current_ramp, tuple(self.state[k] for k in RAMP_KEYS),
                                        self.state["cap_nits"], self.state["cap_knee"])
            live_ramp, live_cap = live if live is not None else (None, False)
            self.ramp_warning = ("" if live_ramp is not None else
                                 "Custom GPU LUT: unchanged; adjusting a colour slider replaces it.")
        except OSError as exc:
            self.ramp_signature, live_ramp = None, None
            self.ramp_warning = f"GPU LUT unreadable: {exc}; startup did not change it."
        self.ramp_unknown = live_ramp is None
        self.ramp_values = live_ramp if live_ramp is not None else (0, 0, 100)
        self.pending_ramp = self.pending_sdr = self.pending_hdr = False
        self.pending_night = None
        self.night_last_apply = 0.0
        self.night_ctl = nightlight.NightLight()
        self.rows, self.hdr_rows = {}, []
        self.held_key, self.repeat_job = None, None
        self.hdr_open, self.hdr_last_apply = False, 0.0

        setup_style(root)
        app_icon(root)
        root.title("HDRDesk")
        root.attributes("-topmost", True)
        root.resizable(False, False)
        if self.state["x"] is not None:
            root.geometry(f"+{self.state['x']}+{self.state['y']}")
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        frm = ttk.Frame(root, padding=(14, 12, 14, 10))
        frm.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frm, text=self.disp.friendly or "Primary display", style="Head.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        specs = [("brightness", "Brightness", -100, 100, fmt_signed, 0),
                 ("contrast", "Contrast", -100, 100, fmt_signed, 0),
                 ("gamma", "Gamma", 30, 280, lambda v: f"{v / 100:.2f}", 100)]
        for r, (key, text, lo, hi, fmt, dflt) in enumerate(specs, start=1):
            self.rows[key] = Row(self, frm, r, key, text, lo, hi, fmt,
                                 self.ramp_values[r - 1], dflt, self.on_ramp_change)
        if self.ramp_unknown:
            for key in ("brightness", "contrast", "gamma"):
                self.rows[key].val.configure(text="Unknown")

        ac = self.disp.advanced_color()
        sdr_now = round((self.disp.sdr_white_nits() - 80) / 4)
        self.rows["sdr"] = Row(self, frm, 6, "sdr", "SDR content", 0, 100,
                               lambda v: f"{v} · {80 + 4 * v} nits", sdr_now, None, self.on_sdr_change)
        if not ac["enabled"]:
            self.rows["sdr"].set_enabled(False)
            self.rows["sdr"].val.configure(text="HDR off")

        # Windows Night Light strength and enablement are separate system settings.
        self.night_error = ""
        try:
            nl = self.night_ctl.read()
            self.night_available = True
        except (OSError, ValueError) as exc:
            nl = {"enabled": False, "strength": 0}
            self.night_available = False
            self.night_error = f"Night Light unavailable: {exc}"
        self.rows["night"] = Row(self, frm, 4, "night", "Night Light", 0, 100,
                                  lambda v: f"{v} %", nl["strength"], None, self.on_night_change)
        self.night_on = tk.BooleanVar(value=nl["enabled"])
        self.rows["night"].name.grid_remove()
        self.night_toggle = ttk.Checkbutton(frm, text="Night Light", variable=self.night_on,
                                            command=self.on_night_toggle, takefocus=0)
        self.night_toggle.grid(row=4, column=0, sticky="w")
        if not self.night_available:
            self.rows["night"].set_enabled(False)
            self.rows["night"].val.configure(text="Unavailable")
            self.night_toggle.state(["disabled"])

        # Highlight cap (HDR only): soft nits ceiling in the GPU LUT, on the PQ signal itself.
        self.rows["cap"] = Row(self, frm, 7, "cap", "Highlight cap", *hdrcap.CAP_RANGE,
                               lambda v: f"{v} nits", self.state["cap_nits"], hdrcap.CAP_DEFAULT,
                               self.on_cap_change)
        self.rows["knee"] = Row(self, frm, 8, "knee", "Cap knee", *hdrcap.KNEE_RANGE,
                                lambda v: f"{v}%·{self.rows['cap'].value * v // 100} nits",
                                self.state["cap_knee"], hdrcap.KNEE_DEFAULT, self.on_cap_change)
        self.cap_on = tk.BooleanVar(value=live_cap)
        self.rows["cap"].name.grid_remove()
        self.cap_toggle = ttk.Checkbutton(frm, text="Highlight cap", variable=self.cap_on,
                                          command=self.on_cap_toggle, takefocus=0)
        self.cap_toggle.grid(row=7, column=0, sticky="w")
        self.cap_available = None
        self.update_cap_available(ac["enabled"])
        frm.grid_rowconfigure(5, minsize=10)  # gap: desktop colour / Night Light above, HDR controls below
        # Up/Down follows the visual order.
        self.rows = {k: self.rows[k] for k in ("brightness", "contrast", "gamma", "night", "sdr", "cap", "knee")}

        btns = ttk.Frame(frm)
        btns.grid(row=9, column=0, columnspan=3, pady=(10, 0), sticky="ew")
        ttk.Button(btns, text="Reset colour", command=self.reset_ramp, takefocus=0).pack(side="left")
        self.cap_reset_btn = ttk.Button(btns, text="Reset cap", command=self.reset_cap, takefocus=0)
        self.cap_reset_btn.pack(side="left", padx=(6, 0))
        self.cap_reset_btn.state(["!disabled"] if self.cap_available else ["disabled"])
        self.hdr_btn = ttk.Button(btns, text="RTX HDR  ▸", command=self.toggle_hdr_panel, takefocus=0)
        self.hdr_btn.pack(side="left", padx=6)
        self.pin = tk.BooleanVar(value=True)
        ttk.Checkbutton(btns, text="On top", variable=self.pin, takefocus=0,
                        command=lambda: root.attributes("-topmost", self.pin.get())).pack(side="right")

        ttk.Label(frm, text="↑↓ select   ←→ adjust   Shift fine   Ctrl coarse   hold to slide   Del default",
                  style="Hint.TLabel").grid(row=10, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.status = ttk.Label(frm, text=self.night_error, style="Status.TLabel")
        self.status.grid(row=11, column=0, columnspan=3, sticky="w")
        self.ramp_notice = ttk.Label(frm, text=self.ramp_warning, style="Status.TLabel")
        self.ramp_notice.grid(row=12, column=0, columnspan=3, sticky="w")

        self._build_hdr_panel(root)
        if self.state.get("hdr_open"):
            self.toggle_hdr_panel()

        # expose scales by key (used by selftest.py)
        self.sliders = {k: r.scale for k, r in self.rows.items()}
        self.side_rows = {r.key: r for r in self.hdr_rows}
        self.sliders.update({r.key: r.scale for r in self.hdr_rows})

        # Merely opening HDRDesk must not change the system's display LUT.
        dark_titlebar(root)
        self.rows["brightness"].scale.focus_set()
        root.after(2000, self.watchdog)

    # ---- keyboard: tap = one step, hold = slide after a short delay ----
    @staticmethod
    def _mult(e):
        if e.state & 0x1:
            return "fine"
        return 5 if e.state & 0x4 else 1

    def key_press(self, row, direction, e):
        if self.held_key == e.keysym:  # OS auto-repeat while held: our own timer drives the slide
            return "break"
        self.cancel_repeat()
        self.held_key = e.keysym
        mult = self._mult(e)
        row.nudge(direction, mult)
        self.repeat_job = self.root.after(HOLD_DELAY_MS, lambda: self._repeat(row, direction, mult))
        return "break"

    def _repeat(self, row, direction, mult):
        row.nudge(direction, mult)
        self.repeat_job = self.root.after(REPEAT_MS, lambda: self._repeat(row, direction, mult))

    def key_release(self, e):
        if self.held_key == e.keysym:
            self.cancel_repeat()
        return "break"

    def cancel_repeat(self):
        if self.repeat_job:
            self.root.after_cancel(self.repeat_job)
        self.repeat_job, self.held_key = None, None

    def move_focus(self, row, d):
        order = [r for r in list(self.rows.values()) + (self.hdr_rows if self.hdr_open else []) if r.enabled]
        if row in order:
            order[(order.index(row) + d) % len(order)].scale.focus_set()
        elif order:
            order[0].scale.focus_set()
        return "break"

    # ---- gamma LUT (brightness / contrast / gamma) ----
    def on_ramp_change(self):
        # Replacing an unrepresentable LUT requires an explicit slider change.
        if self.ramp_unknown:
            self.ramp_unknown = False
            self.ramp_notice.configure(text="")
            for key in ("brightness", "contrast", "gamma"):
                row = self.rows[key]
                row.val.configure(text=row.fmt(row.value))
        if not self.pending_ramp:  # coalesce rapid drags to ~60 Hz
            self.pending_ramp = True
            self.root.after(16, self.apply_ramp)

    @staticmethod
    def model_ramp(bcg, cap=None):
        """The LUT HDRDesk writes: brightness/contrast/gamma, then (HDR only) the nits roll-off.
        cap is (cap_nits, knee_pct) or None."""
        b, c, g = bcg
        ramp = dc.build_ramp(b / 100, c / 100, g / 100)
        return hdrcap.apply_to_ramp(ramp, *cap) if cap else ramp

    @classmethod
    def match_live_ramp(cls, current, preferred, cap_nits, cap_knee):
        """Read the live LUT as ((b, c, g), cap_on), or None if HDRDesk's model can't reproduce it.
        A capped LUT is only recognised for the saved controls and cap settings (near-exact match)."""
        try:
            want = rampfit.signature(cls.model_ramp(preferred, (cap_nits, cap_knee)))
            have = rampfit.signature(current)
            if all(abs(a - b) <= 2 for wc, hc in zip(want, have) for a, b in zip(wc, hc)):
                return tuple(preferred), True
        except (TypeError, ValueError, IndexError):
            pass
        live = rampfit.infer_controls(current, preferred)
        return (live, False) if live is not None else None

    def cap_setting(self):
        if self.cap_on.get() and self.cap_available:
            return self.rows["cap"].value, self.rows["knee"].value
        return None

    def update_cap_available(self, hdr_enabled):
        if hdr_enabled == self.cap_available:
            return
        self.cap_available = hdr_enabled
        for key in ("cap", "knee"):
            row = self.rows[key]
            row.set_enabled(hdr_enabled)
            row.val.configure(text=row.fmt(row.value) if hdr_enabled else "HDR off")
        self.cap_toggle.state(["!disabled"] if hdr_enabled else ["disabled"])
        if hasattr(self, "cap_reset_btn"):
            self.cap_reset_btn.state(["!disabled"] if hdr_enabled else ["disabled"])

    def on_cap_change(self):
        """Cap / knee slider moved by the user: switch the cap on if it was off, then apply."""
        if self.cap_available and not self.cap_on.get():
            self.cap_on.set(True)
        self._cap_values_changed()

    def _cap_values_changed(self):
        """Rewrite the LUT only while the cap is in use, so a reset with the cap off never
        replaces a custom LUT."""
        knee = self.rows["knee"]
        if self.cap_available:
            knee.val.configure(text=knee.fmt(knee.value))  # its nits readout follows the cap
        if self.cap_on.get() and self.cap_available:
            self.on_ramp_change()

    def on_cap_toggle(self):
        self.on_ramp_change()

    def reset_cap(self):
        """Cap and knee back to their defaults; the on/off state is left as it is."""
        if not self.cap_available:
            return
        self.rows["cap"].set(hdrcap.CAP_DEFAULT, notify=False)
        self.rows["knee"].set(hdrcap.KNEE_DEFAULT, notify=False)
        self._cap_values_changed()

    def apply_ramp(self):
        self.pending_ramp = False
        desired = self.model_ramp(tuple(self.rows[k].value for k in RAMP_KEYS), self.cap_setting())
        try:
            self.disp.set_ramp(desired)
            self.ramp_last_apply = time.monotonic()
            self.ramp_signature = rampfit.signature(desired)
            self.status.configure(text="")
        except OSError as e:
            self.status.configure(text=str(e))

    def sync_ramp_from_windows(self):
        # Read external changes, including colour-control changes and resets on
        # mode switches. Never force an old LUT back into Windows.
        if (self.pending_ramp or self.repeat_job or
                time.monotonic() - self.ramp_last_apply < 1.5 or
                any(self.rows[k].scale.instate(["pressed"])
                    for k in RAMP_KEYS + ("cap", "knee"))):
            return
        current = self.disp.get_ramp()
        signature = rampfit.signature(current)
        if signature == self.ramp_signature:
            return
        self.ramp_signature = signature
        preferred = tuple(self.rows[k].value for k in RAMP_KEYS)
        match = self.match_live_ramp(current, preferred, self.rows["cap"].value, self.rows["knee"].value)
        live = None
        if match is not None:
            live, cap_live = match
            self.cap_on.set(cap_live)  # e.g. Windows dropped the LUT on sleep / HDR toggle
        if live is None:
            self.ramp_unknown = True
            self.ramp_notice.configure(
                text="Custom GPU LUT: unchanged; adjusting a colour slider replaces it.")
            for key in ("brightness", "contrast", "gamma"):
                self.rows[key].val.configure(text="Unknown")
            return
        self.ramp_unknown = False
        self.ramp_notice.configure(text="")
        for key, value in zip(("brightness", "contrast", "gamma"), live):
            row = self.rows[key]
            row.set(value, notify=False)
            row.val.configure(text=row.fmt(row.value))

    def reset_ramp(self):
        if self.ramp_unknown:
            # Reset is an explicit user request even if placeholder sliders are
            # already at neutral positions. Apply neutral to the custom LUT.
            for key in ("brightness", "contrast", "gamma"):
                row = self.rows[key]
                row.set(row.default, notify=False)
            self.on_ramp_change()
            return
        for k in ("brightness", "contrast", "gamma"):
            self.rows[k].reset()

    # ---- SDR content brightness ----
    def on_sdr_change(self):
        if not self.pending_sdr:
            self.pending_sdr = True
            self.root.after(30, self.apply_sdr)

    def apply_sdr(self):
        self.pending_sdr = False
        try:
            self.disp.set_sdr_white_nits(80 + 4 * self.rows["sdr"].value)
            self.status.configure(text="")
        except OSError as e:
            self.status.configure(text=str(e))

    # ---- Windows Night Light: native warmth and independent enable switch ----
    def on_night_change(self):
        if not self.night_available:
            return
        if not self.night_on.get():  # moving the warmth slider switches Night Light on
            self.night_on.set(True)
            self.apply_night()       # new strength first, then enable
            self.on_night_toggle()
            return
        if self.pending_night is not None:
            self.root.after_cancel(self.pending_night)
        self.pending_night = self.root.after(150, self.apply_night)

    def apply_night(self):
        self.pending_night = None
        if not self.night_available:
            return
        try:
            self.night_ctl.set_strength(self.rows["night"].value)
            self.night_last_apply = time.monotonic()
            self.status.configure(text="")
        except (OSError, ValueError) as exc:
            self.status.configure(text=f"Night Light: {exc}")

    def on_night_toggle(self):
        if not self.night_available:
            return
        if self.pending_night is not None:
            self.root.after_cancel(self.pending_night)
            self.apply_night()
        try:
            self.night_ctl.set_enabled(self.night_on.get())
            self.night_last_apply = time.monotonic()
            self.status.configure(text="")
        except (OSError, ValueError) as exc:
            try:
                self.night_on.set(self.night_ctl.read()["enabled"])
            except OSError:
                pass
            self.status.configure(text=f"Night Light: {exc}")

    def sync_night_from_windows(self):
        if not self.night_available:
            return
        row = self.rows["night"]
        if (self.pending_night is not None or self.repeat_job
                or time.monotonic() - self.night_last_apply < 1.0
                or row.scale.instate(["pressed"])):
            return
        try:
            current = self.night_ctl.read()
            if current["enabled"] != self.night_on.get():
                self.night_on.set(current["enabled"])
            if current["strength"] != row.value:
                row.set(current["strength"], notify=False)
        except (OSError, ValueError) as exc:
            self.status.configure(text=f"Night Light: {exc}")

    # ---- RTX Video HDR side panel (NVIDIA App > System > Video > HDR) ----
    def _build_hdr_panel(self, root):
        side = self.side = ttk.Frame(root, style="Side.TFrame", padding=(14, 12, 14, 10))
        try:
            cur = nvhdr.read()
            self.hdr_available = True
        except Exception as e:
            cur = {"enabled": False, **HDR_RESET}
            self.hdr_available = False
            self.status.configure(text=f"RTX HDR unavailable: {e}")

        head = ttk.Frame(side, style="Side.TFrame")
        head.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self.hdr_on = tk.BooleanVar(value=cur["enabled"])
        ttk.Checkbutton(head, text="RTX Video HDR", variable=self.hdr_on, style="Side.TCheckbutton",
                        takefocus=0, command=self.on_hdr_change).pack(side="left")

        pct = lambda v: f"{v:+d} %" if v else "0 %"  # noqa: E731
        specs = [("peak", "Peak", 400, 1000, lambda v: f"{v} nits"),
                 ("midgrey", "Middle grey", 10, 100, lambda v: f"{v} nits"),
                 ("contrast", "Contrast", -100, 100, pct),
                 ("saturation", "Saturation", -100, 100, pct)]
        for r, (key, text, lo, hi, fmt) in enumerate(specs, start=1):
            row = Row(self, side, r, "hdr_" + key, text, lo, hi, fmt, cur[key], HDR_RESET[key],
                      self.on_hdr_change, side=True)
            row.set_enabled(self.hdr_available)
            self.hdr_rows.append(row)

        foot = ttk.Frame(side, style="Side.TFrame")
        foot.grid(row=5, column=0, columnspan=3, pady=(10, 0), sticky="ew")
        ttk.Button(foot, text="Reset RTX HDR", style="Side.TButton", takefocus=0,
                   command=self.reset_hdr).pack(side="left")
        ttk.Label(foot, text="400 / 50 / 0 / 0", style="Side.Name.TLabel").pack(side="left", padx=8)

    def toggle_hdr_panel(self):
        self.hdr_open = not self.hdr_open
        if self.hdr_open:
            self.side.grid(row=0, column=1, sticky="nsew")
            self.hdr_btn.configure(text="◂  RTX HDR")
        else:
            focused = self.root.focus_get()
            self.side.grid_remove()
            self.hdr_btn.configure(text="RTX HDR  ▸")
            if any(focused is r.scale for r in self.hdr_rows):
                self.rows["brightness"].scale.focus_set()

    def hdr_state(self):
        return {"enabled": self.hdr_on.get(), **{r.key[4:]: r.value for r in self.hdr_rows}}

    def reset_hdr(self):
        for r in self.hdr_rows:
            r.set(HDR_RESET[r.key[4:]], notify=False)
        self.on_hdr_change()

    def on_hdr_change(self):
        if self.hdr_available and not self.pending_hdr:  # coalesce (~10 escapes per push)
            self.pending_hdr = True
            self.root.after(40, self.apply_hdr)

    def apply_hdr(self):
        self.pending_hdr = False
        try:
            nvescape.apply(self.disp.tgt_adapter, self.hdr_state())
            self.hdr_last_apply = time.monotonic()
            self.status.configure(text="")
        except OSError as e:
            self.status.configure(text=f"RTX HDR: {e}")

    def sync_hdr_from_driver(self):
        """Follow changes made elsewhere (NVIDIA App): the driver persists every accepted change to the registry."""
        busy = self.repeat_job or self.pending_hdr or time.monotonic() - self.hdr_last_apply < 1.5
        if not self.hdr_available or busy:
            return
        if any(r.scale.instate(["pressed"]) for r in self.hdr_rows):
            return
        cur = nvhdr.read()
        if cur["enabled"] != self.hdr_on.get():
            self.hdr_on.set(cur["enabled"])
        for r in self.hdr_rows:
            if cur[r.key[4:]] != r.value:
                r.set(cur[r.key[4:]], notify=False)

    # ---- keep state in sync with the system ----
    def watchdog(self):
        try:
            # The OS/external display controls are authoritative, not saved state.
            self.sync_ramp_from_windows()
            # Follow external changes to SDR brightness (e.g. the Settings app).
            self.update_cap_available(self.disp.advanced_color()["enabled"])
            sdr = self.rows["sdr"]
            if (not self.pending_sdr and not self.repeat_job and not sdr.scale.instate(["pressed"])
                    and self.disp.advanced_color()["enabled"]):
                v = round((self.disp.sdr_white_nits() - 80) / 4)
                if v != sdr.value:
                    sdr.set(v, notify=False)
            self.sync_hdr_from_driver()
            self.sync_night_from_windows()
        except (OSError, RuntimeError):
            try:  # display topology changed: re-find the primary
                self.disp = dc.primary_display()
            except Exception:
                pass
        self.root.after(2000, self.watchdog)

    def on_close(self):
        if self.pending_night is not None:
            self.root.after_cancel(self.pending_night)
            self.apply_night()
        data = {k: self.rows[k].value for k in ("brightness", "contrast", "gamma")}
        data.update(x=self.root.winfo_x(), y=self.root.winfo_y(), hdr_open=self.hdr_open,
                    cap_on=self.cap_on.get(), cap_nits=self.rows["cap"].value, cap_knee=self.rows["knee"].value)
        with open(STATE, "w") as f:
            json.dump(data, f)
        self.root.destroy()


if __name__ == "__main__":
    os.chdir(HERE)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HDRDesk.HDRDesk")
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    try:
        root.iconbitmap(default=ICON)
    except (tk.TclError, OSError):
        pass
    App(root)
    root.mainloop()
