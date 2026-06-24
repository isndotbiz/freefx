#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "numba"]
# ///
"""
phaser — open-source phaser (swept all-pass notches).

A cascade of all-pass filters whose break frequency is swept by an LFO creates
moving notches in the spectrum — the swirly, watery phaser sweep (lush on 80s
synth pads). Feedback deepens the notches. Clean-room all-pass DSP. MIT. Part of
`freefx`.

Usage:
  uv run phaser.py pad.wav out.wav --stages 6 --rate 0.4 --feedback 0.5
  uv run phaser.py vox.wav out.wav --stages 4 --rate 1.0 --mix 0.4
"""
import argparse
import numpy as np
import soundfile as sf
from numba import njit


@njit(cache=True)
def _phase(x, stages, fmin, fmax, rate, sr, fb, mix):
    n = x.shape[0]
    y = np.empty(n, dtype=np.float64)
    zs = np.zeros(stages, dtype=np.float64)               # one-pole all-pass states
    last = 0.0
    twopi_r = 2.0 * np.pi * rate / sr
    lf = np.log(fmin); hf = np.log(fmax)
    for i in range(n):
        f = np.exp(lf + (hf - lf) * 0.5 * (1.0 + np.sin(twopi_r * i)))   # log-swept break freq
        tn = np.tan(np.pi * f / sr)
        a1 = (tn - 1.0) / (tn + 1.0)                       # 1st-order all-pass coef
        s = x[i] + fb * last
        for k in range(stages):
            ap = a1 * s + zs[k]
            zs[k] = s - a1 * ap
            s = ap
        last = s
        y[i] = (1.0 - mix) * x[i] + mix * s
    return y


def main():
    ap = argparse.ArgumentParser(description="phaser — swept all-pass phaser (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--stages", type=int, default=6, help="all-pass stages (more = more notches)")
    ap.add_argument("--rate", type=float, default=0.4, help="LFO rate Hz")
    ap.add_argument("--fmin", type=float, default=300.0)
    ap.add_argument("--fmax", type=float, default=2000.0)
    ap.add_argument("--feedback", type=float, default=0.5, help="-0.95..0.95")
    ap.add_argument("--mix", type=float, default=0.5)
    a = ap.parse_args()

    x, sr = sf.read(a.input)
    fb = min(max(a.feedback, -0.95), 0.95)
    if x.ndim == 1:
        y = _phase(np.ascontiguousarray(x.astype(np.float64)), a.stages, a.fmin, a.fmax, a.rate, sr, fb, a.mix)
    else:
        y = np.stack([_phase(np.ascontiguousarray(x[:, c].astype(np.float64)),
                              a.stages, a.fmin, a.fmax, a.rate, sr, fb, a.mix) for c in range(x.shape[1])], axis=1)
    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y, sr)
    print(f"phaser: {a.stages} stages rate {a.rate:g}Hz fb {fb:g} mix {a.mix:g} -> {a.output}")


if __name__ == "__main__":
    main()
