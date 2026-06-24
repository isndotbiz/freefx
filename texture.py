#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy"]
# ///
"""
texture — open-source lo-fi texture (vinyl crackle + tape hiss + wow).

Layers the nostalgic noise floor over a track: random vinyl crackle/pops, steady
tape hiss, and a slow wow pitch drift. The bedroom / sad-boy lo-fi patina.
Clean-room (filtered noise + sparse impulses + modulated delay). MIT. Part of
`freefx`.

Usage:
  uv run texture.py beat.wav out.wav --crackle 0.4 --hiss 0.2
  uv run texture.py vox.wav out.wav --crackle 0.3 --hiss 0.15 --wow 8 --seed 7
"""
import argparse
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt


def main():
    ap = argparse.ArgumentParser(description="texture — vinyl/hiss lo-fi texture (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--crackle", type=float, default=0.4, help="vinyl crackle amount 0..1")
    ap.add_argument("--hiss", type=float, default=0.2, help="tape hiss amount 0..1")
    ap.add_argument("--wow", type=float, default=0.0, help="slow pitch drift, cents (0=off)")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    x, sr = sf.read(a.input, always_2d=True)
    xd = x.astype(np.float64)
    n = xd.shape[0]
    rng = np.random.default_rng(a.seed)

    if a.wow > 0:                                          # slow wow pitch drift
        t = np.arange(n) / sr
        md = (2 ** (a.wow / 1200.0) - 1) * 0.02 * sr * (0.5 + 0.5 * np.sin(2 * np.pi * 0.7 * t))
        idx = np.clip(np.arange(n) - md, 0, n - 1)
        xd = np.stack([np.interp(idx, np.arange(n), xd[:, c]) for c in range(xd.shape[1])], axis=1)

    # vinyl crackle: sparse random impulses, band-limited
    crk = np.zeros(n)
    npops = int(n / sr * 80 * a.crackle)                  # ~80 pops/sec at full
    if npops > 0:
        pos = rng.integers(0, n, npops)
        crk[pos] = rng.standard_normal(npops) * rng.random(npops)
        crk = sosfilt(butter(2, [800 / (sr / 2), 6000 / (sr / 2)], btype="band", output="sos"), crk)
    hiss = sosfilt(butter(2, 2000 / (sr / 2), btype="high", output="sos"),
                   rng.standard_normal(n)) * 0.02 * a.hiss
    noise = (0.15 * a.crackle * crk + hiss)[:, None]
    y = xd + noise

    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
    sf.write(a.output, y[:, 0] if y.shape[1] == 1 else y, sr)
    nl = 20 * np.log10(np.sqrt(np.mean(noise ** 2)) + 1e-12)
    print(f"texture: crackle {a.crackle:g} hiss {a.hiss:g} wow {a.wow:g}c | "
          f"noise floor {nl:.1f} dBFS -> {a.output}")


if __name__ == "__main__":
    main()
