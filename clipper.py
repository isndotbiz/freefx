#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy"]
# ///
"""
clipper — open-source soft/hard clipper (the modern trap-loudness tool).

Different from `tplimit`: a limiter rides gain down with look-ahead to PROTECT a
ceiling transparently; a clipper just flattens whatever pokes over it, instantly.
That's how trap/hip-hop masters get loud and aggressive — clip the 808/master a
few dB into a ceiling before the limiter. Oversampled 4x so the clipping
harmonics don't alias. Clean-room textbook DSP (waveshaping + oversampling). MIT.

Usage:
  uv run clipper.py master.wav out.wav --drive 4 --ceiling -1            # soft clip 4 dB in
  uv run clipper.py 808.wav out.wav --drive 6 --ceiling -0.5 --hard       # hard clip
  uv run clipper.py mix.wav out.wav --drive 3 --mix 0.7                   # parallel clip
"""
import argparse
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


def clip(x, drive_db, ceiling_db, hard, oversample):
    g = 10 ** (drive_db / 20.0)
    c = 10 ** (ceiling_db / 20.0)
    xo = resample_poly(x, oversample, 1, axis=0) if oversample > 1 else x
    driven = g * xo
    if hard:
        yo = np.clip(driven, -c, c)
    else:
        yo = c * np.tanh(driven / c)                     # smooth knee, asymptotic to ceiling
    y = resample_poly(yo, 1, oversample, axis=0) if oversample > 1 else yo
    y = y[: len(x)] if y.shape[0] > len(x) else y
    return y, g, c


def main():
    ap = argparse.ArgumentParser(description="clipper — soft/hard clipper (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--drive", type=float, default=3.0, help="dB pushed into the clipper")
    ap.add_argument("--ceiling", type=float, default=-1.0, help="clip ceiling, dBFS")
    ap.add_argument("--hard", action="store_true", help="hard clip (default soft tanh knee)")
    ap.add_argument("--mix", type=float, default=1.0, help="0=dry .. 1=fully clipped (parallel)")
    ap.add_argument("--oversample", type=int, default=4)
    a = ap.parse_args()

    x, sr = sf.read(a.input)
    wet, g, c = clip(x.astype(np.float64), a.drive, a.ceiling, a.hard, a.oversample)
    y = (1 - a.mix) * x + a.mix * wet

    over = np.mean(np.abs(g * x.astype(np.float64)) > c) * 100         # % samples actually clipped
    crest_in = 20 * np.log10(np.max(np.abs(x)) / (np.sqrt(np.mean(x**2)) + 1e-12) + 1e-12)
    crest_out = 20 * np.log10(np.max(np.abs(y)) / (np.sqrt(np.mean(y**2)) + 1e-12) + 1e-12)
    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y, sr)
    print(f"clipper ({'hard' if a.hard else 'soft'}): drive {a.drive:g}dB ceiling {a.ceiling:g} "
          f"mix {a.mix:g} | {over:.1f}% samples clipped | crest {crest_in:.1f}->{crest_out:.1f} dB -> {a.output}")


if __name__ == "__main__":
    main()
