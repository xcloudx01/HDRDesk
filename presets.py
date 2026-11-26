"""Named presets: snapshots of HDRDesk's controls, stored in settings.json.

A preset is a flat dict of control values. Loading is tolerant: unknown keys are dropped, values are
clamped to each control's range, and missing keys are simply not applied, so a hand-edited or older
settings.json never breaks the app. Pure data; the UI lives in HDRDesk.pyw.
"""

# key: (kind, lo, hi)   kind "int" is clamped to lo..hi, "bool" ignores lo/hi
FIELDS = {
    "brightness": ("int", -100, 100),
    "contrast": ("int", -100, 100),
    "gamma": ("int", 30, 280),
    "night_on": ("bool", 0, 1),
    "night": ("int", 0, 100),
    "sdr": ("int", 0, 100),
    "cap_on": ("bool", 0, 1),
    "cap_nits": ("int", 80, 1000),
    "cap_knee": ("int", 50, 100),
    "rtx_on": ("bool", 0, 1),
    "rtx_peak": ("int", 400, 1000),
    "rtx_midgrey": ("int", 10, 100),
    "rtx_contrast": ("int", -100, 100),
    "rtx_saturation": ("int", -100, 100),
}
MAX_NAME = 40


def clean_name(name):
    """Trimmed, single-line name, or '' if unusable."""
    return " ".join(str(name).split())[:MAX_NAME]


def normalize(preset):
    out = {}
    if not isinstance(preset, dict):
        return out
    for key, (kind, lo, hi) in FIELDS.items():
        if key not in preset:
            continue
        v = preset[key]
        try:
            if kind == "bool":
                if not isinstance(v, (bool, int)):
                    continue
                out[key] = bool(v)
            else:
                if isinstance(v, bool):
                    continue
                out[key] = max(lo, min(hi, int(round(float(v)))))
        except (TypeError, ValueError):
            continue
    return out


class PresetStore:
    def __init__(self, data=None):
        self.items = {}
        if isinstance(data, dict):
            for name, preset in data.items():
                name, preset = clean_name(name), normalize(preset)
                if name and preset:
                    self.items[name] = preset

    def names(self):
        return sorted(self.items, key=str.casefold)

    def get(self, name):
        return dict(self.items.get(name, {}))

    def save(self, name, preset):
        """Add or overwrite. Returns the stored name, or '' if the name or preset is unusable."""
        name, preset = clean_name(name), normalize(preset)
        if not name or not preset:
            return ""
        # Overwrite an existing preset whose name differs only in case, rather than adding a near-duplicate.
        for existing in list(self.items):
            if existing.casefold() == name.casefold():
                del self.items[existing]
        self.items[name] = preset
        return name

    def delete(self, name):
        return self.items.pop(name, None) is not None

    def to_json(self):
        return {name: dict(self.items[name]) for name in self.names()}
