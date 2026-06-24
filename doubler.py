#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2"]
# ///
"""
doubler — open-source vocal doubler / ADT / stereo widener.

Fakes the sound of a singer tracking the same line twice: short delayed,
slightly detuned copies panned left and right around the dry centre. Widens and
thickens a mono vocal the modern way (automatic double tracking). Clean-room:
fractional-delay + tiny resample detune + panning. MIT. Part of `freefx`.

Usage:
  uv run doubler.py vox.wav out.wav                        # default 2-voice ADT
  uv run doubler.py vox.wav out.wav --voices 2 --delay-ms 22 --detune 12 --spread 1.0 --mix 0.5
"""
import argparse
import numpy as np
import soundfile as sf


def detuned_copy(x, sr, delay_ms, detune_cents):
    """A delayed, slightly pitch/time-shifted copy (resample = detune + drift)."""
    ratio = 2 ** (detune_cents / 1200.0)
    n = len(x)
    idx = np.arange(int(n / ratio)) * ratio
    idx = idx[idx < n - 1]
    shifted = np.interp(idx, np.arange(n), x)             # resample -> detune
    d = int(sr * delay_ms / 1000.0)
    out = np.zeros(n)
    seg = shifted[: max(0, n - d)]
    out[d:d + len(seg)] = seg
    return out


def main():
    ap = argparse.ArgumentParser(description="doubler — vocal doubler / ADT / widener (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--voices", type=int, default=2, help="number of doubled copies (panned ±)")
    ap.add_argument("--delay-ms", type=float, default=22.0)
    ap.add_argument("--detune", type=float, default=12.0, help="max detune in cents")
    ap.add_argument("--spread", type=float, default=1.0, help="0=center .. 1=hard L/R")
    ap.add_argument("--mix", type=float, default=0.5, help="0=dry .. 1=doubles only")
    a = ap.parse_args()

    x, sr = sf.read(a.input)
    mono = x.mean(axis=1) if x.ndim > 1 else x
    L = mono.copy(); R = mono.copy()
    for v in range(a.voices):
        sign = 1 if v % 2 == 0 else -1
        det = sign * a.detune * (1 + 0.3 * v)
        dly = a.delay_ms * (1 + 0.25 * v)
        cp = detuned_copy(mono, sr, dly, det)
        pan = sign * a.spread                              # -1 L .. +1 R
        gl = np.sqrt(0.5 * (1 - pan)); gr = np.sqrt(0.5 * (1 + pan))
        L += a.mix * gl * cp
        R += a.mix * gr * cp
    y = np.stack([L, R], axis=1)

    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y, sr)
    # self-check: stereo width = energy of side vs mid
    mid = (y[:, 0] + y[:, 1]) / 2; side = (y[:, 0] - y[:, 1]) / 2
    print(f"doubler: {a.voices} voice(s) delay {a.delay_ms:g}ms detune {a.detune:g}c mix {a.mix:g} | "
          f"side/mid {20*np.log10((np.sqrt(np.mean(side**2))+1e-12)/(np.sqrt(np.mean(mid**2))+1e-12)):+.1f}dB -> {a.output}")


if __name__ == "__main__":
    main()
