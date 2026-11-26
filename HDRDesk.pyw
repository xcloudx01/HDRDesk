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
import queue
import os
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

import displaycore as dc
import hdrcap
import hotkeys
import nvescape
import nvhdr
import nightlight
import presets
import rampfit
import toast

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
STATE = os.path.join(HERE, "settings.json")
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "HDRDesk.ico")
DEFAULTS = {"brightness": 0, "contrast": 0, "gamma": 100, "x": None, "y": None, "hdr_open": False,
            "cap_on": False, "cap_nits": hdrcap.CAP_DEFAULT, "cap_knee": hdrcap.KNEE_DEFAULT,
            "presets": {}, "preset": "", "hotkeys": [],
            "hotkey_toasts": True}
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
    s.configure("Section.TLabel", background=BG, foreground="#7a7a7a", font=("Segoe UI Semibold", 8))
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
    s.configure("Small.TButton", padding=(8, 1))
    s.configure("Side.TButton", background="#383838", lightcolor="#383838", darkcolor="#383838")
    s.map("Side.TButton", background=[("pressed", "#2a2a2a"), ("active", "#444444")])

    for prefix, bg, acc in (("", BG, ACCENT), ("Side.", PANEL, NV)):
        s.configure(f"{prefix}TCheckbutton", background=bg, foreground=FG, indicatorbackground=TROUGH,
                    indicatorforeground=BG, indicatorrelief="flat", indicatormargin=(0, 0, 6, 0))
        s.map(f"{prefix}TCheckbutton", background=[("active", bg)],
              indicatorbackground=[("selected", acc), ("active", "#4a4a4a")])
    s.configure("Side.TCheckbutton", font=FONT_B)

    # Preset picker: dark editable combobox (type a new name, or pick a saved one).
    s.configure("TCombobox", fieldbackground=TROUGH, background="#333333", foreground=FG, arrowcolor=FG,
                bordercolor="#3d3d3d", lightcolor=TROUGH, darkcolor=TROUGH, insertcolor=FG,
                selectbackground=ACCENT, selectforeground=BG, padding=(6, 2))
    s.map("TCombobox", fieldbackground=[("readonly", TROUGH)], background=[("active", "#3d3d3d")],
          bordercolor=[("focus", ACCENT)])
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", BG)
    root.option_add("*TCombobox*Listbox.font", FONT)

    # Hotkey editor: list + entry fields.
    s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, bordercolor=TROUGH,
                lightcolor=PANEL, darkcolor=PANEL, rowheight=22)
    s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", BG)])
    s.configure("Treeview.Heading", background="#333333", foreground=MUTED, bordercolor=TROUGH,
                lightcolor="#333333", darkcolor="#333333", relief="flat")
    s.map("Treeview.Heading", background=[("active", "#3d3d3d")])
    s.configure("TEntry", fieldbackground=TROUGH, foreground=FG, insertcolor=FG, bordercolor="#3d3d3d",
                lightcolor=TROUGH, darkcolor=TROUGH, padding=(6, 2))
    s.map("TEntry", bordercolor=[("focus", ACCENT)], fieldbackground=[("readonly", TROUGH)])


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


class MessageLabel(ttk.Label):
    """Status line that takes no space while empty (grid_remove remembers its place)."""

    def configure(self, cnf=None, **kw):
        result = super().configure(cnf, **kw)
        if "text" in kw and self.winfo_manager() in ("grid", ""):
            if kw["text"]:
                self.grid()
            else:
                self.grid_remove()
        return result

    config = configure


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
        self.scale.grid(row=r, column=1, padx=8, pady=5)
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


class HotkeyDialog:
    """Edit the global hotkeys. Hotkeys are switched off while this is open, so pressing a combination
    to record it never fires it."""

    PROMPT = "Click here, then press the keys"

    def __init__(self, app):
        self.app = app
        self.entries = [dict(e) for e in app.hotkey_entries]
        self.vk = None
        app.stop_hotkeys()
        top = self.top = tk.Toplevel(app.root)
        top.title("HDRDesk hotkeys")
        top.configure(bg=BG)
        top.transient(app.root)
        top.resizable(False, False)
        top.attributes("-topmost", app.pin.get())
        top.protocol("WM_DELETE_WINDOW", self.close)
        dark_titlebar(top)

        frm = ttk.Frame(top, padding=(14, 12, 14, 10))
        frm.grid(sticky="nsew")
        lst = ttk.Frame(frm)
        lst.grid(row=0, column=0, columnspan=4, sticky="ew")
        self.tree = ttk.Treeview(lst, columns=("keys", "control", "action"), show="headings", height=8,
                                 selectmode="extended")
        for col, text, w in (("keys", "Hotkey", 170), ("control", "Slider", 130), ("action", "Action", 120)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=w, anchor="w", stretch=False)
        self.tree.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Button-1>", lambda e: self.tree.focus_set(), add="+")
        self.tree.bind("<Delete>", lambda e: (self.remove(), "break")[1])
        self.tree.bind("<Button-3>", self.on_right_click)
        self.menu = tk.Menu(top, tearoff=0, bg=PANEL, fg=FG, activebackground=ACCENT, activeforeground=BG,
                            bd=0, relief="flat")
        self.menu.add_command(label="Delete", command=self.remove)
        bar = ttk.Frame(lst)
        bar.pack(fill="x", pady=(4, 0))
        ttk.Label(bar, text="Right-click or press Del to delete (Ctrl/Shift+click for several)",
                  style="Hint.TLabel").pack(side="left")
        ttk.Button(bar, text="Delete selected", command=self.remove, takefocus=0).pack(side="right")

        ttk.Label(frm, text="Keys", style="Name.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 2))
        self.key_var = tk.StringVar(value=self.PROMPT)
        self.key_entry = ttk.Entry(frm, textvariable=self.key_var, width=30)
        self.key_entry.grid(row=1, column=1, columnspan=3, sticky="ew", pady=(10, 2))
        self.key_entry.bind("<KeyPress>", self.on_key)
        self.key_entry.bind("<FocusIn>", lambda e: self.key_entry.after_idle(self.key_entry.select_clear))
        mods = ttk.Frame(frm)
        mods.grid(row=2, column=1, columnspan=3, sticky="w")
        self.mod_vars = {}
        for flag, text in ((hotkeys.MOD_CONTROL, "Ctrl"), (hotkeys.MOD_ALT, "Alt"),
                           (hotkeys.MOD_SHIFT, "Shift"), (hotkeys.MOD_WIN, "Win")):
            v = self.mod_vars[flag] = tk.BooleanVar()
            ttk.Checkbutton(mods, text=text, variable=v, takefocus=0,
                            command=self.refresh_keys).pack(side="left", padx=(0, 10))

        ttk.Label(frm, text="Slider", style="Name.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 2))
        self.labels = {key: t[0] for key, t in app.hotkey_targets().items()}
        self.by_label = {v: k for k, v in self.labels.items()}
        self.target_var = tk.StringVar(value=next(iter(self.labels.values())))
        tbox = ttk.Combobox(frm, textvariable=self.target_var, values=list(self.labels.values()),
                            state="readonly", width=18)
        tbox.grid(row=3, column=1, sticky="w", pady=(8, 2))
        tbox.bind("<<ComboboxSelected>>", lambda e: self.refresh_hint())

        ttk.Label(frm, text="Action", style="Name.TLabel").grid(row=4, column=0, sticky="w", pady=2)
        self.mode_var = tk.StringVar(value="Nudge by")
        act = ttk.Frame(frm)
        act.grid(row=4, column=1, columnspan=3, sticky="w", pady=2)
        mbox = ttk.Combobox(act, textvariable=self.mode_var, values=["Nudge by", "Set to"], state="readonly",
                            width=9)
        mbox.pack(side="left")
        mbox.bind("<<ComboboxSelected>>", lambda e: self.refresh_hint())
        self.value_var = tk.StringVar(value="5")
        ttk.Entry(act, textvariable=self.value_var, width=8).pack(side="left", padx=(6, 0))
        self.hint = ttk.Label(frm, text="", style="Hint.TLabel")
        self.hint.grid(row=5, column=1, columnspan=3, sticky="w")

        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Button(btns, text="Save hotkey", command=self.save, takefocus=0).pack(side="left")
        ttk.Button(btns, text="Close", command=self.close, takefocus=0).pack(side="right")
        ttk.Checkbutton(frm, text="Show a notification when a hotkey is used (not over fullscreen apps)",
                        variable=app.toasts_on, command=app.save_state, takefocus=0).grid(
            row=7, column=0, columnspan=4, sticky="w", pady=(10, 0))
        self.msg = ttk.Label(frm, text="", style="Status.TLabel", wraplength=420)
        self.msg.grid(row=8, column=0, columnspan=4, sticky="w", pady=(6, 0))

        self.fill_tree()
        self.refresh_hint()
        top.grab_set()
        self.key_entry.focus_set()

    # -- helpers --
    def mods(self):
        return sum(f for f, v in self.mod_vars.items() if v.get())

    def target(self):
        return self.by_label[self.target_var.get()]

    def fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, e in enumerate(self.entries):
            self.tree.insert("", "end", iid=str(i), values=(hotkeys.combo_text(e["mods"], e["vk"]),
                                                            self.labels[e["target"]], self.app.action_text(e)))

    def refresh_keys(self):
        if self.vk is None:
            self.key_var.set(self.PROMPT)
            return
        self.key_var.set(hotkeys.combo_text(self.mods(), self.vk))
        bad = hotkeys.invalid_reason(self.mods(), self.vk)
        note = hotkeys.warning(self.mods(), self.vk)
        self.msg.configure(text=f"{bad}." if bad else f"Heads up: {note}. You can still save it." if note else "")

    def refresh_hint(self):
        label, lo, hi, scale = self.app.hotkey_targets()[self.target()]
        fmt = (lambda v: f"{v / scale:.2f}") if scale != 1 else str
        if self.mode_var.get() == "Set to":
            self.hint.configure(text=f"{label}: a value from {fmt(lo)} to {fmt(hi)}")
        else:
            step = "0.05" if scale != 1 else "5"
            self.hint.configure(text=f"{label}: amount to add, e.g. {step} or -{step} (range {fmt(lo)} to {fmt(hi)})")

    def on_key(self, e):
        vk = e.keycode
        if vk in hotkeys.MODIFIER_VKS:
            return "break"
        u = ctypes.windll.user32
        down = lambda *vks: any(u.GetAsyncKeyState(k) & 0x8000 for k in vks)  # noqa: E731
        for flag, vks in ((hotkeys.MOD_CONTROL, (0x11,)), (hotkeys.MOD_ALT, (0x12,)),
                          (hotkeys.MOD_SHIFT, (0x10,)), (hotkeys.MOD_WIN, (0x5B, 0x5C))):
            self.mod_vars[flag].set(down(*vks))
        self.vk = vk
        self.refresh_keys()
        return "break"

    def on_right_click(self, e):
        row = self.tree.identify_row(e.y)
        if not row:
            return
        if row not in self.tree.selection():  # right-clicking outside the selection selects that row
            self.tree.selection_set(row)
        self.tree.focus_set()
        self.menu.entryconfigure(0, label="Delete" if len(self.tree.selection()) == 1
                                 else f"Delete {len(self.tree.selection())} hotkeys")
        self.menu.tk_popup(e.x_root, e.y_root)

    def on_select(self, _e=None):
        sel = self.tree.selection()
        if len(sel) != 1:  # load a hotkey into the form only when exactly one is selected
            return
        e = self.entries[int(sel[0])]
        self.vk = e["vk"]
        for flag, v in self.mod_vars.items():
            v.set(bool(e["mods"] & flag))
        self.refresh_keys()
        self.target_var.set(self.labels[e["target"]])
        self.mode_var.set("Set to" if e["mode"] == "set" else "Nudge by")
        scale = self.app.hotkey_targets()[e["target"]][3]
        self.value_var.set(f"{e['value'] / scale:g}")
        self.refresh_hint()

    # -- actions --
    def save(self):
        if self.vk is None:
            self.msg.configure(text="Click the Keys box and press the combination first.")
            return
        mods = self.mods()
        bad = hotkeys.invalid_reason(mods, self.vk)
        if bad:
            self.msg.configure(text=f"{bad}.")
            return
        label, lo, hi, scale = self.app.hotkey_targets()[self.target()]
        try:
            raw = round(float(self.value_var.get().replace(",", ".")) * scale)
        except ValueError:
            self.msg.configure(text="Enter a number for the value.")
            return
        mode = "set" if self.mode_var.get() == "Set to" else "nudge"
        if mode == "set" and not lo <= raw <= hi:
            self.msg.configure(text=f"{label} goes from {lo / scale:g} to {hi / scale:g}.")
            return
        if mode == "nudge" and (raw == 0 or abs(raw) > hi - lo):
            self.msg.configure(text=f"Nudge by a non-zero amount up to {(hi - lo) / scale:g}.")
            return
        entry = {"mods": mods, "vk": self.vk, "target": self.target(), "mode": mode, "value": raw}
        same = [i for i, e in enumerate(self.entries) if (e["mods"], e["vk"]) == (mods, self.vk)]
        if same:
            self.entries[same[0]] = entry  # same keys: update that hotkey
        else:
            self.entries.append(entry)
        self.fill_tree()
        self.msg.configure(text="")
        self.app.set_hotkeys(self.entries)

    def remove(self):
        sel = self.tree.selection()
        if not sel:
            self.msg.configure(text="Select a hotkey in the list to delete it.")
            return
        drop = {int(i) for i in sel}
        self.entries = [e for i, e in enumerate(self.entries) if i not in drop]
        self.fill_tree()
        self.msg.configure(text="")
        self.app.set_hotkeys(self.entries)

    def close(self):
        self.top.grab_release()
        self.top.destroy()
        self.app.hotkey_dialog = None
        self.app.start_hotkeys()


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
        head = ttk.Frame(frm)
        head.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Label(head, text=self.disp.friendly or "Primary display", style="Head.TLabel").pack(side="left")
        self.hdr_btn = ttk.Button(head, text="RTX HDR  ▸", width=10, style="Small.TButton", command=self.toggle_hdr_panel,
                                  takefocus=0)
        self.hdr_btn.pack(side="right")

        specs = [("brightness", "Brightness", -100, 100, fmt_signed, 0),
                 ("contrast", "Contrast", -100, 100, fmt_signed, 0),
                 ("gamma", "Gamma", 30, 280, lambda v: f"{v / 100:.2f}", 100)]
        for r, (key, text, lo, hi, fmt, dflt) in enumerate(specs, start=3):
            self.rows[key] = Row(self, frm, r, key, text, lo, hi, fmt,
                                 self.ramp_values[r - 3], dflt, self.on_ramp_change)
        if self.ramp_unknown:
            for key in ("brightness", "contrast", "gamma"):
                self.rows[key].val.configure(text="Unknown")
        ttk.Button(frm, text="Reset colour", style="Small.TButton", command=self.reset_ramp, takefocus=0).grid(
            row=6, column=1, columnspan=2, sticky="e", pady=(2, 0))

        ac = self.disp.advanced_color()
        sdr_now = round((self.disp.sdr_white_nits() - 80) / 4)
        self.rows["sdr"] = Row(self, frm, 11, "sdr", "SDR content", 0, 100,
                               lambda v: f"{80 + 4 * v} nits", sdr_now, None, self.on_sdr_change)
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
        self.rows["night"] = Row(self, frm, 8, "night", "Night Light", 0, 100,
                                  lambda v: f"{v} %", nl["strength"], None, self.on_night_change)
        self.night_on = tk.BooleanVar(value=nl["enabled"])
        self.rows["night"].name.grid_remove()
        self.night_toggle = ttk.Checkbutton(frm, text="Night Light", variable=self.night_on,
                                            command=self.on_night_toggle, takefocus=0)
        self.night_toggle.grid(row=8, column=0, sticky="w")
        if not self.night_available:
            self.rows["night"].set_enabled(False)
            self.rows["night"].val.configure(text="Unavailable")
            self.night_toggle.state(["disabled"])

        # Highlight cap (HDR only): soft nits ceiling in the GPU LUT, on the PQ signal itself.
        self.rows["cap"] = Row(self, frm, 12, "cap", "Highlight cap", *hdrcap.CAP_RANGE,
                               lambda v: f"{v} nits", self.state["cap_nits"], hdrcap.CAP_DEFAULT,
                               self.on_cap_change)
        self.rows["knee"] = Row(self, frm, 13, "knee", "Cap knee", *hdrcap.KNEE_RANGE,
                                lambda v: f"{v}%·{self.rows['cap'].value * v // 100} nits",
                                self.state["cap_knee"], hdrcap.KNEE_DEFAULT, self.on_cap_change)
        self.cap_on = tk.BooleanVar(value=live_cap)
        self.rows["cap"].name.grid_remove()
        self.cap_toggle = ttk.Checkbutton(frm, text="Highlight cap", variable=self.cap_on,
                                          command=self.on_cap_toggle, takefocus=0)
        self.cap_toggle.grid(row=12, column=0, sticky="w")
        self.cap_reset_btn = ttk.Button(frm, text="Reset cap", style="Small.TButton", command=self.reset_cap,
                                        takefocus=0)
        self.cap_reset_btn.grid(row=14, column=1, columnspan=2, sticky="e", pady=(2, 0))
        ttk.Label(frm, text="HDR", style="Section.TLabel").grid(row=10, column=0, sticky="w", pady=(0, 1))
        self.cap_available = None
        self.update_cap_available(ac["enabled"])
        # Layout: 3-6 desktop colour | 8 Night Light | 10-14 HDR group | 16 presets | 18-21 bottom; gaps between.
        for gap in (7, 9, 15, 17):
            frm.grid_rowconfigure(gap, minsize=14)
        # Up/Down follows the visual order.
        self.rows = {k: self.rows[k] for k in ("brightness", "contrast", "gamma", "night", "sdr", "cap", "knee")}

        # Presets: pick one to apply it; type a name and Save to store the current settings.
        self.presets = presets.PresetStore(self.state.get("presets"))
        pre = ttk.Frame(frm)
        pre.grid(row=16, column=0, columnspan=3, sticky="ew")
        ttk.Label(pre, text="Preset", style="Name.TLabel", width=12).pack(side="left")
        last = self.state.get("preset", "")
        self.preset_var = tk.StringVar(value=last if last in self.presets.items else "")
        self.preset_box = ttk.Combobox(pre, textvariable=self.preset_var, values=self.presets.names(),
                                       width=20, takefocus=0)
        self.preset_box.pack(side="left", padx=(8, 6), fill="x", expand=True)
        self.preset_box.bind("<<ComboboxSelected>>", lambda e: self.load_preset(self.preset_var.get()))
        self.preset_box.bind("<Return>", lambda e: self.save_preset())
        ttk.Button(pre, text="Save", width=5, style="Small.TButton", command=self.save_preset,
                   takefocus=0).pack(side="left")
        ttk.Button(pre, text="Delete", width=6, style="Small.TButton", command=self.delete_preset,
                   takefocus=0).pack(side="left", padx=(6, 0))

        bottom = ttk.Frame(frm)
        bottom.grid(row=18, column=0, columnspan=3, sticky="ew")
        ttk.Button(bottom, text="Hotkeys…", style="Small.TButton", command=self.open_hotkeys,
                   takefocus=0).pack(side="left")
        self.pin = tk.BooleanVar(value=True)
        ttk.Checkbutton(bottom, text="Always on top", variable=self.pin, takefocus=0,
                        command=lambda: root.attributes("-topmost", self.pin.get())).pack(side="right")
        ttk.Label(frm, text="↑↓ select   ←→ adjust   Shift fine   Ctrl coarse   hold to slide   Del default",
                  style="Hint.TLabel").grid(row=19, column=0, columnspan=3, sticky="w", pady=(10, 0))

        self.status = MessageLabel(frm, text=self.night_error, style="Status.TLabel")
        self.status.grid(row=20, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.status.configure(text=self.night_error)
        self.ramp_notice = MessageLabel(frm, text=self.ramp_warning, style="Status.TLabel")
        self.ramp_notice.grid(row=21, column=0, columnspan=3, sticky="w")
        self.ramp_notice.configure(text=self.ramp_warning)

        self._build_hdr_panel(root)
        if self.state.get("hdr_open"):
            self.toggle_hdr_panel()

        # expose scales by key (used by selftest.py)
        self.sliders = {k: r.scale for k, r in self.rows.items()}
        self.side_rows = {r.key: r for r in self.hdr_rows}
        self.sliders.update({r.key: r.scale for r in self.hdr_rows})

        # Global hotkeys (registered on their own thread; presses are handled here via a queue).
        self.hotkey_queue, self.hotkey_listener, self.hotkey_dialog = queue.Queue(), None, None
        self.toasts_on = tk.BooleanVar(value=bool(self.state.get("hotkey_toasts", True)))
        self.toast = toast.Toast(root, bg=PANEL, fg=FG, muted=MUTED, accent=ACCENT, trough=TROUGH)
        self.hotkey_entries = hotkeys.normalize(self.state.get("hotkeys"), self.hotkey_targets())
        self.start_hotkeys()
        root.after(30, self.poll_hotkeys)

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

    # ---- global hotkeys: nudge a slider, or set it to a value ----
    def hotkey_rows(self):
        return {**self.rows, **{r.key: r for r in self.hdr_rows}}

    def hotkey_targets(self):
        """key -> (label, lo, hi, scale); values are stored in raw slider units (gamma x100)."""
        labels = {"brightness": "Brightness", "contrast": "Contrast", "gamma": "Gamma", "night": "Night Light",
                  "sdr": "SDR content", "cap": "Highlight cap", "knee": "Cap knee", "hdr_peak": "RTX peak",
                  "hdr_midgrey": "RTX middle grey", "hdr_contrast": "RTX contrast",
                  "hdr_saturation": "RTX saturation"}
        rows = self.hotkey_rows()
        return {k: (labels[k], rows[k].lo, rows[k].hi, 100 if k == "gamma" else 1) for k in labels if k in rows}

    def action_text(self, e):
        scale = self.hotkey_targets()[e["target"]][3]
        v = e["value"] / scale
        num = f"{v:.2f}" if scale != 1 else f"{e['value']}"
        if e["mode"] == "set":
            return f"Set to {num}"
        return f"Nudge {'+' if v > 0 else ''}{num}"

    def start_hotkeys(self):
        self.stop_hotkeys()
        if self.hotkey_entries:
            entries = list(self.hotkey_entries)
            self.hotkey_listener = hotkeys.Listener(
                entries, lambda i: self.hotkey_queue.put(("press", entries[i])),
                lambda bad: self.hotkey_queue.put(("failed", [entries[i] for i in bad])))

    def stop_hotkeys(self):
        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
            self.hotkey_listener = None

    def set_hotkeys(self, entries):
        self.hotkey_entries = hotkeys.normalize(entries, self.hotkey_targets())
        self.save_state()

    def open_hotkeys(self):
        if self.hotkey_dialog is None:
            self.hotkey_dialog = HotkeyDialog(self)
        else:
            self.hotkey_dialog.top.lift()

    def poll_hotkeys(self):
        try:
            while True:
                kind, data = self.hotkey_queue.get_nowait()
                if kind == "press":
                    self.run_hotkey(data)
                else:
                    names = ", ".join(hotkeys.combo_text(e["mods"], e["vk"]) for e in data)
                    self.status.configure(text=f"Windows or another app owns this hotkey: {names}")
        except queue.Empty:
            pass
        self.root.after(30, self.poll_hotkeys)

    def run_hotkey(self, e):
        row = self.hotkey_rows().get(e["target"])
        if row is None:
            return
        label = self.hotkey_targets()[e["target"]][0]
        if not row.enabled:
            self.status.configure(text=f"{label} is unavailable right now")
            self.notify(label, "Unavailable")
            return
        row.set(row.value + e["value"] if e["mode"] == "nudge" else e["value"])
        self.notify(label, row.fmt(row.value), (row.value - row.lo) / (row.hi - row.lo))

    def notify(self, title, value, fraction=None):
        """Hotkey feedback toast: optional, and never over a fullscreen game / video."""
        if not self.toasts_on.get():
            return
        if toast.fullscreen_active(own_hwnds=(self.toast.hwnd(),)):
            self.toast.hide()
            return
        self.toast.show(title, value, fraction)

    # ---- presets: named snapshots of every control ----
    def capture_preset(self):
        p = {k: self.rows[k].value for k in RAMP_KEYS}
        p.update(cap_on=self.cap_on.get(), cap_nits=self.rows["cap"].value, cap_knee=self.rows["knee"].value)
        if self.night_available:
            p.update(night_on=self.night_on.get(), night=self.rows["night"].value)
        if self.disp.advanced_color()["enabled"]:
            p["sdr"] = self.rows["sdr"].value
        if self.hdr_available:
            p["rtx_on"] = self.hdr_on.get()
            p.update({"rtx_" + r.key[4:]: r.value for r in self.hdr_rows})
        return p

    def apply_preset(self, p):
        """Set every control the preset holds, then push each group to the system once.
        Parts that can't apply right now (HDR off, Night Light / RTX unavailable) are skipped."""
        self.cancel_repeat()
        # Desktop colour + highlight cap: one LUT write.
        if any(k in p for k in RAMP_KEYS + ("cap_on", "cap_nits", "cap_knee")):
            for key, pkey in (("brightness", "brightness"), ("contrast", "contrast"), ("gamma", "gamma"),
                              ("cap", "cap_nits"), ("knee", "cap_knee")):
                if pkey in p:
                    self.rows[key].set(p[pkey], notify=False)
            if "cap_on" in p:
                self.cap_on.set(p["cap_on"])
            if self.cap_available:
                for key in ("cap", "knee"):
                    self.rows[key].val.configure(text=self.rows[key].fmt(self.rows[key].value))
            self.ramp_unknown = False
            self.ramp_notice.configure(text="")
            for key in RAMP_KEYS:
                self.rows[key].val.configure(text=self.rows[key].fmt(self.rows[key].value))
            self.apply_ramp()
        if "sdr" in p and self.disp.advanced_color()["enabled"]:
            self.rows["sdr"].set(p["sdr"], notify=False)
            self.apply_sdr()
        if self.night_available and ("night" in p or "night_on" in p):
            if self.pending_night is not None:
                self.root.after_cancel(self.pending_night)
                self.pending_night = None
            try:
                cur = self.night_ctl.read()
                if "night" in p:
                    self.rows["night"].set(p["night"], notify=False)
                    if cur["strength"] != p["night"]:
                        self.night_ctl.set_strength(p["night"])
                if "night_on" in p:
                    self.night_on.set(p["night_on"])
                    if cur["enabled"] != p["night_on"]:
                        self.night_ctl.set_enabled(p["night_on"])
                self.night_last_apply = time.monotonic()
            except (OSError, ValueError) as exc:
                self.status.configure(text=f"Night Light: {exc}")
        if self.hdr_available and any(k.startswith("rtx_") for k in p):
            if "rtx_on" in p:
                self.hdr_on.set(p["rtx_on"])
            for r in self.hdr_rows:
                if "rtx_" + r.key[4:] in p:
                    r.set(p["rtx_" + r.key[4:]], notify=False)
            self.apply_hdr()

    def load_preset(self, name):
        p = self.presets.get(name)
        if p:
            self.preset_var.set(name)
            self.apply_preset(p)
            self.save_state()  # remember the last-used preset
        self.rows["brightness"].scale.focus_set()  # keep arrow keys on the sliders

    def save_preset(self):
        name = presets.clean_name(self.preset_var.get())
        if not name:
            self.status.configure(text="Type a name in the Preset box, then Save.")
            return "break"
        name = self.presets.save(name, self.capture_preset())
        self.preset_box.configure(values=self.presets.names())
        self.preset_var.set(name)
        self.status.configure(text="")
        self.save_state()
        self.rows["brightness"].scale.focus_set()
        return "break"

    def delete_preset(self):
        name = self.preset_var.get()
        if name not in self.presets.items:
            self.status.configure(text="Pick a saved preset to delete.")
            return
        if not messagebox.askyesno("HDRDesk", f'Delete preset "{name}"?', parent=self.root):
            return
        self.presets.delete(name)
        self.preset_box.configure(values=self.presets.names())
        self.preset_var.set("")
        self.status.configure(text="")
        self.save_state()

    def save_state(self):
        data = {k: self.rows[k].value for k in RAMP_KEYS}
        data.update(x=self.root.winfo_x(), y=self.root.winfo_y(), hdr_open=self.hdr_open,
                    cap_on=self.cap_on.get(), cap_nits=self.rows["cap"].value, cap_knee=self.rows["knee"].value,
                    presets=self.presets.to_json(), hotkeys=self.hotkey_entries,
                    hotkey_toasts=self.toasts_on.get(),
                    preset=self.preset_var.get() if self.preset_var.get() in self.presets.items else "")
        tmp = STATE + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(data, f, indent=1)
            os.replace(tmp, STATE)  # never leave a half-written settings.json (presets live there)
        except OSError as exc:
            self.status.configure(text=f"Could not save settings: {exc}")

    def on_close(self):
        if self.pending_night is not None:
            self.root.after_cancel(self.pending_night)
            self.apply_night()
        self.stop_hotkeys()
        self.save_state()
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
