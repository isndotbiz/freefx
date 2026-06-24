#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy"]
# ///
"""
irverb — open-source convolution reverb (real spaces / plate IRs).

Convolves the input with an impulse response, so it takes on the exact acoustics
captured in that IR — a real room, a hardware plate, a cathedral. Different from
`verb` (algorithmic): this reproduces a *measured* space. Provide an IR wav with
--ir, or use --synth-ir to generate a decaying-noise plate to try it. Clean-room
(FFT convolution). MIT. Part of `freefx`.

Usage:
  uv run irverb.py vox.wav out.wav --ir plate.wav --mix 0.25 --predelay-ms 20
  uv run irverb.py vox.wav out.wav --synth-ir 2.0 --mix 0.3            # synthetic 2s plate
"""
import argparse
import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve, butter, sosfilt


def synth_ir(seconds, sr):
    n = int(seconds * sr)
    rng = np.random.default_rng(0)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / (sr * seconds / 5.0))
    ir = sosfilt(butter(2, 8000 / (sr / 2), btype="low", output="sos"), ir)   # plate-ish HF damping
    return ir / (np.max(np.abs(ir)) + 1e-9)


def main():
    ap = argparse.ArgumentParser(description="irverb — convolution reverb (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--ir", default=None, help="impulse response wav")
    ap.add_argument("--synth-ir", type=float, default=0.0, help="generate a synthetic IR of N seconds")
    ap.add_argument("--mix", type=float, default=0.25, help="0=dry .. 1=wet only")
    ap.add_argument("--predelay-ms", type=float, default=0.0)
    a = ap.parse_args()

    x, sr = sf.read(a.input, always_2d=True)
    xd = x.astype(np.float64)
    if a.ir:
        ir, isr = sf.read(a.ir)
        ir = ir.mean(axis=1) if ir.ndim > 1 else ir
        ir = ir.astype(np.float64)
    elif a.synth_ir > 0:
        ir = synth_ir(a.synth_ir, sr)
    else:
        raise SystemExit("give --ir <file> or --synth-ir <seconds>")
    if a.predelay_ms > 0:
        ir = np.concatenate([np.zeros(int(sr * a.predelay_ms / 1000.0)), ir])

    wet = np.stack([fftconvolve(xd[:, c], ir)[: len(xd)] for c in range(xd.shape[1])], axis=1)
    wet /= (np.max(np.abs(wet)) + 1e-9)
    wet *= np.max(np.abs(xd)) + 1e-9                       # level-match wet to dry
    y = (1 - a.mix) * xd + a.mix * wet

    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y[:, 0] if y.shape[1] == 1 else y, sr)
    print(f"irverb: ir={a.ir or f'synth {a.synth_ir}s'} mix {a.mix:g} predelay {a.predelay_ms:g}ms | "
          f"IR len {len(ir)/sr:.2f}s -> {a.output}")


if __name__ == "__main__":
    main()
