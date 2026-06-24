#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy", "numba"]
# ///
"""
dyneq — open-source dynamic EQ (per-band compression / expansion).

A dynamic EQ is a peaking filter whose gain is driven by the signal's own level
*inside that band*. Loud sibilance at 7 kHz? A "cut" band tames it only when it
spikes, leaving the rest untouched. Boomy 200 Hz only on loud notes? Same idea.

Clean-room realization (no commercial plugin decompiled). Each band is a
constant-0 dB-peak RBJ bandpass B(x); the output is the classic parallel form

    y = x + k(t) * B(x)

where k(t) = 10^(g(t)/20) - 1 and g(t) is the per-sample EQ gain in dB computed
from a standard compressor static curve on the band's own envelope, smoothed with
attack/release. k=0 -> no change; k<0 -> a dynamic cut; k>0 -> a dynamic boost.
At the band center B has unity magnitude and zero phase, so the realized peak
gain there is exactly (1 + k) -> g dB. MIT. Part of the `freefx` suite.

Usage:
  # de-ess: cut 7 kHz only when it gets loud
  uv run dyneq.py vocal.wav out.wav --band 7000:2.5:-28:4:cut

  # tame boomy low-mids on loud notes, plus a gentle dynamic air boost
  uv run dyneq.py mix.wav out.wav --band 220:1.2:-24:3:cut --band 12000:0.8:-30:2:boost \
        --attack-ms 5 --release-ms 120 --range-db 9

Band format: FREQ_HZ:Q:THRESHOLD_DB:RATIO[:MODE]   (MODE = cut | boost, default cut)
  cut   = compress the band (reduce gain) when its level rises ABOVE threshold
  boost = expand the band (raise gain) when its level falls BELOW threshold
Global timing/limits apply to every band: --attack-ms --release-ms --range-db --makeup-db
"""
import argparse, sys
import numpy as np
import soundfile as sf
from numba import njit


def bpf_0db(f0, Q, fs):
    """RBJ constant 0 dB peak-gain bandpass. Magnitude 1 (zero phase) at f0."""
    w0 = 2 * np.pi * f0 / fs
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2 * Q)
    b = np.array([alpha, 0.0, -alpha])
    a = np.array([1 + alpha, -2 * cw, 1 - alpha])
    return b / a[0], a / a[0]


@njit(cache=True)
def _dynamic_gain(band, thr_db, ratio, mode_cut, atk_c, rel_c, range_db):
    """Per-sample EQ gain (linear k = 10^(g/20)-1) from the band envelope.

    band     : isolated band signal (unity gain at center)
    thr_db   : threshold in dBFS on the band envelope
    ratio    : compression/expansion ratio (>1)
    mode_cut : True -> cut above threshold; False -> boost below threshold
    atk_c    : attack coefficient (one-pole, per sample)
    rel_c    : release coefficient
    range_db : max |gain| applied, dB
    """
    n = band.shape[0]
    k = np.empty(n, dtype=np.float64)
    env = 1e-9
    slope = 1.0 - 1.0 / ratio
    for i in range(n):
        rect = abs(band[i])
        # attack when level rising, release when falling -> classic A/R follower
        coef = atk_c if rect > env else rel_c
        env = coef * env + (1.0 - coef) * rect
        env_db = 20.0 * np.log10(env + 1e-12)
        if mode_cut:
            over = env_db - thr_db
            g_db = -slope * over if over > 0.0 else 0.0      # cut when ABOVE thr
        else:
            under = thr_db - env_db
            g_db = slope * under if under > 0.0 else 0.0      # boost when BELOW thr
        if g_db < -range_db:
            g_db = -range_db
        elif g_db > range_db:
            g_db = range_db
        k[i] = 10.0 ** (g_db / 20.0) - 1.0
    return k


@njit(cache=True)
def _biquad(b, a, x):
    """Direct-form-II transposed biquad."""
    n = x.shape[0]
    y = np.empty(n, dtype=np.float64)
    z1 = 0.0
    z2 = 0.0
    b0, b1, b2 = b[0], b[1], b[2]
    a1, a2 = a[1], a[2]
    for i in range(n):
        xi = x[i]
        yi = b0 * xi + z1
        z1 = b1 * xi - a1 * yi + z2
        z2 = b2 * xi - a2 * yi
        y[i] = yi
    return y


def parse_band(spec):
    p = spec.split(":")
    if len(p) < 4:
        sys.exit(f"band '{spec}' needs at least FREQ:Q:THRESH:RATIO")
    f0 = float(p[0]); Q = float(p[1]); thr = float(p[2]); ratio = float(p[3])
    mode = (p[4].lower() if len(p) > 4 and p[4] else "cut")
    if mode not in ("cut", "boost"):
        sys.exit(f"band mode must be cut|boost, got '{mode}'")
    if ratio < 1.0:
        sys.exit("ratio must be >= 1")
    return f0, Q, thr, ratio, mode


def coef(ms, fs):
    if ms <= 0:
        return 0.0
    return float(np.exp(-1.0 / (fs * ms / 1000.0)))


def main():
    ap = argparse.ArgumentParser(description="dyneq — dynamic EQ (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--band", action="append", default=[],
                    help="FREQ:Q:THRESH_DB:RATIO[:cut|boost] (repeatable)")
    ap.add_argument("--attack-ms", type=float, default=5.0)
    ap.add_argument("--release-ms", type=float, default=80.0)
    ap.add_argument("--range-db", type=float, default=12.0, help="max |gain| per band")
    ap.add_argument("--makeup-db", type=float, default=0.0)
    a = ap.parse_args()
    if not a.band:
        sys.exit("give at least one --band")

    x, sr = sf.read(a.input, always_2d=True)
    atk_c, rel_c = coef(a.attack_ms, sr), coef(a.release_ms, sr)
    y = x.astype(np.float64).copy()

    for spec in a.band:
        f0, Q, thr, ratio, mode = parse_band(spec)
        b, av = bpf_0db(f0, Q, sr)
        applied = []
        for c in range(x.shape[1]):
            band = _biquad(b, av, x[:, c].astype(np.float64))
            k = _dynamic_gain(band, thr, ratio, mode == "cut", atk_c, rel_c, a.range_db)
            y[:, c] += k * band
            g_db = 20.0 * np.log10(np.abs(k + 1.0) + 1e-12)
            applied.append((g_db.min(), g_db.max()))
        lo = min(p[0] for p in applied); hi = max(p[1] for p in applied)
        print(f"  band {mode} @ {f0:.0f}Hz Q{Q}: applied {lo:+.1f}..{hi:+.1f} dB "
              f"(thr {thr:+.0f}, ratio {ratio:g}:1)")

    if a.makeup_db:
        y *= 10.0 ** (a.makeup_db / 20.0)
    peak = np.max(np.abs(y))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")

    sf.write(a.output, y[:, 0] if y.shape[1] == 1 else y, sr)
    print(f"dyneq: {len(a.band)} band(s) -> {a.output}")


if __name__ == "__main__":
    main()
