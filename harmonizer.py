#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyworld", "soundfile", "numpy<2", "setuptools<80"]
# ///
"""
harmonizer — open-source pitch harmonizer (octaves / fifths / thirds).

Generates pitch-shifted copies of a monophonic vocal at fixed musical intervals
and blends them under the dry voice — sub-octave for weight, a fifth/third for
a thickened harmony stack. Built on the WORLD vocoder (shift F0, keep the
formants/timing) so the harmonies keep the vocal's character. Clean-room (WORLD
is BSD; monophonic only). MIT. Part of `freefx`.

Usage:
  uv run harmonizer.py vox.wav out.wav --interval -12 --mix 0.4         # sub-octave weight
  uv run harmonizer.py vox.wav out.wav --interval 7 --interval 12 --mix 0.3  # 5th + octave stack
  uv run harmonizer.py vox.wav out.wav --interval -12 --formant -2      # deeper sub-octave
"""
import argparse
import numpy as np
import soundfile as sf


def warp_formants(sp, semitones):
    if semitones == 0:
        return sp
    F = sp.shape[1]; idx = np.arange(F)
    read = idx * (2.0 ** (-semitones / 12.0))
    out = np.empty_like(sp)
    for t in range(sp.shape[0]):
        out[t] = np.interp(read, idx, sp[t])
    return np.ascontiguousarray(out)


def main():
    ap = argparse.ArgumentParser(description="harmonizer — pitch harmonizer (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--interval", action="append", type=float, default=[], help="semitones (repeatable)")
    ap.add_argument("--formant", type=float, default=0.0, help="formant shift on the harmonies (semitones)")
    ap.add_argument("--mix", type=float, default=0.4, help="0=dry .. 1=harmonies only")
    a = ap.parse_args()
    intervals = a.interval or [-12.0]
    import pyworld as pw

    y, sr = sf.read(a.input)
    if y.ndim > 1:
        y = y.mean(axis=1)
    x = np.ascontiguousarray(y.astype(np.float64))
    f0, t = pw.harvest(x, sr)
    sp = pw.cheaptrick(x, f0, t, sr)
    ap_ = pw.d4c(x, f0, t, sr)
    spF = warp_formants(sp, a.formant)

    out = x.copy() * (1 - a.mix * 0.0)                    # dry stays at unity
    harm = np.zeros_like(x)
    for iv in intervals:
        f0s = f0 * (2 ** (iv / 12.0))
        v = pw.synthesize(np.ascontiguousarray(f0s), spF, ap_, sr)
        harm[: len(v)] += v[: len(harm)]
    harm /= max(len(intervals), 1)
    mixed = out + a.mix * harm

    peak = float(np.max(np.abs(mixed)))
    if peak > 0.999:
        mixed = mixed / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, mixed.astype(np.float32), sr)
    print(f"harmonizer: intervals {intervals} formant {a.formant:+g} mix {a.mix:g} -> {a.output}")


if __name__ == "__main__":
    main()
