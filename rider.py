#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy", "numba"]
# ///
"""
rider — open-source vocal gain rider.

Short-term RMS leveling for vocal stems before compression: slow, smooth fader
gain in dB, not dynamic-range compression. Detection is a mono, K-ish weighted
sidechain; the audio path stays clean. Clean-room. MIT. Part of `freefx`.

Usage:
  uv run rider.py vox.wav out.wav --target-db -18 --window-ms 400 --max-gain-db 6
  uv run rider.py vox.wav out.wav --floor-db -55 --write-automation rider.csv
"""
import argparse, csv
import numpy as np
import soundfile as sf
from numba import njit
from scipy.signal import butter, sosfilt


@njit(cache=True)
def _smooth_gain_db(target_db, atk_c, rel_c):
    n = target_db.shape[0]
    g = np.empty(n, dtype=np.float64)
    cur = 0.0
    for i in range(n):
        target = target_db[i]
        c = atk_c if target < cur else rel_c
        cur = c * cur + (1.0 - c) * target
        g[i] = cur
    return g


def coef(ms, fs):
    return float(np.exp(-1.0 / (fs * ms / 1000.0))) if ms > 0 else 0.0


def _high_shelf_sos(fs, hz=4000.0, gain_db=4.0, q=0.707):
    hz = min(max(hz, 1.0), fs * 0.5 - 1.0)
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * hz / fs
    cw = np.cos(w0)
    sw = np.sin(w0)
    alpha = sw / (2.0 * q)
    root_a = np.sqrt(a)
    b0 = a * ((a + 1.0) + (a - 1.0) * cw + 2.0 * root_a * alpha)
    b1 = -2.0 * a * ((a - 1.0) + (a + 1.0) * cw)
    b2 = a * ((a + 1.0) + (a - 1.0) * cw - 2.0 * root_a * alpha)
    a0 = (a + 1.0) - (a - 1.0) * cw + 2.0 * root_a * alpha
    a1 = 2.0 * ((a - 1.0) - (a + 1.0) * cw)
    a2 = (a + 1.0) - (a - 1.0) * cw - 2.0 * root_a * alpha
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]], dtype=np.float64)


def _detection_signal(x, sr):
    det = np.mean(x, axis=1)
    nyq = sr * 0.5
    if nyq > 100.0:
        sos = butter(2, min(80.0, nyq - 1.0) / nyq, btype="high", output="sos")
        det = sosfilt(sos, det)
    if nyq > 1000.0:
        det = sosfilt(_high_shelf_sos(sr, min(4000.0, nyq - 1.0), 4.0), det)
    return det


def _rms_frames_db(det, sr, window_ms):
    n = det.shape[0]
    hop = max(1, int(sr * 0.010))
    win = max(1, int(sr * max(window_ms, 1e-3) / 1000.0))
    frames = np.arange(0, n, hop, dtype=np.int64)
    sq = det * det
    cs = np.concatenate(([0.0], np.cumsum(sq, dtype=np.float64)))
    db = np.empty(frames.shape[0], dtype=np.float64)
    half = win // 2
    for i, c in enumerate(frames):
        start = max(0, int(c) - half)
        end = min(n, start + win)
        start = max(0, end - win)
        count = max(1, end - start)
        rms = np.sqrt((cs[end] - cs[start]) / count)
        db[i] = 20.0 * np.log10(rms + 1e-12)
    return frames, db


def _target_frames_db(measured_db, target_db, floor_db, max_gain_db):
    out = np.empty_like(measured_db)
    cur = 0.0
    limit = abs(max_gain_db)
    for i, db in enumerate(measured_db):
        if db >= floor_db:
            cur = min(max(target_db - db, -limit), limit)
        out[i] = cur
    return out


def _shift_earlier(gain_db, lookahead_samples):
    n = gain_db.shape[0]
    if lookahead_samples <= 0 or n == 0:
        return gain_db
    shift = min(lookahead_samples, n)
    out = np.empty_like(gain_db)
    out[:n - shift] = gain_db[shift:]
    out[n - shift:] = gain_db[-1]
    return out


def _write_automation(path, gain_db, sr):
    hop = max(1, int(sr * 0.010))
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_sec", "gain_db"])
        for i in range(0, gain_db.shape[0], hop):
            w.writerow([f"{i / sr:.6f}", f"{gain_db[i]:.6f}"])


def main():
    ap = argparse.ArgumentParser(description="rider — vocal gain rider (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--target-db", type=float, default=-18.0, help="target short-window RMS in dBFS")
    ap.add_argument("--window-ms", type=float, default=400.0, help="short-term RMS analysis window")
    ap.add_argument("--max-gain-db", type=float, default=6.0, help="clamp boost/cut to +/- this dB")
    ap.add_argument("--attack-ms", type=float, default=150.0, help="gain-down smoothing time")
    ap.add_argument("--release-ms", type=float, default=400.0, help="gain-up smoothing time")
    ap.add_argument("--lookahead-ms", type=float, default=0.0, help="shift gain earlier by this many ms")
    ap.add_argument("--write-automation", type=str, default=None, help="write CSV time_sec,gain_db")
    ap.add_argument("--floor-db", type=float, default=-55.0, help="hold gain below this dBFS")
    a = ap.parse_args()

    x, sr = sf.read(a.input, always_2d=True)
    xd = x.astype(np.float64)
    n = xd.shape[0]
    if n == 0:
        y = xd
        gain_db = np.zeros(0, dtype=np.float64)
    else:
        det = _detection_signal(xd, sr)
        frames, measured_db = _rms_frames_db(det, sr, a.window_ms)
        target_frames = _target_frames_db(measured_db, a.target_db, a.floor_db, a.max_gain_db)
        target_db = np.interp(np.arange(n, dtype=np.float64), frames.astype(np.float64), target_frames)
        atk_c, rel_c = coef(a.attack_ms, sr), coef(a.release_ms, sr)
        gain_db = _smooth_gain_db(np.ascontiguousarray(target_db), atk_c, rel_c)
        lookahead = max(0, int(sr * a.lookahead_ms / 1000.0))
        gain_db = _shift_earlier(gain_db, lookahead)
        y = xd * (10.0 ** (gain_db / 20.0))[:, None]

    if a.write_automation:
        _write_automation(a.write_automation, gain_db, sr)

    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y[:, 0] if y.shape[1] == 1 else y, sr)

    gmin = float(np.min(gain_db)) if gain_db.size else 0.0
    gmax = float(np.max(gain_db)) if gain_db.size else 0.0
    print(f"rider: target {a.target_db:.1f} dB window {a.window_ms:g}ms max +/-{abs(a.max_gain_db):.1f} dB "
          f"atk {a.attack_ms:g} rel {a.release_ms:g} | gain {gmin:+.1f}..{gmax:+.1f} dB -> {a.output}")


if __name__ == "__main__":
    main()
