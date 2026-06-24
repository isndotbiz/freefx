#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "numba"]
# ///
"""
flanger — open-source flanger (jet-sweep comb modulation).

A very short (0-5 ms) LFO-swept delay mixed with the dry signal creates a moving
comb filter — the classic "jet plane" whoosh. Feedback sharpens the resonant
sweep. Clean-room modulated-delay + feedback DSP. MIT. Part of `freefx`.

Usage:
  uv run flanger.py gtr.wav out.wav --rate 0.3 --depth 3 --feedback 0.6
  uv run flanger.py synth.wav out.wav --rate 0.8 --depth 2 --mix 0.5
"""
import argparse
import numpy as np
import soundfile as sf
from numba import njit


@njit(cache=True)
def _flange(x, base, depth, rate, sr, fb, mix):
    n = x.shape[0]
    y = np.empty(n, dtype=np.float64)
    buf = np.zeros(n, dtype=np.float64)
    twopi_r = 2.0 * np.pi * rate / sr
    for i in range(n):
        d = (base + depth * 0.5 * (1.0 + np.sin(twopi_r * i))) * sr / 1000.0
        di = int(d); frac = d - di
        j0 = i - di; j1 = j0 - 1
        s = 0.0
        if j0 >= 0:
            a = buf[j0]
            b = buf[j1] if j1 >= 0 else 0.0
            s = a * (1.0 - frac) + b * frac               # fractional delay read
        buf[i] = x[i] + fb * s
        y[i] = (1.0 - mix) * x[i] + mix * s
    return y


def main():
    ap = argparse.ArgumentParser(description="flanger — jet-sweep flanger (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--rate", type=float, default=0.3, help="LFO rate Hz")
    ap.add_argument("--depth", type=float, default=3.0, help="sweep depth ms")
    ap.add_argument("--base-ms", type=float, default=1.0, help="minimum delay ms")
    ap.add_argument("--feedback", type=float, default=0.5, help="-0.95..0.95")
    ap.add_argument("--mix", type=float, default=0.5)
    a = ap.parse_args()

    x, sr = sf.read(a.input)
    fb = min(max(a.feedback, -0.95), 0.95)
    if x.ndim == 1:
        y = _flange(np.ascontiguousarray(x.astype(np.float64)), a.base_ms, a.depth, a.rate, sr, fb, a.mix)
    else:
        y = np.stack([_flange(np.ascontiguousarray(x[:, c].astype(np.float64)),
                              a.base_ms, a.depth, a.rate, sr, fb, a.mix) for c in range(x.shape[1])], axis=1)
    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y, sr)
    print(f"flanger: rate {a.rate:g}Hz depth {a.depth:g}ms fb {fb:g} mix {a.mix:g} -> {a.output}")


if __name__ == "__main__":
    main()
