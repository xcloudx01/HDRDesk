"""Small on-screen notification for hotkey changes, in the style of the Windows volume flyout.

One reusable, borderless, click-through window near the bottom centre of the primary display's work
area: it never takes focus, updates in place when hotkeys repeat, and fades out after a moment.
fullscreen_active() reports when something fullscreen (a game, a fullscreen video, a presentation) is
in front, so callers can stay out of the way.
"""
import ctypes
import ctypes.wintypes as W
import tkinter as tk

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32

GWL_EXSTYLE = -20
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_TRANSPARENT = 0x8, 0x80, 0x20
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x80000, 0x8000000
MONITOR_DEFAULTTONEAREST = 2
SPI_GETWORKAREA = 0x30
SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}

# SHQueryUserNotificationState results that mean "don't disturb"
QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE = 2, 3, 4

user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [W.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [W.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.GetForegroundWindow.restype = W.HWND
user32.MonitorFromWindow.restype = W.HMONITOR
user32.MonitorFromWindow.argtypes = [W.HWND, W.DWORD]
user32.GetAncestor.restype = W.HWND
user32.GetAncestor.argtypes = [W.HWND, ctypes.c_uint]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT), ("dwFlags", W.DWORD)]


def fullscreen_active(own_hwnds=()):
    """True when a fullscreen app is in front (exclusive or borderless game, fullscreen video, slideshow)."""
    try:
        state = ctypes.c_int(0)
        if shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0 and state.value in (
                QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE):
            return True
        hwnd = user32.GetForegroundWindow()
        if not hwnd or hwnd in own_hwnds:
            return False
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value in SHELL_CLASSES:  # the desktop itself covers the screen
            return False
        rect = W.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        if not user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        return rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom
    except (AttributeError, OSError):
        return False


class Toast:
    SHOW_MS, FADE_MS, FADE_STEPS = 1400, 250, 10
    W_PX, H_PX = 300, 64

    def __init__(self, root, bg="#2b2b2b", fg="#e8e8e8", muted="#8f8f8f", accent="#4cc2ff", trough="#3c3c3c"):
        self.root, self.job = root, None
        self.colors = dict(bg=bg, fg=fg, muted=muted, accent=accent, trough=trough)
        self.win = None

    def _build(self):
        c = self.colors
        win = self.win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=c["accent"])  # 1 px accent border
        self.cv = tk.Canvas(win, width=self.W_PX - 2, height=self.H_PX - 2, bg=c["bg"], highlightthickness=0)
        self.cv.pack(padx=1, pady=1)
        self.title = self.cv.create_text(16, 18, anchor="w", fill=c["muted"], font=("Segoe UI", 9), text="")
        self.value = self.cv.create_text(self.W_PX - 18, 18, anchor="e", fill=c["fg"],
                                         font=("Segoe UI Semibold", 11), text="")
        self.cv.create_rectangle(16, 40, self.W_PX - 18, 46, fill=c["trough"], width=0)
        self.bar = self.cv.create_rectangle(16, 40, 16, 46, fill=c["accent"], width=0)
        win.update_idletasks()
        try:  # never take focus, let clicks pass through, stay out of Alt+Tab
            hwnd = user32.GetAncestor(win.winfo_id(), 2) or win.winfo_id()
            ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
                                     | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOPMOST)
        except (AttributeError, OSError):
            pass

    def hwnd(self):
        if self.win is None:
            return None
        return user32.GetAncestor(self.win.winfo_id(), 2) or self.win.winfo_id()

    def show(self, title, value, fraction=None):
        """title: what changed; value: its new value text; fraction: 0..1 slider position (None: no bar)."""
        if self.win is None:
            self._build()
        self.cv.itemconfigure(self.title, text=title)
        self.cv.itemconfigure(self.value, text=value)
        if fraction is None:
            self.cv.itemconfigure(self.bar, state="hidden")
        else:
            x = 16 + (self.W_PX - 34) * min(1.0, max(0.0, fraction))
            self.cv.coords(self.bar, 16, 40, x, 46)
            self.cv.itemconfigure(self.bar, state="normal")
        work = W.RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work), 0)
        x = (work.left + work.right - self.W_PX) // 2
        y = work.bottom - self.H_PX - 48
        win = self.win
        assert win is not None
        win.geometry(f"{self.W_PX}x{self.H_PX}+{x}+{y}")
        win.attributes("-alpha", 0.96)
        win.deiconify()
        win.lift()
        if self.job:
            self.root.after_cancel(self.job)
        self.job = self.root.after(self.SHOW_MS, lambda: self._fade(self.FADE_STEPS))

    def _fade(self, step):
        win = self.win
        if win is None:
            return
        if step <= 0:
            win.withdraw()
            self.job = None
            return
        win.attributes("-alpha", 0.96 * step / self.FADE_STEPS)
        self.job = self.root.after(self.FADE_MS // self.FADE_STEPS, lambda: self._fade(step - 1))

    def hide(self):
        if self.job:
            self.root.after_cancel(self.job)
            self.job = None
        if self.win is not None:
            self.win.withdraw()
