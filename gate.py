#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "numba"]
# ///
"""
gate — open-source noise gate / downward expander.

Below the threshold, attenuate (a hard gate at high range, a gentle expander at
low range); above it, pass through. Attack opens fast, hold keeps it open through
short dips, release closes smoothly. Cleans breaths/noise between vocal phrases,
or — with a fast release — chops a reverb tail for the gated-snare sound. Clean-
room envelope DSP. MIT. Part of `freefx`.

Usage:
  uv run gate.py vox.wav out.wav --threshold -45 --range 40           # vocal cleanup
  uv run gate.py snare.wav out.wav --threshold -20 --range 60 --release-ms 80   # gated reverb
"""
import argparse
import numpy as np
import soundfile as sf
from numba import njit


@njit(cache=True)
def _gate(det, thr_db, range_db, ratio, atk_c, rel_c, hold_n):
    n = det.shape[0]
    g = np.empty(n, dtype=np.float64)
    env = 1e-9
    held = 0
    cur = 10.0 ** (-range_db / 20.0)
    floor = 10.0 ** (-range_db / 20.0)
    for i in range(n):
        rect = abs(det[i])
        env = (atk_c if rect > env else rel_c) * env + (1.0 - (atk_c if rect > env else rel_c)) * rect
        env_db = 20.0 * np.log10(env + 1e-12)
        if env_db >= thr_db:
            target = 1.0
            held = hold_n
        elif held > 0:
            target = 1.0
            held -= 1
        else:
            # downward expander below threshold: gain reduction grows with how far under
            under = thr_db - env_db
            gr_db = -min(range_db, under * (ratio - 1.0))
            target = max(floor, 10.0 ** (gr_db / 20.0))
        cur = (atk_c if target > cur else rel_c) * cur + (1.0 - (atk_c if target > cur else rel_c)) * target
        g[i] = cur
    return g


def coef(ms, fs):
    return float(np.exp(-1.0 / (fs * ms / 1000.0))) if ms > 0 else 0.0


def main():
    ap = argparse.ArgumentParser(description="gate — noise gate / expander (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--threshold", type=float, default=-45.0, help="dBFS gate opens above this")
    ap.add_argument("--range", type=float, default=40.0, help="max attenuation below threshold (dB)")
    ap.add_argument("--ratio", type=float, default=4.0, help="expander ratio below threshold")
    ap.add_argument("--attack-ms", type=float, default=1.0)
    ap.add_argument("--hold-ms", type=float, default=30.0)
    ap.add_argument("--release-ms", type=float, default=120.0)
    a = ap.parse_args()

    x, sr = sf.read(a.input, always_2d=True)
    det = np.max(np.abs(x.astype(np.float64)), axis=1)
    g = _gate(np.ascontiguousarray(det), a.threshold, a.range, a.ratio,
              coef(a.attack_ms, sr), coef(a.release_ms, sr), int(sr * a.hold_ms / 1000.0))
    y = x.astype(np.float64) * g[:, None]
    sf.write(a.output, y[:, 0] if y.shape[1] == 1 else y, sr)
    gdb = 20.0 * np.log10(g + 1e-12)
    print(f"gate: thr {a.threshold:+g} range {a.range:g} ratio {a.ratio:g}:1 | "
          f"gain {gdb.min():.1f}..{gdb.max():.1f} dB | {np.mean(g<0.5)*100:.0f}% gated -> {a.output}")


if __name__ == "__main__":
    main()
