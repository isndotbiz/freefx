#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2"]
# ///
"""
bitcrush — open-source bit-depth + sample-rate crusher (lo-fi texture).

Two classic lo-fi degradations: quantise to fewer bits (adds quantisation grit)
and sample-and-hold downsample (aliased, "crunchy" highs). Blend back for a
parallel lo-fi colour. Clean-room. MIT. Part of `freefx`.

Usage:
  uv run bitcrush.py vox.wav out.wav --bits 8 --downsample 2        # mild lo-fi
  uv run bitcrush.py loop.wav out.wav --bits 6 --downsample 4 --mix 0.6
"""
import argparse
import numpy as np
import soundfile as sf


def main():
    ap = argparse.ArgumentParser(description="bitcrush — bit/rate crusher (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--bits", type=int, default=8, help="quantisation bit depth")
    ap.add_argument("--downsample", type=int, default=1, help="sample-and-hold factor (1=off)")
    ap.add_argument("--mix", type=float, default=1.0, help="0=dry .. 1=fully crushed")
    a = ap.parse_args()

    x, sr = sf.read(a.input, always_2d=True)
    xd = x.astype(np.float64)
    levels = 2 ** a.bits
    wet = np.round(xd * (levels / 2)) / (levels / 2)      # bit-depth quantise
    if a.downsample > 1:
        n = wet.shape[0]
        hold = (np.arange(n) // a.downsample) * a.downsample   # sample-and-hold
        wet = wet[np.clip(hold, 0, n - 1)]
    y = (1 - a.mix) * xd + a.mix * wet

    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
    sf.write(a.output, y[:, 0] if y.shape[1] == 1 else y, sr)
    # self-check: quantisation error energy
    err = 20 * np.log10(np.sqrt(np.mean((y - xd) ** 2)) + 1e-12)
    print(f"bitcrush: {a.bits} bits /{a.downsample} downsample mix {a.mix:g} | "
          f"added noise/error {err:.1f} dBFS -> {a.output}")


if __name__ == "__main__":
    main()
