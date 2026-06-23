#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy"]
# ///
"""
eq — open-source parametric EQ (biquad cascade, RBJ cookbook).

Add any number of bands; each is a standard second-order section. Types:
  peak | lowshelf | highshelf | hpf | lpf

Clean-room, textbook DSP (Robert Bristow-Johnson's Audio EQ Cookbook). MIT.
Part of the `freefx` open-source effects suite.

Usage:
  uv run eq.py in.wav out.wav --band peak:300:-3:0.9 --band highshelf:10000:2:0.7
  uv run eq.py in.wav out.wav --band hpf:30::0.707 --band peak:2500:4:1.2
Band format: TYPE:FREQ_HZ:GAIN_DB:Q   (GAIN_DB ignored/blank for hpf/lpf)
"""
import argparse, sys
import numpy as np
import soundfile as sf
from scipy.signal import sosfilt, sosfreqz

def biquad(kind, f0, gain_db, Q, fs):
    w0 = 2 * np.pi * f0 / fs
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2 * Q)
    A = 10 ** (gain_db / 40.0)
    if kind == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind == "hpf":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]; a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "lpf":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2];   a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind in ("lowshelf", "highshelf"):
        s = 1 if kind == "lowshelf" else -1
        sa = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) - s * (A - 1) * cw + sa),
             2 * A * ((A - 1) - s * (A + 1) * cw),
             A * ((A + 1) - s * (A - 1) * cw - sa)]
        a = [(A + 1) + s * (A - 1) * cw + sa,
             -2 * ((A - 1) + s * (A + 1) * cw),
             (A + 1) + s * (A - 1) * cw - sa]
        if kind == "highshelf":
            b = [A * ((A + 1) + (A - 1) * cw + sa),
                 -2 * A * ((A - 1) + (A + 1) * cw),
                 A * ((A + 1) + (A - 1) * cw - sa)]
            a = [(A + 1) - (A - 1) * cw + sa,
                 2 * ((A - 1) - (A + 1) * cw),
                 (A + 1) - (A - 1) * cw - sa]
    else:
        sys.exit(f"unknown band type '{kind}'")
    a0 = a[0]
    return [b[0]/a0, b[1]/a0, b[2]/a0, 1.0, a[1]/a0, a[2]/a0]  # one SOS row

def parse_band(spec):
    parts = spec.split(":")
    kind = parts[0]
    f0 = float(parts[1])
    gain = float(parts[2]) if len(parts) > 2 and parts[2] != "" else 0.0
    Q = float(parts[3]) if len(parts) > 3 and parts[3] != "" else 0.707
    return kind, f0, gain, Q

def main():
    ap = argparse.ArgumentParser(description="eq — parametric EQ (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--band", action="append", default=[], help="TYPE:FREQ:GAIN_DB:Q (repeatable)")
    a = ap.parse_args()
    if not a.band: sys.exit("give at least one --band")
    x, sr = sf.read(a.input)
    sos = []
    for spec in a.band:
        kind, f0, gain, Q = parse_band(spec)
        sos.append(biquad(kind, f0, gain, Q, sr))
        # report actual gain at the band center as a self-check
        w, h = sosfreqz([biquad(kind, f0, gain, Q, sr)], worN=[2 * np.pi * f0 / sr])
        print(f"  band {kind} @ {f0:.0f}Hz: {20*np.log10(abs(h[0])+1e-12):+.1f} dB (Q={Q})")
    sos = np.array(sos)
    if x.ndim == 1:
        y = sosfilt(sos, x)
    else:
        y = np.stack([sosfilt(sos, x[:, c]) for c in range(x.shape[1])], axis=1)
    peak = np.max(np.abs(y))
    if peak > 0.999:  # avoid clipping from boosts
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y, sr)
    print(f"eq: {len(a.band)} band(s) -> {a.output}")

if __name__ == "__main__":
    main()
