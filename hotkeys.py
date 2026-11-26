"""Global hotkeys: each one nudges a slider by an amount or sets it to a value.

Entries are plain dicts stored in settings.json:
    {"mods": 3, "vk": 0x75, "target": "brightness", "mode": "nudge" | "set", "value": -10}
`mods` uses RegisterHotKey's flags; `value` is in the slider's raw units (gamma is x100).

Any key combination may be used. warning() describes combinations that Windows or most apps already
rely on (window switching, the HDR toggle Win+Alt+B, the graphics-driver reset Win+Ctrl+Shift+B, plain
typing...) so the editor can point that out; it never blocks saving. Windows itself still refuses to
hand over some combinations (e.g. Ctrl+Alt+Del, or ones another app owns): Listener reports those as
failed. invalid_reason() only rejects what can't be a hotkey at all. Listener registers the hotkeys on its own
thread (RegisterHotKey needs a message loop on the registering thread) and reports presses through
a callback; the UI must hop back to its own thread before touching widgets.
"""
import ctypes
import ctypes.wintypes as W
import threading

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
MOD_MASK = MOD_ALT | MOD_CONTROL | MOD_SHIFT | MOD_WIN
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

VK_TAB, VK_RETURN, VK_PAUSE, VK_ESCAPE, VK_SPACE = 0x09, 0x0D, 0x13, 0x1B, 0x20
VK_PRIOR, VK_NEXT, VK_END, VK_HOME, VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN = range(0x21, 0x29)
VK_SNAPSHOT, VK_INSERT, VK_DELETE = 0x2C, 0x2D, 0x2E
VK_F1, VK_F4, VK_F12, VK_F13, VK_F24 = 0x70, 0x73, 0x7B, 0x7C, 0x87
MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}
LOCK_VKS = {0x14, 0x90, 0x91}  # Caps / Num / Scroll Lock

# Keys that type nothing: OK with a single modifier. Everything else (letters, digits, punctuation,
# space) types text, so it needs two or more modifiers to avoid hijacking typing / app shortcuts.
NON_TYPING = (set(range(VK_F1, VK_F24 + 1)) | set(range(VK_PRIOR, VK_DOWN + 1))
              | {VK_INSERT, VK_DELETE, VK_PAUSE, VK_SNAPSHOT} | set(range(0x60, 0x70)))  # numpad


def _v(ch):
    return ord(ch.upper())


A, C, S, W_ = MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN
# Exact combinations that stay off-limits even with enough modifiers.
RESERVED = {
    (C | A, VK_DELETE): "Ctrl+Alt+Del is the secure attention sequence",
    (C | S, VK_ESCAPE): "Ctrl+Shift+Esc opens Task Manager",
    (C | A, VK_TAB): "Ctrl+Alt+Tab is the window switcher",
    (A | S, VK_TAB): "Alt+Shift+Tab is the window switcher",
    (A | S, VK_ESCAPE): "Alt+Shift+Esc switches windows",
    (W_ | C | S, _v("B")): "Win+Ctrl+Shift+B resets the graphics driver",
    (W_ | A, _v("B")): "Win+Alt+B toggles Windows HDR",
    (W_ | S, _v("S")): "Win+Shift+S is Snipping Tool",
    (W_ | C, _v("D")): "Win+Ctrl+D creates a virtual desktop",
    (W_ | C, VK_F4): "Win+Ctrl+F4 closes the virtual desktop",
    (W_ | C, VK_LEFT): "Win+Ctrl+Left switches virtual desktop",
    (W_ | C, VK_RIGHT): "Win+Ctrl+Right switches virtual desktop",
    (W_ | S, VK_LEFT): "Win+Shift+Left moves the window to another monitor",
    (W_ | S, VK_RIGHT): "Win+Shift+Right moves the window to another monitor",
    (W_ | S, VK_UP): "Win+Shift+Up stretches the window",
    (W_ | S, VK_DOWN): "Win+Shift+Down restores the window",
    (W_ | S, _v("M")): "Win+Shift+M restores minimised windows",
    (W_ | C, VK_RETURN): "Win+Ctrl+Enter toggles Narrator",
    (W_ | C, _v("C")): "Win+Ctrl+C toggles colour filters",
    (W_ | C, _v("O")): "Win+Ctrl+O opens the on-screen keyboard",
    (W_ | C, _v("Q")): "Win+Ctrl+Q opens Quick Assist",
    (W_ | C, _v("F")): "Win+Ctrl+F searches for devices",
    (W_ | A, _v("R")): "Win+Alt+R records with Game Bar",
    (W_ | A, _v("G")): "Win+Alt+G records with Game Bar",
    (W_ | A, VK_SNAPSHOT): "Win+Alt+PrtSc is a Game Bar screenshot",
    (W_ | A, _v("K")): "Win+Alt+K mutes the mic in calls",
    (W_ | A, VK_RETURN): "Win+Alt+Enter opens taskbar settings",
}
# Single-modifier combinations on non-typing keys that Windows owns.
RESERVED_SINGLE = {
    (A, VK_TAB): "Alt+Tab is the window switcher",
    (A, VK_ESCAPE): "Alt+Esc switches windows",
    (A, VK_F4): "Alt+F4 closes windows",
    (A, VK_SPACE): "Alt+Space opens the window menu",
    (A, VK_RETURN): "Alt+Enter toggles full screen / properties",
    (C, VK_ESCAPE): "Ctrl+Esc opens Start",
    (C, VK_TAB): "Ctrl+Tab switches tabs",
    (C, VK_F4): "Ctrl+F4 closes tabs",
    (S, VK_DELETE): "Shift+Del deletes permanently / cuts",
    (S, VK_INSERT): "Shift+Ins pastes",
    (C, VK_INSERT): "Ctrl+Ins copies",
}


def invalid_reason(mods, vk):
    """'' if (mods, vk) can be a hotkey at all, else why not (only a lone modifier / no key)."""
    if not 0 < vk < 0xFF or vk in MODIFIER_VKS:
        return "Press a key other than Ctrl, Alt, Shift or Win"
    return ""


def warning(mods, vk):
    """'' if nothing else is likely to use this combination, else a short note on what it overrides.
    Advisory only: every valid combination can be saved."""
    mods &= MOD_MASK
    if invalid_reason(mods, vk):
        return ""
    if vk in LOCK_VKS:
        return "it also toggles that lock"
    if vk == VK_SNAPSHOT and not mods:
        return "PrtSc is the screenshot key"
    if vk == VK_F12 and not mods:
        return "F12 is reserved by Windows for debuggers"
    if (mods, vk) in RESERVED:
        return RESERVED[(mods, vk)]
    if (mods, vk) in RESERVED_SINGLE:
        return RESERVED_SINGLE[(mods, vk)]
    if mods == MOD_WIN:
        return "Win+key shortcuts usually belong to Windows"
    if not mods:
        if VK_F13 <= vk <= VK_F24:
            return ""
        return "on its own this key stops working in every app while HDRDesk runs"
    typing = vk not in NON_TYPING
    if typing and bin(mods).count("1") < 2:
        return "with one modifier this overrides typing or common app shortcuts everywhere while HDRDesk runs"
    return ""


_NAMES = {VK_TAB: "Tab", VK_RETURN: "Enter", VK_PAUSE: "Pause", VK_ESCAPE: "Esc", VK_SPACE: "Space",
          VK_PRIOR: "PgUp", VK_NEXT: "PgDn", VK_END: "End", VK_HOME: "Home", VK_LEFT: "Left", VK_UP: "Up",
          VK_RIGHT: "Right", VK_DOWN: "Down", VK_SNAPSHOT: "PrtSc", VK_INSERT: "Ins", VK_DELETE: "Del",
          0x6A: "Num *", 0x6B: "Num +", 0x6D: "Num -", 0x6E: "Num .", 0x6F: "Num /"}


def key_name(vk):
    if vk in _NAMES:
        return _NAMES[vk]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if VK_F1 <= vk <= VK_F24:
        return f"F{vk - VK_F1 + 1}"
    if 0x60 <= vk <= 0x69:
        return f"Num {vk - 0x60}"
    try:  # punctuation etc.: ask the keyboard layout
        user32 = ctypes.windll.user32
        sc = user32.MapVirtualKeyW(vk, 0)
        buf = ctypes.create_unicode_buffer(32)
        if sc and user32.GetKeyNameTextW(sc << 16, buf, 32):
            return buf.value
    except (AttributeError, OSError):
        pass
    return f"VK {vk:#04x}"


def combo_text(mods, vk):
    parts = [n for f, n in ((MOD_WIN, "Win"), (MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift"))
             if mods & f]
    return "+".join(parts + [key_name(vk)])


def normalize(entries, targets):
    """Keep well-formed, valid, non-duplicate entries whose target exists."""
    out, seen = [], set()
    if not isinstance(entries, list):
        return out
    for e in entries:
        try:
            mods, vk = int(e["mods"]) & MOD_MASK, int(e["vk"])
            target, mode, value = str(e["target"]), str(e["mode"]), int(e["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if target not in targets or mode not in ("nudge", "set") or invalid_reason(mods, vk):
            continue
        if (mods, vk) in seen:
            continue
        seen.add((mods, vk))
        out.append({"mods": mods, "vk": vk, "target": target, "mode": mode, "value": value})
    return out


class Listener:
    """Registers hotkeys on a private thread. on_press(index) and on_failed(list of indexes) are called
    from that thread."""

    def __init__(self, entries, on_press, on_failed=None):
        self.entries, self.on_press, self.on_failed = list(entries), on_press, on_failed
        self.tid, self.ready = None, threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="hotkeys")
        self.thread.start()
        self.ready.wait(2)

    def _run(self):
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        msg = W.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # create this thread's message queue
        self.tid = kernel32.GetCurrentThreadId()
        ids, failed = [], []
        for i, e in enumerate(self.entries):
            if user32.RegisterHotKey(None, i + 1, e["mods"], e["vk"]):
                ids.append(i + 1)
            else:
                failed.append(i)  # usually: another app already owns this combination
        self.ready.set()
        if failed and self.on_failed:
            self.on_failed(failed)
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and 1 <= msg.wParam <= len(self.entries):
                    self.on_press(msg.wParam - 1)
        finally:
            for hid in ids:
                user32.UnregisterHotKey(None, hid)

    def stop(self):
        if self.tid:
            ctypes.windll.user32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)
        self.thread.join(2)
