#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy"]
# ///
"""
width — open-source stereo width (M/S) + bass mono-maker.

Mid/Side processing: scale the Side signal to narrow or widen the stereo image,
and optionally collapse everything below a frequency to mono (so the low end
stays centred and translates on club/vinyl systems). Clean-room M/S matrix +
crossover. MIT. Part of `freefx`.

Usage:
  uv run width.py mix.wav out.wav --width 1.4                 # wider
  uv run width.py master.wav out.wav --width 1.2 --mono-hz 120  # widen highs, mono the bass
  uv run width.py track.wav out.wav --width 0.6               # narrower / more mono
"""
import argparse
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt


def main():
    ap = argparse.ArgumentParser(description="width — stereo width + mono-maker (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--width", type=float, default=1.2, help="0=mono, 1=unchanged, >1 wider")
    ap.add_argument("--mono-hz", type=float, default=0.0, help="collapse below this Hz to mono (0=off)")
    a = ap.parse_args()

    x, sr = sf.read(a.input, always_2d=True)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    xd = x.astype(np.float64)
    mid = (xd[:, 0] + xd[:, 1]) * 0.5
    side = (xd[:, 0] - xd[:, 1]) * 0.5
    side *= a.width

    if a.mono_hz > 0:
        sos = butter(2, min(a.mono_hz, sr / 2 - 1) / (sr / 2), btype="low", output="sos")
        side_low = sosfilt(sos, side)
        side = side - side_low                            # remove low-freq side content -> bass is mono

    L = mid + side; R = mid - side
    y = np.stack([L, R], axis=1)
    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y, sr)
    s = (y[:, 0] - y[:, 1]) * 0.5; m = (y[:, 0] + y[:, 1]) * 0.5
    print(f"width: width {a.width:g} mono<{a.mono_hz:g}Hz | "
          f"side/mid {20*np.log10((np.sqrt(np.mean(s**2))+1e-12)/(np.sqrt(np.mean(m**2))+1e-12)):+.1f}dB -> {a.output}")


if __name__ == "__main__":
    main()
