#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2"]
# ///
"""
tremolo — open-source tremolo / auto-pan (amplitude LFO).

Modulates level with an LFO (tremolo), or pans the LFO across the stereo field
(auto-pan) for movement. Sine or square shape. Clean-room. MIT. Part of `freefx`.

Usage:
  uv run tremolo.py gtr.wav out.wav --rate 5 --depth 0.6              # classic tremolo
  uv run tremolo.py pad.wav out.wav --rate 0.5 --depth 0.8 --pan      # slow auto-pan
  uv run tremolo.py synth.wav out.wav --rate 8 --shape square         # choppy gate-trem
"""
import argparse
import numpy as np
import soundfile as sf


def main():
    ap = argparse.ArgumentParser(description="tremolo — tremolo / auto-pan (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--rate", type=float, default=5.0, help="LFO rate Hz")
    ap.add_argument("--depth", type=float, default=0.6, help="0..1")
    ap.add_argument("--shape", choices=["sine", "square"], default="sine")
    ap.add_argument("--pan", action="store_true", help="auto-pan instead of tremolo")
    a = ap.parse_args()

    x, sr = sf.read(a.input, always_2d=True)
    n = x.shape[0]; t = np.arange(n) / sr
    lfo = np.sin(2 * np.pi * a.rate * t)
    if a.shape == "square":
        lfo = np.sign(lfo)
    if a.pan:
        if x.shape[1] == 1:
            x = np.repeat(x, 2, axis=1)
        pan = a.depth * lfo                               # -depth..+depth
        gl = np.sqrt(0.5 * (1 - pan)); gr = np.sqrt(0.5 * (1 + pan))
        y = np.stack([x[:, 0] * gl, x[:, 1] * gr], axis=1)
    else:
        g = 1.0 - a.depth * 0.5 * (1.0 + lfo)             # amplitude mod, depth=1 -> dips to 0
        y = x * g[:, None]

    sf.write(a.output, y[:, 0] if y.shape[1] == 1 else y, sr)
    print(f"tremolo: rate {a.rate:g}Hz depth {a.depth:g} {a.shape}{' auto-pan' if a.pan else ''} -> {a.output}")


if __name__ == "__main__":
    main()
