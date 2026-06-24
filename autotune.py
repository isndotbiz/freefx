#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyworld", "soundfile", "numpy<2", "setuptools<80"]
# ///
"""
autotune — open-source hard pitch tuning (the creative T-Pain / trap effect).

Where `pitchpin` does *transparent* correction (nudge toward the note, keep it
human), `autotune` is the *effect*: snap dead-flat to the scale with a
controllable glide. `--retune-ms 0` is the robotic staircase; bump it up for the
slurred T-Pain glide. Adds the two knobs the correction tool doesn't have:

  --retune-ms  how fast the pitch slews to the snapped note (0 = instant/hard)
  --formant    shift the formants independently of pitch — go NEGATIVE for a
               deeper / darker / bigger voice, positive for brighter/smaller
  --pitch      transpose the whole vocal by N semitones (e.g. -2 for baritone)

Clean-room: built on the open-source WORLD vocoder (BSD) + public DSP. No
proprietary code, no decompilation, monophonic only (polyphonic note access is
patented elsewhere and deliberately out of scope). MIT. Part of `freefx`.

How it works:
  1. WORLD analysis -> F0, spectral envelope (formants), aperiodicity
  2. snap each voiced F0 to the nearest scale note, then slew toward it at the
     retune rate (one-pole in semitone space); 0 ms = instant hard tune
  3. optional formant warp of the envelope + global transpose
  4. WORLD resynthesis with the new F0 / envelope, original timing

Usage:
  uv run autotune.py vox.wav out.wav --key A --scale minor                 # hard tune
  uv run autotune.py vox.wav out.wav --key C --scale major --retune-ms 40  # T-Pain glide
  uv run autotune.py vox.wav out.wav --key A --scale minor --formant -3 --pitch -2  # deep/dark
"""
import argparse, sys
import numpy as np
import soundfile as sf

NOTE_IX = {"C":0,"C#":1,"DB":1,"D":2,"D#":3,"EB":3,"E":4,"F":5,"F#":6,"GB":6,
           "G":7,"G#":8,"AB":8,"A":9,"A#":10,"BB":10,"B":11}
SCALE = {"minor":{0,2,3,5,7,8,10}, "major":{0,2,4,5,7,9,11},
         "chromatic":set(range(12)),
         "minor_pentatonic":{0,3,5,7,10}, "major_pentatonic":{0,2,4,7,9}}
A4 = 440.0


def allowed_classes(key, scale):
    if not key or scale == "chromatic":
        return set(range(12))
    if key.upper() not in NOTE_IX:
        sys.exit(f"unknown key '{key}' (use C, C#, D, ... or Db/Eb spellings)")
    if scale not in SCALE:
        sys.exit(f"unknown scale '{scale}' (one of: {', '.join(SCALE)})")
    root = NOTE_IX[key.upper()]
    return {(root + i) % 12 for i in SCALE[scale]}


def snap_and_glide(f0, allowed, frame_s, retune_ms, strength, transpose):
    """Hard-snap each voiced F0 to the nearest scale note, then slew toward the
    target with a one-pole whose time constant is retune_ms (0 = instant). The
    slew runs in MIDI/semitone space so the glide is musical. Unvoiced gaps reset
    the slew so each new phrase snaps fresh instead of gliding across silence."""
    out = np.zeros_like(f0)
    coef = np.exp(-frame_s / (retune_ms / 1000.0)) if retune_ms > 0 else 0.0
    state = None
    for i, hz in enumerate(f0):
        if hz <= 0:
            out[i] = 0.0; state = None; continue
        m = 69 + 12 * np.log2(hz / A4)
        base = int(round(m))
        cands = [base + d for d in range(-3, 4) if ((base + d) - 69) % 12 in allowed]
        target = min(cands, key=lambda c: abs(c - m)) if cands else m
        target = m * (1 - strength) + target * strength       # strength<1 leaves it human
        state = target if state is None else coef * state + (1 - coef) * target
        out[i] = A4 * 2 ** ((state + transpose - 69) / 12)
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


def main():
    ap = argparse.ArgumentParser(description="autotune — hard pitch tuning effect (freefx, MIT).")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--key", default=None, help="root note, e.g. A, C#, Eb (omit = chromatic)")
    ap.add_argument("--scale", default="minor", help="minor|major|chromatic|minor_pentatonic|major_pentatonic")
    ap.add_argument("--retune-ms", type=float, default=0.0, help="slew time to the note (0 = hard/robotic)")
    ap.add_argument("--strength", type=float, default=1.0, help="1=full snap (default) .. 0=off")
    ap.add_argument("--formant", type=float, default=0.0, help="formant shift in semitones (negative = deeper)")
    ap.add_argument("--pitch", type=float, default=0.0, help="global transpose in semitones (negative = lower)")
    ap.add_argument("--fast", action="store_true", help="dio+stonemask F0 (faster, less accurate) vs harvest")
    a = ap.parse_args()
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

    frame_s = (t[1] - t[0]) if len(t) > 1 else 0.005
    allowed = allowed_classes(a.key, a.scale)
    f0c = snap_and_glide(f0, allowed, frame_s, a.retune_ms, a.strength, a.pitch)
    sp = warp_formants(sp, a.formant)

    out = pw.synthesize(np.ascontiguousarray(f0c), sp, ap_, sr).astype(np.float32)
    peak = float(np.max(np.abs(out)))
    if peak > 0.999:
        out = out / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, out, sr)

    voiced = int((f0 > 0).sum())
    print(f"autotune: {voiced} voiced frames | key={a.key or 'chromatic'} "
          f"{a.scale if a.key else ''} | retune={a.retune_ms:g}ms strength={a.strength:g} "
          f"formant={a.formant:+g} pitch={a.pitch:+g} -> {a.output}")


if __name__ == "__main__":
    main()
