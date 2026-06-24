#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy", "numba"]
# ///
"""
duck — open-source sidechain ducking / pump.

Turns a track down whenever a trigger is loud: classic sidechain "pump" of pads
or a reverb tail to the kick, or ducking music under a vocal. Provide a key file
(the trigger, e.g. the kick) with --key, or omit it to self-key on the input's
own low end (pumps on its own kicks). Clean-room envelope DSP. MIT. Part of
`freefx`.

Usage:
  uv run duck.py pads.wav out.wav --key kick.wav --amount 9 --release-ms 180   # pump pads to kick
  uv run duck.py mix.wav out.wav --amount 6                                     # self-key on low end
  uv run duck.py verbtail.wav out.wav --key vocal.wav --amount 12               # duck reverb under vox
"""
import argparse
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt
from numba import njit


@njit(cache=True)
def _duck(key, thr_db, depth, atk_c, rel_c):
    n = key.shape[0]
    g = np.empty(n, dtype=np.float64)
    env = 1e-9; cur = 1.0
    for i in range(n):
        rect = abs(key[i])
        env = (atk_c if rect > env else rel_c) * env + (1.0 - (atk_c if rect > env else rel_c)) * rect
        over = 20.0 * np.log10(env + 1e-12) - thr_db
        target = 10.0 ** (-(depth if over > 0.0 else 0.0) / 20.0)   # full duck when key over threshold
        cur = (atk_c if target < cur else rel_c) * cur + (1.0 - (atk_c if target < cur else rel_c)) * target
        g[i] = cur
    return g


def coef(ms, fs):
    return float(np.exp(-1.0 / (fs * ms / 1000.0))) if ms > 0 else 0.0


def main():
    ap = argparse.ArgumentParser(description="duck — sidechain ducking / pump (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--key", default=None, help="trigger file (omit = self-key on input low end)")
    ap.add_argument("--threshold", type=float, default=-30.0)
    ap.add_argument("--amount", type=float, default=9.0, help="max duck depth in dB")
    ap.add_argument("--attack-ms", type=float, default=2.0)
    ap.add_argument("--release-ms", type=float, default=180.0)
    ap.add_argument("--key-hpf", type=float, default=0.0, help="only trigger above this Hz")
    a = ap.parse_args()

    x, sr = sf.read(a.input, always_2d=True)
    if a.key:
        k, ksr = sf.read(a.key, always_2d=True)
        key = np.max(np.abs(k.astype(np.float64)), axis=1)
        if len(key) < len(x):
            key = np.pad(key, (0, len(x) - len(key)))
        key = key[: len(x)]
    else:
        lo = sosfilt(butter(2, 120 / (sr / 2), btype="low", output="sos"), np.max(np.abs(x), axis=1))
        key = np.abs(lo)
    if a.key_hpf > 0:
        key = np.abs(sosfilt(butter(2, a.key_hpf / (sr / 2), btype="high", output="sos"), key))

    g = _duck(np.ascontiguousarray(key), a.threshold, a.amount, coef(a.attack_ms, sr), coef(a.release_ms, sr))
    y = x.astype(np.float64) * g[:, None]
    sf.write(a.output, y[:, 0] if y.shape[1] == 1 else y, sr)
    gdb = 20.0 * np.log10(g + 1e-12)
    print(f"duck: key={'self-low' if not a.key else a.key} thr {a.threshold:+g} amount {a.amount:g}dB | "
          f"gain {gdb.min():.1f}..{gdb.max():.1f} dB -> {a.output}")


if __name__ == "__main__":
    main()
