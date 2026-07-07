#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy"]
# ///
"""
retro — open-source lo-fi color macro: noise, wobble, saturation, bitcrush, tone, dropouts.

One knob (`--age`) dials in the whole worn-media patina: tape hiss + vinyl
crackle bed, wow/flutter pitch instability, tape-ish tanh saturation, bit/rate
crush, a darkening tone tilt, and crossfaded dropout dips. Every sub-flag
overrides its age-derived value, and the resolved settings are printed so you
can see exactly what the macro chose. All randomness (noise, crackle, dropout
timing, LFO phases) is seeded -> renders are reproducible.

Signal order: wobble -> drive -> bitcrush -> tone -> noise bed -> dropouts -> mix.
(Pitch instability first so everything downstream "lives on the tape"; the noise
bed is added after tone so hiss keeps its own character; dropouts dip program
AND noise together, like a worn spot on the media. Note: wobble delays the wet
path by a few ms, so partial --mix values comb slightly — by design, keep
--mix high for the classic sound.)

Generic, well-known public DSP only (filtered noise, sparse impulses, modulated
fractional delay, tanh waveshaping, quantise + sample-and-hold, first-order
tilt, raised-cosine gain dips). Clean-room. MIT. Part of `freefx`.

Usage:
  uv run retro.py beat.wav out.wav --age 0.5                 # one-knob lo-fi
  uv run retro.py vox.wav out.wav --age 0.7 --wobble 0.2     # aged, but steadier pitch
  uv run retro.py loop.wav out.wav --age 0.3 --bits 8 --tone -0.9 --seed 42
"""
import argparse
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, resample_poly

TWO_PI = 2.0 * np.pi


def _sos_lp(hz, sr, order=1):
    return butter(order, min(hz, sr / 2 - 1) / (sr / 2), btype="low", output="sos")


def _sos_hp(hz, sr, order=1):
    return butter(order, max(hz, 10.0) / (sr / 2), btype="high", output="sos")


def wobble_fx(x, sr, amount, rng):
    """Wow (~0.9 Hz) + flutter (~7.5 Hz) via modulated fractional-delay resample.
    Delay depth per LFO is chosen so the peak pitch deviation is the stated cents:
    for d(t)=D*sin(2*pi*f*t) the instantaneous rate is 1-d'(t), so
    D = (2**(cents/1200)-1) / (2*pi*f)."""
    if amount <= 0:
        return x
    n = x.shape[0]
    t = np.arange(n) / sr
    wow_c, flut_c = 40.0 * amount, 9.0 * amount          # peak deviation, cents
    wow_hz = 0.9 + 0.6 * rng.random()                    # slight seeded variation
    flut_hz = 6.0 + 6.0 * rng.random()
    d_wow = (2 ** (wow_c / 1200.0) - 1.0) / (TWO_PI * wow_hz) * sr
    d_flu = (2 ** (flut_c / 1200.0) - 1.0) / (TWO_PI * flut_hz) * sr
    lfo = (d_wow * (1 + np.sin(TWO_PI * wow_hz * t + rng.random() * TWO_PI))
           + d_flu * (1 + np.sin(TWO_PI * flut_hz * t + rng.random() * TWO_PI)))
    idx = np.clip(np.arange(n) - lfo, 0, n - 1)
    return np.stack([np.interp(idx, np.arange(n), x[:, c]) for c in range(x.shape[1])], axis=1)


def drive_fx(x, sr, amount, oversample=4):
    """Tape-ish saturation: 4x-oversampled asymmetric tanh + gentle HF rolloff
    (drive-conditioned tone, like sat.py)."""
    if amount <= 0:
        return x
    g = 10 ** (12.0 * amount / 20.0)                     # up to +12 dB into the shaper
    bias = 0.08 * amount                                 # a little even-harmonic warmth
    xo = resample_poly(x, oversample, 1, axis=0)
    yo = np.tanh(g * xo + bias) - np.tanh(bias)
    yo /= max(np.tanh(g + abs(bias)), 1e-9)
    y = resample_poly(yo, 1, oversample, axis=0)[: x.shape[0]]
    return sosfilt(_sos_lp(16000 - 5000 * amount, sr), y, axis=0)


def bitcrush_fx(x, bits, downsample):
    """Quantise to `bits` + sample-and-hold downsample (like bitcrush.py)."""
    y = x
    if bits < 24:
        half = 2 ** (bits - 1)
        y = np.round(y * half) / half
    if downsample > 1:
        n = y.shape[0]
        hold = (np.arange(n) // downsample) * downsample
        y = y[np.clip(hold, 0, n - 1)]
    return y


def tone_fx(x, sr, tone):
    """Tilt: negative pulls a first-order lowpass down (16k -> ~2.2k at -1);
    positive adds complementary HF lift + a slight low trim."""
    if abs(tone) < 1e-3:
        return x
    if tone < 0:
        hz = 16000.0 * (2200.0 / 16000.0) ** (-tone)
        return sosfilt(_sos_lp(hz, sr), x, axis=0)
    y = x + 0.7 * tone * sosfilt(_sos_hp(2500, sr), x, axis=0)
    return sosfilt(_sos_hp(20 + 60 * tone, sr), y, axis=0)


def noise_bed(x, sr, amount, rng):
    """Tape hiss (highpassed white) + sparse band-limited vinyl crackle,
    level gently modulated by program level (quieter bed in true silence
    would be dishonest tape — so only ~35% modulation depth)."""
    if amount <= 0:
        return np.zeros_like(x)
    n = x.shape[0]
    hiss = sosfilt(_sos_hp(2000, sr, 2), rng.standard_normal(n)) * 0.02 * amount
    crk = np.zeros(n)
    npops = int(n / sr * 90 * amount)
    if npops > 0:
        pos = rng.integers(0, n, npops)
        crk[pos] = rng.standard_normal(npops) * rng.random(npops)
        crk = sosfilt(butter(2, [800 / (sr / 2), 6000 / (sr / 2)], btype="band", output="sos"), crk)
    bed = 0.14 * amount * crk + hiss
    env = sosfilt(_sos_lp(8, sr), np.mean(np.abs(x), axis=1))   # program level follower
    env = env / (np.max(env) + 1e-9)
    return (bed * (0.65 + 0.35 * np.clip(env, 0, 1)))[:, None]


def dropout_gain(n, sr, amount, rng):
    """Random raised-cosine level dips (worn tape). Returns a gain curve in
    (0,1]; cosine windows -> inherently click-free crossfades."""
    g = np.ones(n)
    if amount <= 0:
        return g[:, None]
    rate = 1.4 * amount                                  # events per second at full
    n_ev = rng.poisson(rate * n / sr)
    for _ in range(n_ev):
        dur = int(sr * (0.08 + 0.22 * rng.random()))     # 80..300 ms
        start = rng.integers(0, max(n - dur, 1))
        depth = amount * (0.35 + 0.45 * rng.random())    # dip 35..80% * amount
        win = 0.5 * (1 - np.cos(TWO_PI * np.arange(dur) / dur))   # 0->1->0
        g[start:start + dur] = np.minimum(g[start:start + dur], 1 - depth * win)
    return g[:, None]


def resolve(a):
    """age -> per-component defaults; explicit sub-flags override."""
    ag = float(np.clip(a.age, 0.0, 1.0))
    r = {
        "noise":   a.noise   if a.noise   is not None else round(0.70 * ag, 3),
        "wobble":  a.wobble  if a.wobble  is not None else round(0.55 * ag, 3),
        "drive":   a.drive   if a.drive   is not None else round(0.60 * ag, 3),
        "bits":    a.bits    if a.bits    is not None else int(round(16 - 8 * ag)),
        "downsample": 1 + (ag >= 0.55) + (ag >= 0.85),
        "tone":    a.tone    if a.tone    is not None else round(-0.80 * ag, 3),
        "dropout": a.dropout if a.dropout is not None else round(max(0.0, ag - 0.25) * 1.2, 3),
    }
    return r


def main():
    ap = argparse.ArgumentParser(description="retro — lo-fi color macro (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--age", type=float, default=0.5, help="one-knob macro 0..1 (sets everything below)")
    ap.add_argument("--noise", type=float, default=None, help="hiss+crackle bed 0..1 (override)")
    ap.add_argument("--wobble", type=float, default=None, help="wow/flutter 0..1 (override)")
    ap.add_argument("--drive", type=float, default=None, help="tape saturation 0..1 (override)")
    ap.add_argument("--bits", type=int, default=None, help="bit depth (override; age maps 16..8)")
    ap.add_argument("--tone", type=float, default=None, help="tilt -1 dark .. +1 bright (override)")
    ap.add_argument("--dropout", type=float, default=None, help="tape dropouts 0..1 (override)")
    ap.add_argument("--mix", type=float, default=1.0, help="0=dry .. 1=wet")
    ap.add_argument("--seed", type=int, default=1337, help="seeds ALL randomness -> reproducible")
    a = ap.parse_args()

    x, sr = sf.read(a.input, always_2d=True)
    xd = x.astype(np.float64)
    rng = np.random.default_rng(a.seed)
    r = resolve(a)
    print(f"retro: age {a.age:g} -> noise {r['noise']:g} wobble {r['wobble']:g} drive {r['drive']:g} "
          f"bits {r['bits']} ds {r['downsample']} tone {r['tone']:g} dropout {r['dropout']:g} "
          f"mix {a.mix:g} seed {a.seed}")

    y = wobble_fx(xd, sr, r["wobble"], rng)              # 1. pitch instability
    y = drive_fx(y, sr, r["drive"])                      # 2. tape saturation
    y = bitcrush_fx(y, r["bits"], r["downsample"])       # 3. bit/rate crush
    y = tone_fx(y, sr, r["tone"])                        # 4. tilt
    y = y + noise_bed(y, sr, r["noise"], rng)            # 5. hiss + crackle bed
    y = y * dropout_gain(y.shape[0], sr, r["dropout"], rng)   # 6. worn-tape dips
    y = (1 - a.mix) * xd + a.mix * y                     # 7. wet/dry

    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y[:, 0] if y.shape[1] == 1 else y, sr)
    out_rms = 20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-12)
    print(f"retro: RMS {out_rms:.1f} dBFS peak {min(peak, 0.999):.3f} -> {a.output}")


if __name__ == "__main__":
    main()
