#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy", "numba"]
# ///
"""
comp — open-source full-band compressor (with de-esser mode).

A standard feed-forward compressor: soft-knee static curve, attack/release
envelope, makeup gain, stereo-linked detection (one gain on both channels so the
image stays put). Add `--sidechain-hpf` to listen above a frequency and it
becomes a de-esser / vocal-rider that only clamps on bright, loud sibilance.

Clean-room textbook DSP (peak/RMS detector + soft-knee gain computer). MIT.
Part of the `freefx` suite — pairs with `dyneq` (per-band) and `tplimit` (peaks).

Usage:
  uv run comp.py vox.wav out.wav --threshold -18 --ratio 4 --attack-ms 5 --release-ms 120 --makeup auto
  uv run comp.py drums.wav out.wav --threshold -12 --ratio 6 --knee 4 --rms
  uv run comp.py vox.wav out.wav --threshold -26 --ratio 5 --sidechain-hpf 5500   # de-ess
"""
import argparse, sys
import numpy as np
import soundfile as sf
from numba import njit
from scipy.signal import butter, sosfilt


@njit(cache=True)
def _compress(det, thr_db, ratio, knee_db, atk_c, rel_c, rms_c):
    """Soft-knee compressor gain trajectory (linear) from a detection signal.

    det    : linked detection signal (already side-chain filtered if asked)
    rms_c  : if >0, square-law RMS smoothing coefficient; else peak detection
    returns per-sample linear gain to multiply the (unfiltered) signal by.
    """
    n = det.shape[0]
    g = np.empty(n, dtype=np.float64)
    env = 1e-9
    ms = 1e-12
    slope = 1.0 / ratio - 1.0          # negative
    half_knee = knee_db * 0.5
    cur = 1.0
    for i in range(n):
        rect = abs(det[i])
        if rms_c > 0.0:
            ms = rms_c * ms + (1.0 - rms_c) * rect * rect
            level = np.sqrt(ms)
        else:
            coef = atk_c if rect > env else rel_c
            env = coef * env + (1.0 - coef) * rect
            level = env
        level_db = 20.0 * np.log10(level + 1e-12)
        over = level_db - thr_db
        # soft knee around the threshold
        if knee_db > 0.0 and -half_knee <= over <= half_knee:
            gr_db = slope * (over + half_knee) ** 2 / (2.0 * knee_db)
        elif over > 0.0:
            gr_db = slope * over
        else:
            gr_db = 0.0
        target = 10.0 ** (gr_db / 20.0)
        # smooth the gain itself: attack when clamping harder, release when easing
        coef = atk_c if target < cur else rel_c
        cur = coef * cur + (1.0 - coef) * target
        g[i] = cur
    return g


def coef(ms, fs):
    return float(np.exp(-1.0 / (fs * ms / 1000.0))) if ms > 0 else 0.0


def main():
    ap = argparse.ArgumentParser(description="comp — full-band compressor / de-esser (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--threshold", type=float, default=-18.0, help="dBFS")
    ap.add_argument("--ratio", type=float, default=4.0)
    ap.add_argument("--knee", type=float, default=6.0, help="soft-knee width dB (0 = hard)")
    ap.add_argument("--attack-ms", type=float, default=5.0)
    ap.add_argument("--release-ms", type=float, default=120.0)
    ap.add_argument("--rms", action="store_true", help="RMS detection (smoother) instead of peak")
    ap.add_argument("--rms-ms", type=float, default=10.0, help="RMS window when --rms")
    ap.add_argument("--makeup", default="0", help="dB, or 'auto' to offset the threshold-implied loss")
    ap.add_argument("--sidechain-hpf", type=float, default=0.0, help="detect only above this Hz (de-ess)")
    a = ap.parse_args()
    if a.ratio < 1.0:
        sys.exit("ratio must be >= 1")

    x, sr = sf.read(a.input, always_2d=True)
    xd = x.astype(np.float64)
    det = np.max(np.abs(xd), axis=1)                     # stereo-linked detection
    if a.sidechain_hpf > 0:
        sos = butter(2, a.sidechain_hpf / (sr / 2), btype="high", output="sos")
        det = np.abs(sosfilt(sos, det))

    atk_c, rel_c = coef(a.attack_ms, sr), coef(a.release_ms, sr)
    rms_c = coef(a.rms_ms, sr) if a.rms else 0.0
    g = _compress(np.ascontiguousarray(det), a.threshold, a.ratio, a.knee,
                  atk_c, rel_c, rms_c)

    if a.makeup == "auto":
        makeup_db = -20.0 * np.log10(np.median(g[g < 0.999]) + 1e-12) if np.any(g < 0.999) else 0.0
    else:
        makeup_db = float(a.makeup)
    y = xd * g[:, None] * (10.0 ** (makeup_db / 20.0))

    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y[:, 0] if y.shape[1] == 1 else y, sr)

    g_db = 20.0 * np.log10(g + 1e-12)
    mode = f"de-ess>{a.sidechain_hpf:.0f}Hz" if a.sidechain_hpf > 0 else ("rms" if a.rms else "peak")
    print(f"comp ({mode}): thr {a.threshold:+.0f} ratio {a.ratio:g}:1 knee {a.knee:g} | "
          f"gain reduction {g_db.min():.1f}..{g_db.max():.1f} dB | makeup {makeup_db:+.1f} dB -> {a.output}")


if __name__ == "__main__":
    main()
