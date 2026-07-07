#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2"]
# ///
"""
timefx — open-source rhythmic time effects: stutter, tape stop, half-time, gate.

Grid-locked time manipulation for the emo trap / cloud rap lane. Four generic,
well-known effects: `stutter` retriggers a slice on a step pattern, `tapestop`
ramps playback speed to zero so pitch falls with it (variable-rate resample),
`halftime` plays the region at half speed an octave down (the classic trap
sound; 2x resample), `gate` is a trance-gate pattern chop with smoothed edges.
An optional --start-s/--end-s region confines the effect; audio outside passes
through untouched (drops/hooks stay intact). Clean-room. MIT. Part of `freefx`.

Mix semantics: stutter/gate/tapestop keep the region length, so --mix blends
wet/dry sample-wise (tapestop with mix<1 leaks dry under the stop — parallel
style). halftime changes the region length, so --mix is ill-defined there and
the wet path is used fully (a note is printed if --mix < 1).

Usage:
  uv run timefx.py hook.wav out.wav --mode stutter --bpm 140 --grid 1/16 --pattern "x---x---"
  uv run timefx.py hook.wav out.wav --mode tapestop --bpm 140 --length 2 --start-s 6.85
  uv run timefx.py drums.wav out.wav --mode halftime --start-s 13.7 --end-s 27.4
  uv run timefx.py synth.wav out.wav --mode gate --bpm 140 --grid 1/8 --pattern "x-x-xx--"
"""
import argparse
import os
import shutil
import subprocess
import tempfile
import numpy as np
import soundfile as sf

GRIDS = {"1/4": 1.0, "1/8": 0.5, "1/16": 0.25, "1/32": 0.125}   # beats per step


def _edge_fades(seg, f):
    """Short linear fade-in/out on a retriggered slice to kill boundary clicks."""
    m = seg.shape[0]
    f = min(f, m // 2)
    if f > 0:
        seg[:f] *= np.linspace(0.0, 1.0, f)[:, None]
        seg[m - f:] *= np.linspace(1.0, 0.0, f)[:, None]
    return seg


def fx_stutter(dry, sr, step_n, pattern, xf_n):
    """x/1 = capture this step's slice and repeat it through following -/. steps;
    s = normal playthrough (releases the held slice)."""
    n, ch = dry.shape
    wet = dry.copy()
    held = None
    for k in range(int(np.ceil(n / step_n))):
        c = pattern[k % len(pattern)]
        a = k * step_n
        b = min(a + step_n, n)
        if c in "x1":
            held = dry[a:a + step_n].copy()
        elif c == "s":
            held = None
        if held is not None:
            seg = held[:b - a].copy()
            if seg.shape[0] < b - a:                      # held slice from the tail
                seg = np.vstack([seg, np.zeros((b - a - seg.shape[0], ch))])
            wet[a:b] = _edge_fades(seg, xf_n)
    return wet


def fx_tapestop(dry, sr, stop_n, curve):
    """Speed ramps 1 -> 0 over stop_n samples (pitch drops with it), then silence."""
    n, ch = dry.shape
    m = min(stop_n, n)
    u = np.arange(m) / max(m, 1)
    speed = (1.0 - u) if curve == "lin" else (1.0 - u) ** 2
    pos = np.concatenate(([0.0], np.cumsum(speed)))[:m]   # cumulative phase
    pos = np.minimum(pos, n - 1)
    wet = np.zeros_like(dry)
    src = np.arange(n)
    for c in range(ch):
        wet[:m, c] = np.interp(pos, src, dry[:, c])       # linear-interp resample
    return wet                                            # rest of region: silence


def fx_halftime(dry, sr, keep_pitch):
    """2x length. Default: read at 0.5 rate (pitch drops an octave — the sound).
    --keep-pitch shells out to the rubberband CLI when it's on PATH."""
    n, ch = dry.shape
    if keep_pitch:
        rb = shutil.which("rubberband")
        if rb:
            with tempfile.TemporaryDirectory() as td:
                ip, op = os.path.join(td, "i.wav"), os.path.join(td, "o.wav")
                sf.write(ip, dry, sr)
                subprocess.run([rb, "--time", "2", ip, op], check=True,
                               capture_output=True)
                wet, _ = sf.read(op, always_2d=True)
            return wet.astype(np.float64)
        print("  (rubberband not found on PATH — falling back to pitch-drop half-time)")
    pos = np.arange(2 * n) * 0.5
    pos = np.minimum(pos, n - 1)
    src = np.arange(n)
    wet = np.zeros((2 * n, ch))
    for c in range(ch):
        wet[:, c] = np.interp(pos, src, dry[:, c])
    return wet


def fx_gate(dry, sr, step_n, pattern, atk_ms, rel_ms):
    """Trance-gate: x/1 = open, anything else = closed; linear attack/release ramps."""
    n = dry.shape[0]
    tgt = np.zeros(n)
    for k in range(int(np.ceil(n / step_n))):
        if pattern[k % len(pattern)] in "x1":
            tgt[k * step_n:min((k + 1) * step_n, n)] = 1.0
    g = tgt.copy()
    atk = max(1, int(sr * atk_ms / 1000.0))
    rel = max(1, int(sr * rel_ms / 1000.0))
    edges = list(np.flatnonzero(np.diff(tgt)) + 1) + [n]
    for i, e in enumerate(edges[:-1]):
        m = min(atk if tgt[e] > tgt[e - 1] else rel, edges[i + 1] - e)
        g[e:e + m] = np.linspace(g[e - 1], tgt[e], m + 1)[1:]
        g[e + m:edges[i + 1]] = tgt[e]
    return dry * g[:, None]


def main():
    ap = argparse.ArgumentParser(description="timefx — stutter/tapestop/halftime/gate (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--mode", required=True, choices=["stutter", "tapestop", "halftime", "gate"])
    ap.add_argument("--bpm", type=float, default=140.0, help="tempo for the grid")
    ap.add_argument("--grid", choices=sorted(GRIDS), default="1/8", help="pattern step size")
    ap.add_argument("--mix", type=float, default=1.0, help="0=dry .. 1=wet (see docstring)")
    ap.add_argument("--pattern", default=None,
                    help="step pattern: x/1=trigger(open), -/.=continue(closed), s=playthrough (stutter)")
    ap.add_argument("--start-s", type=float, default=None, help="region start (default: file start)")
    ap.add_argument("--end-s", type=float, default=None, help="region end (default: file end)")
    ap.add_argument("--length", type=float, default=None, help="tapestop length in grid steps")
    ap.add_argument("--length-s", type=float, default=None, help="tapestop length in seconds (overrides --length)")
    ap.add_argument("--curve", choices=["lin", "exp"], default="exp", help="tapestop deceleration curve")
    ap.add_argument("--keep-pitch", action="store_true", help="halftime: pitch-preserving via rubberband CLI if present")
    ap.add_argument("--gate-attack-ms", type=float, default=4.0)
    ap.add_argument("--gate-release-ms", type=float, default=30.0)
    a = ap.parse_args()

    x, sr = sf.read(a.input, always_2d=True)
    xd = x.astype(np.float64)
    n = xd.shape[0]
    i0 = int(round((a.start_s or 0.0) * sr))
    i1 = int(round(a.end_s * sr)) if a.end_s is not None else n
    i0, i1 = max(0, min(i0, n)), max(0, min(i1, n))
    if i1 <= i0:
        raise SystemExit("timefx: empty region (--start-s/--end-s)")
    dry = xd[i0:i1]

    step_n = max(1, int(round(sr * 60.0 / a.bpm * GRIDS[a.grid])))
    pattern = a.pattern or "x-x-x-x-"
    if a.mode in ("stutter", "gate") and not set(pattern) <= set("x1s.-"):
        raise SystemExit(f"timefx: bad pattern chars in {pattern!r} (use x 1 s . -)")
    mix = min(max(a.mix, 0.0), 1.0)

    if a.mode == "stutter":
        wet = fx_stutter(dry, sr, step_n, pattern, int(sr * 0.004))   # ~4 ms crossfade
        region = (1.0 - mix) * dry + mix * wet
    elif a.mode == "tapestop":
        stop_s = a.length_s if a.length_s is not None else \
                 (a.length * step_n / sr if a.length is not None else 60.0 / a.bpm)
        wet = fx_tapestop(dry, sr, max(1, int(round(stop_s * sr))), a.curve)
        region = (1.0 - mix) * dry + mix * wet
    elif a.mode == "halftime":
        if mix < 1.0:
            print("  (halftime changes region length — --mix ignored, wet used fully)")
        region = fx_halftime(dry, sr, a.keep_pitch)
    else:                                                             # gate
        wet = fx_gate(dry, sr, step_n, pattern, a.gate_attack_ms, a.gate_release_ms)
        region = (1.0 - mix) * dry + mix * wet

    y = np.vstack([xd[:i0], region, xd[i1:]])
    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y[:, 0] if y.shape[1] == 1 else y, sr)
    print(f"timefx: {a.mode} bpm {a.bpm:g} grid {a.grid} mix {mix:g} "
          f"region {i0/sr:.3f}..{i1/sr:.3f}s | {y.shape[0]/sr:.3f}s out -> {a.output}")


if __name__ == "__main__":
    main()
