#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy"]
# ///
"""
tplimit — open-source true-peak brickwall limiter / loudness maximizer.

Oversampled look-ahead limiting: catches inter-sample (true) peaks by limiting at
an upsampled rate, so the final file never exceeds the ceiling in dBTP. Optional
--target-lufs auto-calibrates input gain to hit a loudness target (a "maximizer"),
the way you'd push a master to -9 LUFS while staying true-peak safe.

Clean-room, standard DSP. MIT. Part of the `freefx` open-source effects suite.

Usage:
  uv run tplimit.py in.wav out.wav --ceiling -1                 # limit peaks to -1 dBTP
  uv run tplimit.py in.wav out.wav --gain 6 --ceiling -1        # drive +6 dB into the limiter
  uv run tplimit.py in.wav out.wav --target-lufs -9 --ceiling -1  # maximize to -9 LUFS, TP-safe
"""
import argparse, subprocess, sys, tempfile, os
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, lfilter, lfilter_zi
from scipy.ndimage import maximum_filter1d

def limit(x, sr, ceiling_db=-1.0, gain_db=0.0, oversample=4, lookahead_ms=2.0, release_ms=60.0):
    if x.ndim == 1: x = x[:, None]
    # 0.3 dB safety margin: downsampling reintroduces tiny inter-sample peaks, so aim
    # slightly below the requested ceiling to guarantee the FINAL true-peak stays under it.
    ceil = 10 ** ((ceiling_db - 0.3) / 20.0)
    x = x * (10 ** (gain_db / 20.0))
    xo = resample_poly(x, oversample, 1, axis=0)              # upsample to see inter-sample peaks
    sro = sr * oversample
    peak = np.max(np.abs(xo), axis=1)                         # link channels
    la = max(1, int(sro * lookahead_ms / 1000.0))
    env = maximum_filter1d(peak, size=la, mode="nearest")     # look-ahead peak envelope
    desired = np.where(env > ceil, ceil / np.maximum(env, 1e-12), 1.0)
    a = np.exp(-1.0 / (sro * release_ms / 1000.0))           # one-pole release
    zi = lfilter_zi([1 - a], [1, -a]) * desired[0]
    smoothed, _ = lfilter([1 - a], [1, -a], desired, zi=zi)
    g = np.minimum(desired, smoothed)                         # instant attack, smooth release
    yo = np.clip(xo * g[:, None], -ceil, ceil)               # clip in OVERSAMPLED domain
    y = resample_poly(yo, 1, oversample, axis=0)
    return y[:, 0] if y.shape[1] == 1 else y

def measure_lufs(path):
    r = subprocess.run(["ffmpeg", "-i", path, "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                       capture_output=True, text=True)
    vals = [l for l in r.stderr.splitlines() if "I:" in l and "LUFS" in l]
    return float(vals[-1].split("I:")[1].split("LUFS")[0].strip()) if vals else 0.0

def main():
    ap = argparse.ArgumentParser(description="tplimit — true-peak limiter / maximizer (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--ceiling", type=float, default=-1.0, help="output ceiling in dBTP (default -1)")
    ap.add_argument("--gain", type=float, default=0.0, help="input drive in dB")
    ap.add_argument("--target-lufs", type=float, default=None, help="auto-calibrate gain to this LUFS")
    ap.add_argument("--oversample", type=int, default=4)
    ap.add_argument("--lookahead-ms", type=float, default=2.0)
    ap.add_argument("--release-ms", type=float, default=60.0)
    a = ap.parse_args()
    x, sr = sf.read(a.input)

    if a.target_lufs is None:
        y = limit(x, sr, a.ceiling, a.gain, a.oversample, a.lookahead_ms, a.release_ms)
        sf.write(a.output, y, sr)
        print(f"tplimit: ceiling {a.ceiling} dBTP, gain {a.gain} dB -> {a.output}")
        return

    # maximizer: bisect input gain to hit target LUFS (TP stays safe via the limiter)
    lo, hi, gain = 0.0, 36.0, 6.0
    best = None
    tmp = a.output + ".cal.wav"
    for it in range(8):
        y = limit(x, sr, a.ceiling, gain, a.oversample, a.lookahead_ms, a.release_ms)
        sf.write(tmp, y, sr)
        I = measure_lufs(tmp)
        print(f"  iter {it}: gain={gain:.1f}dB -> {I:.1f} LUFS")
        if best is None or abs(I - a.target_lufs) < abs(best[1] - a.target_lufs): best = (gain, I)
        if abs(I - a.target_lufs) <= 0.3: break
        if I < a.target_lufs: lo = gain; gain = (gain + hi) / 2.0
        else:                 hi = gain; gain = (lo + gain) / 2.0
    y = limit(x, sr, a.ceiling, best[0], a.oversample, a.lookahead_ms, a.release_ms)
    sf.write(a.output, y, sr)
    try: os.remove(tmp)
    except OSError: pass
    print(f"tplimit: maximized to {best[1]:.1f} LUFS (gain {best[0]:.1f}dB, ceiling {a.ceiling} dBTP) -> {a.output}")

if __name__ == "__main__":
    main()
