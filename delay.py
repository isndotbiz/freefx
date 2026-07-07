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
  uv run delay.py vox.wav out.wav --bpm 160 --note 1/8d --feedback 0.5          # dotted-8 tempo throw
  uv run delay.py vox.wav out.wav --time-ms 375 --duck 0.8 --duck-release-ms 300 # delay blooms between lines
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


@njit(cache=True)
def _duckgain(L, R, duck, thr_db, atk_c, rel_c):
    n = L.shape[0]
    g = np.empty(n, dtype=np.float64)
    env = 1e-9; presence = 0.0
    for i in range(n):
        rect = max(abs(L[i]), abs(R[i]))
        env = (atk_c if rect > env else rel_c) * env + (1.0 - (atk_c if rect > env else rel_c)) * rect
        over = 20.0 * np.log10(env + 1e-12) - thr_db
        target = 1.0 if over > 0.0 else 0.0
        presence = (atk_c if target > presence else rel_c) * presence + (1.0 - (atk_c if target > presence else rel_c)) * target
        g[i] = 1.0 - duck * presence
    return g


def coef(ms, fs):
    return float(np.exp(-1.0 / (fs * ms / 1000.0))) if ms > 0 else 0.0


def tempo_ms(bpm, note):
    tail = note.split("/")[1]
    suffix = tail[-1] if tail[-1] in ("d", "t") else ""
    denom = float(tail[:-1] if suffix else tail)
    whole_note_ms = (60000.0 / bpm) * 4.0
    mult = 1.5 if suffix == "d" else (2.0 / 3.0 if suffix == "t" else 1.0)
    return whole_note_ms * (1.0 / denom) * mult


def main():
    ap = argparse.ArgumentParser(description="delay — stereo/ping-pong delay (freefx, MIT)")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--time-ms", type=float, default=None)
    ap.add_argument("--bpm", type=float, default=None)
    ap.add_argument("--note", choices=["1/1", "1/2", "1/4", "1/4d", "1/4t", "1/8", "1/8d", "1/8t", "1/16", "1/16d", "1/16t", "1/32"], default="1/4")
    ap.add_argument("--feedback", type=float, default=0.4, help="0..0.95")
    ap.add_argument("--pingpong", action="store_true")
    ap.add_argument("--tone", type=float, default=0.0, help="lowpass the feedback at this Hz (0=off)")
    ap.add_argument("--mix", type=float, default=0.3, help="0=dry .. 1=wet only")
    ap.add_argument("--duck", type=float, default=0.0, help="0..1 wet ducking from dry input")
    ap.add_argument("--duck-threshold", type=float, default=-30.0)
    ap.add_argument("--duck-attack-ms", type=float, default=5.0)
    ap.add_argument("--duck-release-ms", type=float, default=250.0)
    a = ap.parse_args()
    if a.bpm is not None and a.bpm <= 0:
        ap.error("--bpm must be > 0")

    if a.time_ms is not None:
        time_ms = a.time_ms; source = "time-ms"
    elif a.bpm is not None:
        time_ms = tempo_ms(a.bpm, a.note); source = "tempo-sync (bpm/note)"
    else:
        time_ms = 375.0; source = "time-ms (default)"

    x, sr = sf.read(a.input, always_2d=True)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    xd = np.ascontiguousarray(x.astype(np.float64))
    d = int(sr * time_ms / 1000.0)
    fb = min(max(a.feedback, 0.0), 0.95)
    duck = min(max(a.duck, 0.0), 1.0)
    L_in = np.ascontiguousarray(xd[:, 0]); R_in = np.ascontiguousarray(xd[:, 1])
    if a.tone > 0:                                        # darken the input feeding the delay
        sos = butter(1, min(a.tone, sr / 2 - 1) / (sr / 2), btype="low", output="sos")
        L_in = sosfilt(sos, L_in); R_in = sosfilt(sos, R_in)
    wetL, wetR = _fbdelay(L_in, R_in, d, fb, a.pingpong)
    # the delayed component only (subtract the dry that passed straight through the recursion seed)
    wetL = wetL - L_in; wetR = wetR - R_in
    duck_msg = ""
    if duck > 0.0:
        dg = _duckgain(np.ascontiguousarray(xd[:, 0]), np.ascontiguousarray(xd[:, 1]), duck, a.duck_threshold,
                       coef(a.duck_attack_ms, sr), coef(a.duck_release_ms, sr))
        wetL = wetL * dg; wetR = wetR * dg
        duck_msg = f" duck {duck:g} min-gain {20.0*np.log10(float(np.min(dg))+1e-12):.1f}dB"
    y = np.stack([xd[:, 0] + a.mix * wetL, xd[:, 1] + a.mix * wetR], axis=1)

    peak = float(np.max(np.abs(y)))
    if peak > 0.999:
        y = y / peak * 0.999
        print(f"  (normalized -{20*np.log10(peak):.1f} dB to avoid clipping)")
    sf.write(a.output, y, sr)
    print(f"delay: {time_ms:g}ms [{source}] fb {fb:g} {'ping-pong ' if a.pingpong else ''}tone {a.tone:g} "
          f"mix {a.mix:g}{duck_msg} | {a.feedback and int(np.log(0.01)/np.log(max(fb,1e-3))) or 0} audible repeats -> {a.output}")


if __name__ == "__main__":
    main()
