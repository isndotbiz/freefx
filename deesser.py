#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy", "numba"]
# ///
"""
deesser — open-source de-esser (tame sibilance).

Detects energy in the sibilance band (~5-9 kHz) and, when it spikes over the
threshold, ducks just that band — so "sss"/"shh" stop spitting without dulling
the whole vocal. Split mode (process only the band) keeps the rest untouched.
`--listen` outputs just the detection band so you can dial the frequency in.
Clean-room. MIT. Part of `freefx`.

Usage:
  uv run deesser.py vox.wav out.wav --freq 6500 --threshold -30 --range 8
  uv run deesser.py vox.wav out.wav --freq 7000 --listen          # hear what it's keying on
"""
import argparse
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt
from numba import njit


@njit(cache=True)
def _gain(band, thr_db, ratio, range_db, atk_c, rel_c):
    n = band.shape[0]
    g = np.empty(n, dtype=np.float64)
    env = 1e-9
    slope = 1.0 - 1.0 / ratio
    for i in range(n):
        rect = abs(band[i])
        env = (atk_c if rect > env else rel_c) * env + (1.0 - (atk_c if rect > env else rel_c)) * rect
        over = 20.0 * np.log10(env + 1e-12) - thr_db
        gr = -min(range_db, slope * over) if over > 0.0 else 0.0
        g[i] = 10.0 ** (gr / 20.0)
    return g


def coef(ms, fs):
    return float(np.exp(-1.0 / (fs * ms / 1000.0))) if ms > 0 else 0.0


def main():
    ap = argparse.ArgumentParser(description="deesser — de-esser (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--freq", type=float, default=6500.0, help="sibilance band center")
    ap.add_argument("--threshold", type=float, default=-30.0)
    ap.add_argument("--ratio", type=float, default=4.0)
    ap.add_argument("--range", type=float, default=8.0, help="max reduction dB")
    ap.add_argument("--attack-ms", type=float, default=0.5)
    ap.add_argument("--release-ms", type=float, default=40.0)
    ap.add_argument("--listen", action="store_true", help="output the detection band only")
    a = ap.parse_args()

    x, sr = sf.read(a.input, always_2d=True)
    xd = x.astype(np.float64)
    lo = max(a.freq * 0.7, 1000); hi = min(a.freq * 1.5, sr / 2 - 1)
    sos = butter(2, [lo / (sr / 2), hi / (sr / 2)], btype="band", output="sos")
    band = sosfilt(sos, xd, axis=0)
    if a.listen:
        sf.write(a.output, band[:, 0] if band.shape[1] == 1 else band, sr)
        print(f"deesser --listen: band {lo:.0f}-{hi:.0f}Hz -> {a.output}")
        return

    det = np.max(np.abs(band), axis=1)
    g = _gain(np.ascontiguousarray(det), a.threshold, a.ratio, a.range,
              coef(a.attack_ms, sr), coef(a.release_ms, sr))
    y = xd - band + band * g[:, None]                     # reduce only the sibilance band (split de-ess)
    sf.write(a.output, y[:, 0] if y.shape[1] == 1 else y, sr)
    gdb = 20.0 * np.log10(g + 1e-12)
    print(f"deesser: {a.freq:g}Hz thr {a.threshold:+g} ratio {a.ratio:g}:1 | "
          f"reduction {gdb.min():.1f} dB max -> {a.output}")


if __name__ == "__main__":
    main()
