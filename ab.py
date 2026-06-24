#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy", "pedalboard"]
# ///
"""
ab — A/B harness for the freefx suite: render a reference through a real plugin,
then compare any set of renders by measured metrics + a null test, and emit a
blind-labelled pair to drop into a listening panel.

Two subcommands:

  vst      render a source through a VST3 plugin (pedalboard) — the "B" reference
           uv run ab.py vst src.wav ref.wav "TDR Nova"        # by installed name
           uv run ab.py vst src.wav ref.wav "/path/to/Plugin.vst3" --param Mix=0.3

  compare  measure + null-test N renders against the first one, write a blind pair
           uv run ab.py compare freefx_out.wav nova_out.wav --src dope_boy_fresh.wav --blind ./ab_out

Metrics: integrated LUFS (ffmpeg ebur128), true-peak dBTP (4x oversampled), spectral
tilt (HF/LF energy ratio in dB), and null residual vs the reference (how audibly
different two renders are). Clean-room measurement only. MIT. Part of `freefx`.
"""
import argparse, subprocess, sys, os, glob, shutil
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

VST3_DIRS = ["/Library/Audio/Plug-Ins/VST3", os.path.expanduser("~/Library/Audio/Plug-Ins/VST3")]


def find_vst3(name):
    if os.path.exists(name):
        return name
    for d in VST3_DIRS:
        for p in glob.glob(os.path.join(d, "*.vst3")):
            if name.lower() in os.path.basename(p).lower():
                return p
    sys.exit(f"VST3 '{name}' not found in {VST3_DIRS}")


def measure_lufs(path):
    r = subprocess.run(["ffmpeg", "-i", path, "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                       capture_output=True, text=True)
    vals = [l for l in r.stderr.splitlines() if "I:" in l and "LUFS" in l]
    if not vals:
        return float("nan")
    try:
        return float(vals[-1].split("I:")[1].split("LUFS")[0].strip())
    except Exception:
        return float("nan")


def true_peak_db(x, sr, os_=4):
    xo = resample_poly(x, os_, 1, axis=0)
    pk = np.max(np.abs(xo))
    return 20 * np.log10(pk + 1e-12)


def spectral_tilt_db(x, sr):
    m = x.mean(axis=1) if x.ndim > 1 else x
    X = np.abs(np.fft.rfft(m * np.hanning(len(m))))
    f = np.fft.rfftfreq(len(m), 1 / sr)
    hf = X[f > 4000].sum(); lf = X[(f > 50) & (f < 500)].sum()
    return 20 * np.log10((hf + 1e-12) / (lf + 1e-12))


def best_align(ref, cand, max_lag=2000):
    """Integer-sample offset that best aligns cand to ref (cross-correlation on a slice)."""
    a = ref[: min(len(ref), 200000)]
    b = cand[: min(len(cand), 200000)]
    n = min(len(a), len(b))
    a = a[:n] - a[:n].mean(); b = b[:n] - b[:n].mean()
    lags = range(-max_lag, max_lag + 1, 8)
    best, blag = -1e9, 0
    for L in lags:
        if L >= 0:
            c = np.dot(a[L:], b[: n - L]) if n - L > 0 else 0
        else:
            c = np.dot(a[: n + L], b[-L:]) if n + L > 0 else 0
        if c > best:
            best, blag = c, L
    return blag


def null_residual_db(ref, cand):
    """RMS of (cand - ref) relative to ref RMS, in dB. ~0 dB = totally different,
    very negative = nearly identical. Gain-normalises cand to ref first."""
    rm = ref.mean(axis=1) if ref.ndim > 1 else ref
    cm = cand.mean(axis=1) if cand.ndim > 1 else cand
    lag = best_align(rm, cm)
    if lag > 0:
        cm = cm[lag:]
    elif lag < 0:
        rm = rm[-lag:]
    n = min(len(rm), len(cm))
    rm, cm = rm[:n], cm[:n]
    g = np.dot(rm, cm) / (np.dot(cm, cm) + 1e-12)        # least-squares gain match
    diff = rm - g * cm
    return 20 * np.log10(np.sqrt(np.mean(diff ** 2) + 1e-12) /
                         (np.sqrt(np.mean(rm ** 2)) + 1e-12))


def _coerce(v):
    low = v.strip().lower()
    if low in ("on", "true", "yes"):
        return True
    if low in ("off", "false", "no"):
        return False
    try:
        return float(v)
    except ValueError:
        return v


def cmd_vst(a):
    from pedalboard import load_plugin
    path = find_vst3(a.plugin)
    plug = load_plugin(path)
    for kv in a.param:
        k, v = kv.split("=", 1)
        try:
            setattr(plug, k, _coerce(v))
        except Exception as e:
            print(f"     ! could not set {k}={v}: {e}")
    x, sr = sf.read(a.input, always_2d=True)
    y = plug(x.T.astype(np.float32), sr).T
    sf.write(a.output, y, sr)
    print(f"vst: {os.path.basename(path)} -> {a.output}  ({y.shape[0]/sr:.1f}s)")
    for kv in a.param:                                   # read back what actually took
        k = kv.split("=", 1)[0]
        try:
            print(f"     {k} = {getattr(plug, k)}")
        except Exception:
            pass


def cmd_compare(a):
    files = a.files
    print(f"{'file':28s} {'LUFS':>7s} {'dBTP':>7s} {'tilt':>7s} {'null-vs-ref':>12s}")
    ref = None
    for i, p in enumerate(files):
        x, sr = sf.read(p)
        lufs = measure_lufs(p); tp = true_peak_db(x, sr); tilt = spectral_tilt_db(x, sr)
        if i == 0:
            ref = x.mean(axis=1) if x.ndim > 1 else x
            nullv = "  (reference)"
        else:
            cm = x.mean(axis=1) if x.ndim > 1 else x
            nullv = f"{null_residual_db(ref, cm):+10.1f}dB"
        print(f"{os.path.basename(p)[:28]:28s} {lufs:7.1f} {tp:7.1f} {tilt:7.1f} {nullv:>12s}")
    if a.src:
        xs, srs = sf.read(a.src)
        print(f"\nsource: {os.path.basename(a.src)}  LUFS {measure_lufs(a.src):.1f}  "
              f"tilt {spectral_tilt_db(xs, srs):+.1f}")
    if a.blind:
        os.makedirs(a.blind, exist_ok=True)
        order = list(range(len(files)))
        order = order[1:] + order[:1]                    # deterministic rotation = "blind"
        key = []
        for slot, idx in enumerate(order, 1):
            dst = os.path.join(a.blind, f"blind_{slot}.wav")
            x, sr = sf.read(files[idx]); sf.write(dst, x, sr)
            key.append(f"blind_{slot}.wav <- {os.path.basename(files[idx])}")
        with open(os.path.join(a.blind, "BLIND_KEY.txt"), "w") as f:
            f.write("\n".join(key) + "\n")
        print(f"\nblind pair -> {a.blind}/ (key in BLIND_KEY.txt)")


def main():
    ap = argparse.ArgumentParser(description="ab — A/B harness (freefx, MIT)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("vst", help="render source through a VST3 (pedalboard)")
    v.add_argument("input"); v.add_argument("output"); v.add_argument("plugin")
    v.add_argument("--param", action="append", default=[], help="NAME=VALUE (repeatable)")
    v.set_defaults(func=cmd_vst)
    c = sub.add_parser("compare", help="measure + null-test renders, write blind pair")
    c.add_argument("files", nargs="+", help="first = reference, rest = candidates")
    c.add_argument("--src", default=None, help="original source, for context")
    c.add_argument("--blind", default=None, help="dir to write blind-labelled copies")
    c.set_defaults(func=cmd_compare)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
