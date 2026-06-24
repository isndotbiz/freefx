#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2"]
# ///
"""
chorus — open-source chorus (the 80s synth-pad signature).

Several LFO-modulated short delay lines, panned, summed under the dry signal:
the lush, shimmering "many detuned copies" sound that defines 80s Juno/Oberheim
pads (the chorus circuit IS the signature). Clean-room modulated-delay DSP. MIT.
Part of `freefx`.

Usage:
  uv run chorus.py pad.wav out.wav --voices 3 --rate 0.6 --depth 4 --mix 0.5
  uv run chorus.py vox.wav out.wav --voices 2 --rate 1.2 --depth 2 --mix 0.3
"""
import argparse
import numpy as np
import soundfile as sf


def voice(mono, sr, base_ms, depth_ms, rate_hz, phase):
    n = len(mono); t = np.arange(n) / sr
    delay = (base_ms + depth_ms * (0.5 + 0.5 * np.sin(2 * np.pi * rate_hz * t + phase))) * sr / 1000.0
    idx = np.clip(np.arange(n) - delay, 0, n - 1)
    return np.interp(idx, np.arange(n), mono)


def main():
    ap = argparse.ArgumentParser(description="chorus — modulated-delay chorus (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--voices", type=int, default=3)
    ap.add_argument("--rate", type=float, default=0.6, help="LFO rate Hz")
    ap.add_argument("--depth", type=float, default=4.0, help="modulation depth ms")
    ap.add_argument("--base-ms", type=float, default=18.0, help="base delay ms")
    ap.add_argument("--mix", type=float, default=0.5, help="0=dry .. 1=wet only")
    a = ap.parse_args()

    x, sr = sf.read(a.input)
    mono = x.mean(axis=1) if x.ndim > 1 else x
    L = mono.copy(); R = mono.copy()
    for v in range(a.voices):
        ph = 2 * np.pi * v / a.voices
        w = voice(mono, sr, a.base_ms, a.depth, a.rate * (1 + 0.1 * v), ph)
        pan = -1 + 2 * v / max(a.voices - 1, 1)           # spread voices across the field
        gl = np.sqrt(0.5 * (1 - pan)); gr = np.sqrt(0.5 * (1 + pan))
        L += a.mix * gl * w; R += a.mix * gr * w
    y = np.stack([L, R], axis=1)

    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y, sr)
    s = (y[:, 0] - y[:, 1]) * 0.5; m = (y[:, 0] + y[:, 1]) * 0.5
    print(f"chorus: {a.voices} voices rate {a.rate:g}Hz depth {a.depth:g}ms mix {a.mix:g} | "
          f"side/mid {20*np.log10((np.sqrt(np.mean(s**2))+1e-12)/(np.sqrt(np.mean(m**2))+1e-12)):+.1f}dB -> {a.output}")


if __name__ == "__main__":
    main()
