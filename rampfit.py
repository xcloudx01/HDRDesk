"""Read-only inference of HDRDesk's brightness/contrast/gamma from a GPU LUT.

A LUT does not uniquely encode its generating controls once clipping occurs. Accept
only a close match to the HDRDesk model; never write a candidate to the display.
"""
from math import sqrt

GAMMAS = range(30, 281)
POSITIONS = tuple(i / 255.0 for i in range(256))


def _samples(brightness, contrast, gamma):
    slope = 1.0 + contrast / 100.0
    intercept = 0.5 * (1.0 - slope) + brightness / 200.0
    exponent = 100.0 / gamma
    return tuple(round(min(1.0, max(0.0, x ** exponent * slope + intercept)) * 65535)
                 for x in POSITIONS)


def _error(samples, measured):
    return sum((a - b) ** 2 for a, b in zip(samples, measured))


def signature(ramp):
    """Immutable snapshot so a new Windows gamma LUT can be detected safely."""
    return tuple(tuple(int(v) for v in channel) for channel in ramp)


def infer_controls(ramp, preferred=None):
    """Return (brightness, contrast, gamma) or None for an unrepresentable LUT.

    Channels must be essentially equal. Result is inferred from actual display
    values, never unconditionally from a settings file. `preferred` only resolves
    ambiguities if those controls reproduce the measured LUT exactly.
    """
    try:
        channels = [tuple(int(v) for v in ramp[c]) for c in range(3)]
        if any(len(ch) != 256 for ch in channels):
            return None
        measured = channels[0]
        if any(max(abs(a - b) for a, b in zip(measured, ch)) > 256 for ch in channels[1:]):
            return None
        if any(not 0 <= v <= 65535 for v in measured):
            return None
    except (TypeError, ValueError, IndexError):
        return None

    if preferred is not None:
        try:
            b, c, g = (int(x) for x in preferred)
            if (-100 <= b <= 100 and -100 <= c <= 100 and 30 <= g <= 280
                    and max(abs(a - v) for a, v in zip(_samples(b, c, g), measured)) <= 1):
                return b, c, g
        except (TypeError, ValueError):
            pass

    interior = [(i, y / 65535.0) for i, y in enumerate(measured) if 256 < y < 65279]
    if len(interior) < 8:  # too clipped to identify the shape
        return None

    # For each gamma, fit y = slope * x**(100/gamma) + intercept using
    # unclipped samples. Then refine the nearby integer controls against the
    # whole LUT, including clipped endpoints.
    candidates = []
    for g in GAMMAS:
        transformed = [POSITIONS[i] ** (100.0 / g) for i, _ in interior]
        mean_x = sum(transformed) / len(interior)
        mean_y = sum(y for _, y in interior) / len(interior)
        denom = sum((x - mean_x) ** 2 for x in transformed)
        if denom < 1e-12:
            continue
        slope = sum((x - mean_x) * (y - mean_y) for x, (_, y) in zip(transformed, interior)) / denom
        intercept = mean_y - slope * mean_x
        b = round(200.0 * (intercept - (1.0 - slope) / 2.0))
        c = round(100.0 * (slope - 1.0))
        b = max(-100, min(100, b))
        c = max(-100, min(100, c))
        candidates.append((_error(_samples(b, c, g), measured), b, c, g))
    if not candidates:
        return None

    # Multiple nearly identical curves occur at high contrast/clipping.
    # Search a small integer neighborhood for a reproducible UI setting.
    best = min(candidates)
    for _, b0, c0, g0 in sorted(candidates)[:5]:
        for g in range(max(30, g0 - 2), min(280, g0 + 2) + 1):
            for b in range(max(-100, b0 - 2), min(100, b0 + 2) + 1):
                for c in range(max(-100, c0 - 2), min(100, c0 + 2) + 1):
                    item = (_error(_samples(b, c, g), measured), b, c, g)
                    if item < best:
                        best = item

    # RGB ramps with ICC calibration or independently adjusted channels must
    # not be misrepresented as these three global sliders.
    if sqrt(best[0] / 256) > 256:  # 0.4% full-scale RMS
        return None
    return best[1:]
