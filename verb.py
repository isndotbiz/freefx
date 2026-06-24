#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "numba"]
# ///
"""
verb — open-source algorithmic reverb (Freeverb-style: parallel damped combs + series allpass).

Clean-room implementation of the public-domain Freeverb topology (8 lowpass-feedback
comb filters in parallel -> 4 allpass filters in series, per channel). Delay-line
loops are JIT-compiled (numba) so it runs fast on a full track. MIT. Part of `freefx`.

Usage:
  uv run verb.py in.wav out.wav --roomsize 0.7 --damp 0.4 --wet 0.3
  uv run verb.py vocal.wav wet.wav --roomsize 0.85 --wet 0.22 --predelay-ms 25 --tail-sec 2

Params: --roomsize 0..1 (decay), --damp 0..1 (HF absorption), --wet/--dry levels,
        --width 0..1 (stereo spread), --predelay-ms, --tail-sec (ring-out past the input).
"""
import argparse
import numpy as np
import soundfile as sf
from numba import njit

# Freeverb tunings (samples @ 44100); scaled to the file's samplerate at runtime.
COMB = np.array([1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617])
ALLPASS = np.array([556, 441, 341, 225])
STEREOSPREAD = 23
FIXEDGAIN = 0.015

@njit(cache=True)
def comb(x, M, fb, damp):
    y = np.zeros_like(x); buf = np.zeros(M); fs = 0.0; idx = 0
    for n in range(x.shape[0]):
        out = buf[idx]
        fs = out * (1.0 - damp) + fs * damp     # one-pole lowpass in the feedback
        buf[idx] = x[n] + fs * fb
        y[n] = out
        idx += 1
        if idx >= M: idx = 0
    return y

@njit(cache=True)
def allpass(x, M, fb):
    y = np.zeros_like(x); buf = np.zeros(M); idx = 0
    for n in range(x.shape[0]):
        bo = buf[idx]
        y[n] = -x[n] + bo
        buf[idx] = x[n] + bo * fb
        idx += 1
        if idx >= M: idx = 0
    return y

def reverb_channel(x, combs, allps, roomfb, damp):
    acc = np.zeros_like(x)
    for M in combs:
        acc += comb(x, int(M), roomfb, damp)
    for M in allps:
        acc = allpass(acc, int(M), 0.5)
    return acc

def main():
    ap = argparse.ArgumentParser(description="verb — Freeverb-style reverb (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--roomsize", type=float, default=0.6, help="0..1 decay/size")
    ap.add_argument("--damp", type=float, default=0.5, help="0..1 HF damping")
    ap.add_argument("--wet", type=float, default=0.3)
    ap.add_argument("--dry", type=float, default=0.7)
    ap.add_argument("--width", type=float, default=1.0, help="0..1 stereo spread")
    ap.add_argument("--predelay-ms", type=float, default=0.0)
    ap.add_argument("--tail-sec", type=float, default=0.0, help="extra ring-out past the input")
    a = ap.parse_args()

    x, sr = sf.read(a.input)
    if x.ndim == 1: x = np.column_stack([x, x])
    x = x.astype(np.float64)
    scale = sr / 44100.0
    combs = np.maximum(1, (COMB * scale).astype(np.int64))
    allps = np.maximum(1, (ALLPASS * scale).astype(np.int64))
    combs_r = combs + int(STEREOSPREAD * scale)
    allps_r = allps + int(STEREOSPREAD * scale)
    roomfb = a.roomsize * 0.28 + 0.7
    dampv = a.damp * 0.4

    pad = int(max(0.0, a.tail_sec) * sr)
    xin = np.vstack([x, np.zeros((pad, 2))]) if pad else x
    drySig = xin.copy()
    gin = xin * FIXEDGAIN
    revL = reverb_channel(np.ascontiguousarray(gin[:, 0]), combs,   allps,   roomfb, dampv)
    revR = reverb_channel(np.ascontiguousarray(gin[:, 1]), combs_r, allps_r, roomfb, dampv)

    pre = int(max(0.0, a.predelay_ms) / 1000.0 * sr)
    if pre:
        revL = np.concatenate([np.zeros(pre), revL])[:len(revL)]
        revR = np.concatenate([np.zeros(pre), revR])[:len(revR)]

    wet1 = a.wet * (a.width / 2.0 + 0.5)
    wet2 = a.wet * ((1.0 - a.width) / 2.0)
    outL = a.dry * drySig[:, 0] + wet1 * revL + wet2 * revR
    outR = a.dry * drySig[:, 1] + wet1 * revR + wet2 * revL
    y = np.column_stack([outL, outR])
    peak = np.max(np.abs(y))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y.astype(np.float32), sr)
    print(f"verb: roomsize={a.roomsize} damp={a.damp} wet={a.wet} -> {a.output} "
          f"({len(y)/sr:.1f}s, tail {a.tail_sec}s)")

if __name__ == "__main__":
    main()
