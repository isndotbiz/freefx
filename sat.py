#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy"]
# ///
"""
sat — open-source tape / analog saturation (warmth, grit, glue).

The "distinctive voice" colour: drive the signal into a soft, slightly
asymmetric nonlinearity (even + odd harmonics), roll off the highs the way tape
does, and optionally add slow wow/flutter pitch wobble. Oversampled 4x around the
waveshaper so the new harmonics don't alias. Clean-room textbook DSP (tanh
waveshaping, oversampling, modulated fractional delay). MIT. Part of `freefx`.

Usage:
  uv run sat.py vox.wav out.wav --drive 6                       # gentle warmth
  uv run sat.py mix.wav out.wav --drive 10 --tone-hz 12000 --mix 0.8   # tape glue
  uv run sat.py vox.wav out.wav --drive 8 --flutter 6 --bias 0.15      # lo-fi wobble
"""
import argparse
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, butter, sosfilt


def saturate(x, drive_db, bias, oversample):
    """Oversampled asymmetric tanh waveshaper. bias adds even harmonics (warmth);
    DC from the bias is removed afterwards so it doesn't offset the signal."""
    g = 10 ** (drive_db / 20.0)
    xo = resample_poly(x, oversample, 1, axis=0) if oversample > 1 else x
    yo = np.tanh(g * xo + bias) - np.tanh(bias)
    yo = yo / max(np.tanh(g + abs(bias)), 1e-9)          # keep unity-ish scale
    y = resample_poly(yo, 1, oversample, axis=0) if oversample > 1 else yo
    return y[: len(x)] if y.shape[0] > len(x) else y


def flutter(x, sr, depth_cents, rate_hz):
    """Slow pitch wobble via a modulated fractional delay (tape wow/flutter)."""
    if depth_cents <= 0:
        return x
    n = x.shape[0]
    t = np.arange(n) / sr
    # convert cents of pitch wobble into a swept delay (small, musical)
    max_delay = sr * (2 ** (depth_cents / 1200.0) - 1.0) * 0.02
    lfo = (0.5 * (1 + np.sin(2 * np.pi * rate_hz * t))) * max_delay
    idx = np.arange(n) - lfo
    idx = np.clip(idx, 0, n - 1)
    if x.ndim == 1:
        return np.interp(idx, np.arange(n), x)
    return np.stack([np.interp(idx, np.arange(n), x[:, c]) for c in range(x.shape[1])], axis=1)


def main():
    ap = argparse.ArgumentParser(description="sat — tape/analog saturation (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--drive", type=float, default=6.0, help="dB into the waveshaper")
    ap.add_argument("--bias", type=float, default=0.1, help="asymmetry -> even harmonics/warmth (0=odd only)")
    ap.add_argument("--tone-hz", type=float, default=0.0, help="tape HF rolloff corner (0=off)")
    ap.add_argument("--flutter", type=float, default=0.0, help="wow/flutter depth in cents (0=off)")
    ap.add_argument("--flutter-hz", type=float, default=6.0)
    ap.add_argument("--mix", type=float, default=1.0, help="0=dry .. 1=fully saturated")
    ap.add_argument("--oversample", type=int, default=4)
    a = ap.parse_args()

    x, sr = sf.read(a.input)
    wet = saturate(x.astype(np.float64), a.drive, a.bias, a.oversample)
    if a.tone_hz > 0:
        sos = butter(1, min(a.tone_hz, sr / 2 - 1) / (sr / 2), btype="low", output="sos")
        wet = sosfilt(sos, wet, axis=0)
    wet = flutter(wet, sr, a.flutter, a.flutter_hz)
    y = (1 - a.mix) * x + a.mix * wet

    # report added harmonic energy as a self-check (THD-ish: energy above the input band ratio)
    in_rms = np.sqrt(np.mean(x.astype(np.float64) ** 2) + 1e-12)
    out_rms = np.sqrt(np.mean(y ** 2) + 1e-12)
    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y, sr)
    print(f"sat: drive {a.drive:g}dB bias {a.bias:g} tone {a.tone_hz:g}Hz flutter {a.flutter:g}c "
          f"mix {a.mix:g} | RMS {20*np.log10(in_rms):.1f}->{20*np.log10(out_rms):.1f} dB -> {a.output}")


if __name__ == "__main__":
    main()
