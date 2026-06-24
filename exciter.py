#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy"]
# ///
"""
exciter — open-source HF harmonic exciter (air / "crisp" / sparkle).

Adds presence the way an aural exciter does: split off the highs, generate new
harmonics up there by gently saturating that band, and blend them back in. Unlike
a high-shelf (which only boosts what's already there) this synthesises NEW upper
harmonics, so it reads as "air" without sounding like an EQ boost. Oversampled so
the new content doesn't alias. Clean-room textbook DSP. MIT. Part of `freefx`.

Usage:
  uv run exciter.py vox.wav out.wav --freq 5000 --amount 3      # vocal air
  uv run exciter.py mix.wav out.wav --freq 8000 --amount 2 --drive 8
"""
import argparse
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, resample_poly


def main():
    ap = argparse.ArgumentParser(description="exciter — HF harmonic exciter (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--freq", type=float, default=5000.0, help="split frequency (excite above this)")
    ap.add_argument("--drive", type=float, default=6.0, help="dB into the HF saturator")
    ap.add_argument("--amount", type=float, default=3.0, help="dB of excited HF blended back in")
    ap.add_argument("--oversample", type=int, default=4)
    a = ap.parse_args()

    x, sr = sf.read(a.input)
    xd = x.astype(np.float64)
    sos = butter(2, min(a.freq, sr / 2 - 1) / (sr / 2), btype="high", output="sos")
    hf = sosfilt(sos, xd, axis=0)

    g = 10 ** (a.drive / 20.0)
    hfo = resample_poly(hf, a.oversample, 1, axis=0)
    exc = np.tanh(g * hfo) / max(np.tanh(g), 1e-9)
    exc = resample_poly(exc, 1, a.oversample, axis=0)
    exc = sosfilt(sos, exc[: len(xd)], axis=0)            # keep only the new highs
    y = xd + (10 ** (a.amount / 20.0) - 1.0) * exc * (np.sqrt(np.mean(hf**2)) /
            (np.sqrt(np.mean(exc**2)) + 1e-12))           # level-match the excited band

    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y, sr)
    # self-check: HF energy ratio change
    def hfe(s): return np.sqrt(np.mean(sosfilt(sos, s, axis=0) ** 2) + 1e-12)
    print(f"exciter: >{a.freq:g}Hz drive {a.drive:g} amount {a.amount:+g}dB | "
          f"HF energy {20*np.log10(hfe(xd)):.1f}->{20*np.log10(hfe(y)):.1f} dB -> {a.output}")


if __name__ == "__main__":
    main()
