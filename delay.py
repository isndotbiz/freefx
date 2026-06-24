#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy", "numba"]
# ///
"""
delay — open-source stereo / ping-pong feedback delay (vocal throws).

A feedback delay line with optional ping-pong (echoes bounce L<->R) and a tone
control in the feedback path (each repeat gets darker, like analog/tape echo).
The trap/emo vocal "throw" — print it and it's part of the track, no DAW needed.
Clean-room. MIT. Part of `freefx`.

Usage:
  uv run delay.py vox.wav out.wav --time-ms 375 --feedback 0.4 --mix 0.3        # 1/4 throw
  uv run delay.py vox.wav out.wav --time-ms 250 --feedback 0.5 --pingpong --tone 4000
"""
import argparse
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt
from numba import njit


@njit(cache=True)
def _fbdelay(L, R, d, fb, pingpong):
    n = L.shape[0]
    oL = np.zeros(n); oR = np.zeros(n)
    for i in range(n):
        jL = i - d
        jR = i - d
        eL = oL[jL] if jL >= 0 else 0.0
        eR = oR[jR] if jR >= 0 else 0.0
        if pingpong:
            oL[i] = L[i] + fb * eR
            oR[i] = R[i] + fb * eL
        else:
            oL[i] = L[i] + fb * eL
            oR[i] = R[i] + fb * eR
    return oL, oR


def main():
    ap = argparse.ArgumentParser(description="delay — stereo/ping-pong delay (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--time-ms", type=float, default=375.0)
    ap.add_argument("--feedback", type=float, default=0.4, help="0..0.95")
    ap.add_argument("--pingpong", action="store_true")
    ap.add_argument("--tone", type=float, default=0.0, help="lowpass the feedback at this Hz (0=off)")
    ap.add_argument("--mix", type=float, default=0.3, help="0=dry .. 1=wet only")
    a = ap.parse_args()

    x, sr = sf.read(a.input, always_2d=True)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    xd = np.ascontiguousarray(x.astype(np.float64))
    d = int(sr * a.time_ms / 1000.0)
    fb = min(max(a.feedback, 0.0), 0.95)
    L_in = np.ascontiguousarray(xd[:, 0]); R_in = np.ascontiguousarray(xd[:, 1])
    if a.tone > 0:                                        # darken the input feeding the delay
        sos = butter(1, min(a.tone, sr / 2 - 1) / (sr / 2), btype="low", output="sos")
        L_in = sosfilt(sos, L_in); R_in = sosfilt(sos, R_in)
    wetL, wetR = _fbdelay(L_in, R_in, d, fb, a.pingpong)
    # the delayed component only (subtract the dry that passed straight through the recursion seed)
    wetL = wetL - L_in; wetR = wetR - R_in
    y = np.stack([xd[:, 0] + a.mix * wetL, xd[:, 1] + a.mix * wetR], axis=1)

    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y, sr)
    print(f"delay: {a.time_ms:g}ms fb {fb:g} {'ping-pong ' if a.pingpong else ''}tone {a.tone:g} "
          f"mix {a.mix:g} | {a.feedback and int(np.log(0.01)/np.log(max(fb,1e-3))) or 0} audible repeats -> {a.output}")


if __name__ == "__main__":
    main()
