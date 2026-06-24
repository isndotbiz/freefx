#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy"]
# ///
"""
vocoder — open-source channel vocoder (robot / talkbox vocals).

Splits the modulator (your voice) into N frequency bands, follows the energy
envelope of each, and imposes those envelopes on the same bands of a carrier (a
synth, or a built-in saw/noise) — the carrier "talks". The 80s/electro robot
vocal. Clean-room analysis/synthesis filterbank. MIT. Part of `freefx`.

Usage:
  uv run vocoder.py vox.wav out.wav --carrier saw --bands 24
  uv run vocoder.py vox.wav out.wav --carrier synth.wav --bands 32 --mix 1.0
"""
import argparse
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, lfilter


def make_carrier(kind, n, sr):
    t = np.arange(n) / sr
    if kind == "noise":
        rng = np.random.default_rng(0)
        return rng.standard_normal(n) * 0.3
    # buzzy saw stack (rich harmonics for the vocoder to carve)
    f0 = 110.0
    sig = np.zeros(n)
    for h in range(1, 40):
        sig += (1.0 / h) * np.sin(2 * np.pi * f0 * h * t)
    return 0.3 * sig / np.max(np.abs(sig) + 1e-9)


def main():
    ap = argparse.ArgumentParser(description="vocoder — channel vocoder (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--carrier", default="saw", help="'saw' | 'noise' | path to a wav")
    ap.add_argument("--bands", type=int, default=24)
    ap.add_argument("--env-ms", type=float, default=15.0, help="envelope follower smoothing")
    ap.add_argument("--mix", type=float, default=1.0)
    a = ap.parse_args()

    mod, sr = sf.read(a.input)
    mod = mod.mean(axis=1) if mod.ndim > 1 else mod
    mod = mod.astype(np.float64)
    n = len(mod)
    if a.carrier in ("saw", "noise"):
        car = make_carrier(a.carrier, n, sr)
    else:
        c, _ = sf.read(a.carrier); c = c.mean(axis=1) if c.ndim > 1 else c
        car = np.resize(c.astype(np.float64), n)

    edges = np.logspace(np.log10(120), np.log10(min(8000, sr / 2 - 200)), a.bands + 1)
    env_c = np.exp(-1.0 / (sr * a.env_ms / 1000.0))
    out = np.zeros(n)
    for b in range(a.bands):
        sos = butter(2, [edges[b] / (sr / 2), edges[b + 1] / (sr / 2)], btype="band", output="sos")
        mb = sosfilt(sos, mod); cb = sosfilt(sos, car)
        env = np.abs(mb)
        env = lfilter([1 - env_c], [1, -env_c], env)      # one-pole smooth the band envelope
        out += cb * env
    out *= 3.0                                             # filterbank loses level; restore
    y = (1 - a.mix) * np.resize(mod, n) + a.mix * out

    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y, sr)
    print(f"vocoder: carrier={a.carrier} bands={a.bands} mix {a.mix:g} -> {a.output}")


if __name__ == "__main__":
    main()
