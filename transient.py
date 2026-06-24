#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "numba"]
# ///
"""
transient — open-source transient shaper (attack/sustain designer).

Adds or softens the PUNCH of a sound independent of its level — snap an 808 or
snare's attack, or fatten its sustain/tail. Works by comparing a fast envelope
follower (tracks onsets) against a slow one (tracks the body): when fast > slow
you're in an attack, when slow > fast you're in the decay. Level-independent, so
it shapes punch without acting like a compressor. Clean-room dual-envelope DSP
(the SPL Transient Designer principle, built from scratch). MIT. Part of `freefx`.

Usage:
  uv run transient.py drums.wav out.wav --attack 6                 # snappier
  uv run transient.py 808.wav out.wav --attack 4 --sustain -3      # punchier, tighter tail
  uv run transient.py loop.wav out.wav --attack -4                 # soften/round the hits
"""
import argparse
import numpy as np
import soundfile as sf
from numba import njit


@njit(cache=True)
def _shape(x, fast_a, fast_r, slow_a, slow_r, atk_amt, sus_amt, max_db):
    n = x.shape[0]
    g = np.empty(n, dtype=np.float64)
    ef = 1e-9
    es = 1e-9
    for i in range(n):
        rect = abs(x[i])
        ef = (fast_a if rect > ef else fast_r) * ef + (1.0 - (fast_a if rect > ef else fast_r)) * rect
        es = (slow_a if rect > es else slow_r) * es + (1.0 - (slow_a if rect > es else slow_r)) * rect
        diff_db = 20.0 * np.log10((ef + 1e-9) / (es + 1e-9))    # >0 attack, <0 sustain
        if diff_db >= 0.0:
            gain_db = atk_amt * diff_db
        else:
            gain_db = -sus_amt * diff_db                         # diff_db<0 -> sustain region
        if gain_db > max_db:
            gain_db = max_db
        elif gain_db < -max_db:
            gain_db = -max_db
        g[i] = 10.0 ** (gain_db / 20.0)
    return g


def coef(ms, fs):
    return float(np.exp(-1.0 / (fs * ms / 1000.0))) if ms > 0 else 0.0


def main():
    ap = argparse.ArgumentParser(description="transient — attack/sustain shaper (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--attack", type=float, default=0.0, help="transient emphasis (dB, + snappier / - softer)")
    ap.add_argument("--sustain", type=float, default=0.0, help="sustain/tail emphasis (dB, + fatter / - tighter)")
    ap.add_argument("--max-db", type=float, default=12.0, help="gain clamp")
    a = ap.parse_args()

    x, sr = sf.read(a.input, always_2d=True)
    fa, fr = coef(0.5, sr), coef(40.0, sr)               # fast follower: snappy attack
    sa, sr_ = coef(18.0, sr), coef(120.0, sr)            # slow follower: tracks the body
    det = np.max(np.abs(x.astype(np.float64)), axis=1)   # stereo-linked detection
    g = _shape(np.ascontiguousarray(det), fa, fr, sa, sr_, a.attack, a.sustain, a.max_db)
    y = x.astype(np.float64) * g[:, None]

    g_db = 20.0 * np.log10(g + 1e-12)
    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y[:, 0] if y.shape[1] == 1 else y, sr)
    print(f"transient: attack {a.attack:+g} sustain {a.sustain:+g} dB | "
          f"gain {g_db.min():.1f}..{g_db.max():.1f} dB -> {a.output}")


if __name__ == "__main__":
    main()
