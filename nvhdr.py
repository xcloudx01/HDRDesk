"""NVIDIA RTX Video HDR ('TrueHDR') settings, stored in the NVIDIA display-adapter driver key.
Mirrors NVIDIA App > System > Video > HDR. Reading works unelevated; writing needs admin (HKLM)."""
import ctypes
import winreg as R

CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
SUFFIX = {"enabled": "TrueHDR", "peak": "TrueHDR_P", "midgrey": "TrueHDR_M",
          "contrast": "TrueHDR_C", "saturation": "TrueHDR_S"}
RANGES = {"peak": (400, 1000), "midgrey": (10, 100), "contrast": (-100, 100), "saturation": (-100, 100)}
OFFSET = {"contrast": 100, "saturation": 100}  # stored as UI value + 100
XEN_SET = 0x80000001  # companion "_XEN_" flag the NVIDIA App writes alongside each value


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def find_key():
    """Return the class subkey path of the NVIDIA adapter that carries the TrueHDR values."""
    with R.OpenKey(R.HKEY_LOCAL_MACHINE, CLASS) as cls:
        i = 0
        while True:
            try:
                sub = R.EnumKey(cls, i)
            except OSError:
                break
            i += 1
            try:
                with R.OpenKey(cls, sub) as k:
                    if "NVIDIA" not in str(R.QueryValueEx(k, "ProviderName")[0]).upper():
                        continue
                    R.QueryValueEx(k, "_User_Global_VAL_TrueHDR_P")
                    return f"{CLASS}\\{sub}"
            except OSError:
                continue
    raise RuntimeError("NVIDIA TrueHDR registry values not found (open NVIDIA App > System > Video once)")


def _value_names(k):
    names, i = [], 0
    while True:
        try:
            names.append(R.EnumValue(k, i)[0])
        except OSError:
            return names
        i += 1


def read(path=None):
    path = path or find_key()
    with R.OpenKey(R.HKEY_LOCAL_MACHINE, path) as k:
        out = {}
        for key, suf in SUFFIX.items():
            try:
                v = R.QueryValueEx(k, f"_User_Global_VAL_{suf}")[0]
            except OSError:
                v = 0 if key == "enabled" else RANGES[key][0] + OFFSET.get(key, 0)
            out[key] = bool(v) if key == "enabled" else int(v) - OFFSET.get(key, 0)
        return out


ORDER = ["enabled", "peak", "midgrey", "saturation", "contrast"]  # order the NVIDIA App writes in (procmon trace)


def _raw(key, ui):
    if key == "enabled":
        return 1 if ui else 0
    lo, hi = RANGES[key]
    return max(lo, min(hi, int(ui))) + OFFSET.get(key, 0)


def write(changes, path=None):
    """NOT LIVE: persistence only (verified: the driver ignores direct registry edits). Use nvescape.apply() instead.
    Write the full settings block exactly as nvcontainer does, then the RTXVideoFlags 'commit'.
    changes: subset of {'enabled', 'peak', 'midgrey', 'contrast', 'saturation'}; the rest keep current values."""
    path = path or find_key()
    state = {**read(path), **changes}
    with R.OpenKey(R.HKEY_LOCAL_MACHINE, path, 0, R.KEY_READ | R.KEY_SET_VALUE) as k:
        existing = _value_names(k)
        subs = sorted({n.split("_VAL_")[0] for n in existing if n.startswith("_User_SUB") and "_VAL_TrueHDR_" in n})
        dw = lambda name, v: R.SetValueEx(k, name, 0, R.REG_DWORD, v)  # noqa: E731
        for key in ORDER:
            suf, raw = SUFFIX[key], _raw(key, state[key])
            if key != "enabled":
                for sub in subs:  # per-display copies, e.g. _User_SUB0_DFP1
                    dw(f"{sub}_VAL_{suf}", raw)
                    dw(f"{sub}_XEN_{suf}", 0)
            dw(f"_User_Global_VAL_{suf}", raw)
            dw(f"_User_Global_XEN_{suf}", XEN_SET)
        try:
            flags = R.QueryValueEx(k, "_User_Global_VAL_RTXVideoFlags")[0]
        except OSError:
            flags = 257
        dw("_User_Global_VAL_RTXVideoFlags", flags)
        dw("_User_Global_XEN_RTXVideoFlags", XEN_SET)


if __name__ == "__main__":
    print(find_key())
    print(read())
