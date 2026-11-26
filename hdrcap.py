"""Highlight cap for HDR mode: a soft nits ceiling built into the GPU gamma ramp.

With Windows HDR on, the GPU gamma ramp (SetDeviceGammaRamp) acts on the PQ (SMPTE ST 2084) signal sent to the
monitor, so ramp index i stands for an absolute luminance pq_to_nits(i / 255). Measured on an AW3423DWF / RTX 3090:
a ramp clamp at index 154 (~244 nits) clipped desktop SDR content and RTX Video HDR output at the same luminance.

The curve leaves everything below the knee untouched, then rolls off smoothly (slope 1 at the knee, so no visible
kink) towards the cap, which it approaches but never exceeds. Pure functions; no display access here.
"""
from math import exp

# SMPTE ST 2084 constants
M1, M2 = 2610 / 16384, 2523 / 4096 * 128
C1, C2, C3 = 3424 / 4096, 2413 / 4096 * 32, 2392 / 4096 * 32
PQ_MAX_NITS = 10000.0

CAP_RANGE = (80, 1000)    # nits
KNEE_RANGE = (50, 100)    # knee as % of the cap
CAP_DEFAULT, KNEE_DEFAULT = 150, 70


def pq_to_nits(e):
    e = min(1.0, max(0.0, e)) ** (1 / M2)
    return PQ_MAX_NITS * (max(e - C1, 0.0) / (C2 - C3 * e)) ** (1 / M1)


def nits_to_pq(nits):
    y = (min(PQ_MAX_NITS, max(0.0, nits)) / PQ_MAX_NITS) ** M1
    return ((C1 + C2 * y) / (1 + C3 * y)) ** M2


def roll_off(nits, cap, knee_pct):
    """Identity up to the knee, then knee + span * (1 - e^(-(L - knee) / span)): continuous slope, < cap."""
    knee = cap * knee_pct / 100.0
    if nits <= knee:
        return nits
    span = cap - knee
    if span <= 0:
        return knee
    return knee + span * (1.0 - exp(-(nits - knee) / span))


def apply_to_ramp(ramp, cap, knee_pct):
    """Return a new Ramp: every channel's output (a PQ code) passed through the nits roll-off."""
    out = type(ramp)()
    for c in range(3):
        for i in range(256):
            pq = ramp[c][i] / 65535.0
            out[c][i] = int(round(nits_to_pq(roll_off(pq_to_nits(pq), cap, knee_pct)) * 65535))
    return out
