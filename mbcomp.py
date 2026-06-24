#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy", "numba"]
# ///
"""
mbcomp — open-source 3-band multiband compressor (master glue).

Splits into low / mid / high bands at two crossovers, compresses each
independently (soft-knee, attack/release), and sums. Tame a boomy low end
without dulling the highs, or glue a master band-by-band. Complementary split
(mid = full − low − high) so it reconstructs exactly when nothing is compressing.
Clean-room. MIT. Part of `freefx`.

Usage:
  uv run mbcomp.py master.wav out.wav --xover 200 2500 --threshold -20 --ratio 3
  uv run mbcomp.py mix.wav out.wav --xover 150 4000 --threshold -24 --ratio 2.5 --makeup 2
"""
import argparse
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt
from numba import njit


@njit(cache=True)
def _comp_gain(det, thr_db, ratio, knee_db, atk_c, rel_c):
    n = det.shape[0]
    g = np.empty(n, dtype=np.float64)
    env = 1e-9; cur = 1.0
    slope = 1.0 / ratio - 1.0
    hk = knee_db * 0.5
    for i in range(n):
        rect = abs(det[i])
        env = (atk_c if rect > env else rel_c) * env + (1.0 - (atk_c if rect > env else rel_c)) * rect
        over = 20.0 * np.log10(env + 1e-12) - thr_db
        if knee_db > 0.0 and -hk <= over <= hk:
            gr = slope * (over + hk) ** 2 / (2.0 * knee_db)
        elif over > 0.0:
            gr = slope * over
        else:
            gr = 0.0
        target = 10.0 ** (gr / 20.0)
        cur = (atk_c if target < cur else rel_c) * cur + (1.0 - (atk_c if target < cur else rel_c)) * target
        g[i] = cur
    return g


def coef(ms, fs):
    return float(np.exp(-1.0 / (fs * ms / 1000.0))) if ms > 0 else 0.0


def compress_band(band, sr, thr, ratio, knee, atk, rel):
    det = np.max(np.abs(band), axis=1) if band.ndim > 1 else np.abs(band)
    g = _comp_gain(np.ascontiguousarray(det), thr, ratio, knee, coef(atk, sr), coef(rel, sr))
    return band * (g[:, None] if band.ndim > 1 else g), 20 * np.log10(g.min() + 1e-12)


def main():
    ap = argparse.ArgumentParser(description="mbcomp — 3-band multiband compressor (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--xover", type=float, nargs=2, default=[200.0, 2500.0], help="low/mid and mid/high Hz")
    ap.add_argument("--threshold", type=float, default=-20.0)
    ap.add_argument("--ratio", type=float, default=3.0)
    ap.add_argument("--knee", type=float, default=6.0)
    ap.add_argument("--attack-ms", type=float, default=10.0)
    ap.add_argument("--release-ms", type=float, default=120.0)
    ap.add_argument("--makeup", type=float, default=0.0)
    a = ap.parse_args()

    x, sr = sf.read(a.input, always_2d=True)
    xd = x.astype(np.float64)
    f1, f2 = a.xover
    lo = sosfilt(butter(4, f1 / (sr / 2), btype="low", output="sos"), xd, axis=0)
    hi = sosfilt(butter(4, f2 / (sr / 2), btype="high", output="sos"), xd, axis=0)
    mid = xd - lo - hi                                    # complementary -> exact reconstruction
    grs = []
    out = np.zeros_like(xd)
    for band in (lo, mid, hi):
        b, gr = compress_band(band, sr, a.threshold, a.ratio, a.knee, a.attack_ms, a.release_ms)
        out += b; grs.append(gr)
    out *= 10 ** (a.makeup / 20.0)

    peak = float(np.max(np.abs(out)))
    if peak > 0.999:
        out = out / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, out[:, 0] if out.shape[1] == 1 else out, sr)
    print(f"mbcomp: xover {f1:g}/{f2:g}Hz thr {a.threshold:+g} ratio {a.ratio:g}:1 | "
          f"max GR low/mid/high {grs[0]:.1f}/{grs[1]:.1f}/{grs[2]:.1f} dB -> {a.output}")


if __name__ == "__main__":
    main()
