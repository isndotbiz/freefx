#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyworld", "soundfile", "numpy<2", "setuptools<80"]
# ///
"""
formant — open-source pitch/formant color (alter-ego voice tool).

Where `pitchpin` corrects pitch and `autotune` snaps it to a scale, `formant`
does NO scale snapping at all — it is pure *color*: transpose the whole vocal
and/or move the formants independently. This is the "deep dark voice" /
"chipmunk texture" / gender-bend tool:

  --pitch    transpose F0 by N semitones (fractional OK, e.g. -2.5); the
             formants stay put unless you also move them, so a plain -5 sounds
             like the same person singing lower, not a slowed-down tape
  --formant  shift the formants independently of pitch — NEGATIVE for a
             deeper / darker / bigger voice, POSITIVE for brighter / smaller
  --mix      blend the processed voice with the dry one (0..1); WORLD
             resynthesis preserves timing, so the blend stays phase-coherent
             enough for parallel color tricks

Clean-room: built on the open-source WORLD vocoder (BSD) + public DSP. No
proprietary code, no decompilation, monophonic only. MIT. Part of `freefx`.

How it works:
  1. WORLD analysis -> F0, spectral envelope (formants), aperiodicity
  2. multiply voiced F0 by 2^(pitch/12); unvoiced frames (F0=0) stay 0
  3. warp the spectral envelope along frequency by 2^(formant/12)
  4. WORLD resynthesis with original timing, then dry/wet mix

Stereo inputs are downmixed to mono before analysis and the output is mono
(same approach as autotune.py — WORLD is a monophonic model).

Usage:
  uv run formant.py vox.wav out.wav --pitch -5                    # lower voice, same character
  uv run formant.py vox.wav out.wav --formant -4                  # deep/dark/bigger, same pitch
  uv run formant.py vox.wav out.wav --pitch 4 --formant 5         # chipmunk texture
  uv run formant.py vox.wav out.wav --pitch -2 --formant -3 --mix 0.6  # subtle alter-ego blend
"""
import argparse, sys
import numpy as np
import soundfile as sf


def transpose_f0(f0, semitones):
    """Scale voiced F0 by 2^(semitones/12); unvoiced frames (F0=0) stay 0."""
    if semitones == 0:
        return f0
    out = f0 * (2.0 ** (semitones / 12.0))
    out[f0 <= 0] = 0.0
    return out


def warp_formants(sp, semitones):
    """Shift the spectral envelope (formants) by N semitones without touching F0.
    Negative = lower formants = deeper/bigger voice. E'(f) = E(f / s)."""
    if semitones == 0:
        return sp
    F = sp.shape[1]
    idx = np.arange(F)
    read = idx * (2.0 ** (-semitones / 12.0))                 # sample source at k/s
    out = np.empty_like(sp)
    for t in range(sp.shape[0]):
        out[t] = np.interp(read, idx, sp[t])
    return np.ascontiguousarray(out)


def blend(wet, dry, mix):
    """Weighted sum of processed and dry. WORLD resynthesis keeps the original
    timing, so a plain sum is time-aligned; lengths are matched defensively
    because synthesize() can differ from the input by a few samples."""
    if mix >= 1.0:
        return wet
    n = min(len(wet), len(dry))
    return mix * wet[:n] + (1.0 - mix) * dry[:n]


def main():
    ap = argparse.ArgumentParser(description="formant — pitch/formant color, no scale snapping (freefx, MIT).")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--pitch", type=float, default=0.0, help="transpose in semitones, fractional OK (negative = lower)")
    ap.add_argument("--formant", type=float, default=0.0, help="formant shift in semitones (negative = deeper/darker)")
    ap.add_argument("--mix", type=float, default=1.0, help="wet/dry blend 0..1 (1 = fully processed)")
    ap.add_argument("--fast", action="store_true", help="dio+stonemask F0 (faster, less accurate) vs harvest")
    a = ap.parse_args()
    if not (0.0 <= a.mix <= 1.0):
        sys.exit(f"--mix must be in 0..1 (got {a.mix:g})")
    import pyworld as pw

    y, sr = sf.read(a.input)
    if y.ndim > 1:
        y = y.mean(axis=1)
    x = np.ascontiguousarray(y.astype(np.float64))

    if a.fast:
        f0, t = pw.dio(x, sr); f0 = pw.stonemask(x, f0, t, sr)
    else:
        f0, t = pw.harvest(x, sr)
    sp = pw.cheaptrick(x, f0, t, sr)
    ap_ = pw.d4c(x, f0, t, sr)

    f0c = transpose_f0(f0, a.pitch)
    sp = warp_formants(sp, a.formant)

    out = pw.synthesize(np.ascontiguousarray(f0c), sp, ap_, sr)
    out = blend(out, x, a.mix).astype(np.float32)
    peak = float(np.max(np.abs(out)))
    if peak > 0.999:
        out = out / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, out, sr)

    voiced = int((f0 > 0).sum())
    print(f"formant: {voiced} voiced frames | pitch={a.pitch:+g} formant={a.formant:+g} "
          f"mix={a.mix:g}{' fast' if a.fast else ''} -> {a.output}")


if __name__ == "__main__":
    main()
