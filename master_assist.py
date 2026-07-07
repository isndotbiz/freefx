#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy", "pyloudnorm"]
# ///
"""
master_assist — open-source command-line mastering assistant (analyze + render two masters).

An Ozone-style assistant built entirely from public DSP and the other `freefx`
tools. ANALYZE the mix first (integrated + short-term LUFS, sample/true peak,
crest factor, spectral tilt, stereo width), choose conservative corrective
moves from the numbers — and print WHY each move was chosen — then render two
masters: `soundcloud` (~-9 LUFS, dense and clipped-forward) and `spotify`
(-14 LUFS, dynamics preserved, limiter only). Both are true-peak safe at
-1 dBTP. Loudness is measured with pyloudnorm, the limiter gain is computed
from the measurement, and every render is RE-measured afterwards (one
correction pass if off by >0.7 LU) so the printed numbers are real, never
assumed. Clean-room. MIT. Part of `freefx`.

Usage:
  uv run master_assist.py mix.wav master.wav                        # both profiles
  uv run master_assist.py mix.wav master.wav --profile soundcloud   # one profile
  uv run master_assist.py mix.wav --analyze                         # analysis only, no render
  uv run master_assist.py mix.wav master.wav --dry-run              # print the plan, render nothing
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
import pyloudnorm as pyln
from scipy.signal import resample_poly, welch, butter, sosfilt

HERE = Path(__file__).resolve().parent

PROFILES = {
    "soundcloud": dict(target=-9.0, ceiling=-1.0, window=(-10.5, -8.0),
                       blurb="SoundCloud-loud: dense, clipped-forward, ~-9 LUFS"),
    "spotify":    dict(target=-14.0, ceiling=-1.0, window=(-15.0, -13.0),
                       blurb="Spotify-dynamic: -14 LUFS, dynamics preserved, limiter only"),
}

# spectral-tilt neutral window (dB/octave of the 40 Hz..16 kHz log-log fit);
# full mixes typically sit around -4..-6 dB/oct, so only nudge outside this.
TILT_DARK = -7.5
TILT_BRIGHT = -3.5


# ---------------- measurement (pyloudnorm + textbook estimates) ----------------

def true_peak_db(x, sr, oversample=4):
    """dBTP estimate: 4x oversample (resample_poly) then take the sample max."""
    xo = resample_poly(x, oversample, 1, axis=0)
    return 20 * np.log10(np.max(np.abs(xo)) + 1e-12)


def short_term_max(x, sr, meter):
    """Max loudness over sliding 3 s windows, 1 s hop (short-term approximation)."""
    win, hop = int(3.0 * sr), int(1.0 * sr)
    if x.shape[0] <= win:
        return meter.integrated_loudness(x)
    vals = [meter.integrated_loudness(x[s:s + win])
            for s in range(0, x.shape[0] - win + 1, hop)]
    vals = [v for v in vals if np.isfinite(v)]
    return max(vals) if vals else float("-inf")


def spectral_tilt(x, sr):
    """dB/octave slope of the average spectrum (Welch), log-log fit 40 Hz..16 kHz."""
    mono = x.mean(axis=1) if x.ndim > 1 else x
    f, p = welch(mono, sr, nperseg=min(8192, mono.shape[0]))
    m = (f >= 40) & (f <= min(16000, sr / 2 - 1)) & (p > 0)
    return float(np.polyfit(np.log2(f[m]), 10 * np.log10(p[m] + 1e-20), 1)[0])


def analyze(x, sr):
    meter = pyln.Meter(sr)
    xd = x.astype(np.float64)
    rms = float(np.sqrt(np.mean(xd ** 2)) + 1e-12)
    peak_db = 20 * np.log10(np.max(np.abs(xd)) + 1e-12)
    m = dict(
        lufs=meter.integrated_loudness(xd),
        st_max=short_term_max(xd, sr, meter),
        peak_db=peak_db,
        tp_db=true_peak_db(xd, sr),
        crest=peak_db - 20 * np.log10(rms),
        tilt=spectral_tilt(xd, sr),
        width=None, lowcorr=None,
    )
    if xd.ndim > 1 and xd.shape[1] == 2:
        L, R = xd[:, 0], xd[:, 1]
        mid, side = (L + R) / 2, (L - R) / 2
        m["width"] = float(np.sqrt(np.mean(side ** 2)) / (np.sqrt(np.mean(mid ** 2)) + 1e-12))
        sos = butter(4, 120 / (sr / 2), btype="low", output="sos")
        m["lowcorr"] = float(np.corrcoef(sosfilt(sos, L), sosfilt(sos, R))[0, 1])
    return m


def print_analysis(path, m):
    print(f"master_assist: analysis of {path}")
    print(f"  integrated       {m['lufs']:6.1f} LUFS")
    print(f"  short-term max   {m['st_max']:6.1f} LUFS  (3 s windows, 1 s hop)")
    print(f"  sample peak      {m['peak_db']:6.1f} dBFS")
    print(f"  true peak        {m['tp_db']:6.1f} dBTP  (4x oversampled estimate)")
    print(f"  crest factor     {m['crest']:6.1f} dB")
    print(f"  spectral tilt    {m['tilt']:6.1f} dB/oct (40 Hz-16 kHz log-log fit)")
    if m["width"] is not None:
        mono = "yes" if m["lowcorr"] > 0.9 else "NO"
        print(f"  stereo width     {m['width']:6.2f} side/mid RMS")
        print(f"  mono <120 Hz     {mono:>6}  (L/R correlation {m['lowcorr']:.2f} below 120 Hz)")
    else:
        print("  stereo width        n/a  (mono file)")


# ---------------- planning (conservative, transparent) ----------------

def plan_steps(m, profile):
    """Return (pre-limit steps, why-lines). Every move states its reason."""
    whys, bands = [], ["hpf:24::0.707"]
    whys.append("high-pass 24 Hz — clears sub-rumble so the limiter isn't eating inaudible energy (always on)")
    if m["tilt"] < TILT_DARK:
        bands.append("highshelf:10000:1.5:0.7")
        whys.append(f"tilt {m['tilt']:.1f} dB/oct (dark, < {TILT_DARK:g}) -> +1.5 dB high shelf @ 10 kHz")
    elif m["tilt"] > TILT_BRIGHT:
        bands.append("highshelf:10000:-1.5:0.7")
        whys.append(f"tilt {m['tilt']:.1f} dB/oct (bright, > {TILT_BRIGHT:g}) -> -1.5 dB high shelf @ 10 kHz")
    else:
        whys.append(f"tilt {m['tilt']:.1f} dB/oct inside neutral window [{TILT_DARK:g}..{TILT_BRIGHT:g}] -> no tonal shelf")

    steps = [("eq", tuple(a for b in bands for a in ("--band", b)))]
    if profile == "soundcloud":
        whys.append("gentle 3-band glue (2:1 @ -18) — evens the low end without dulling the highs")
        steps.append(("mbcomp", ("--xover", "200", "2500", "--threshold", "-18",
                                 "--ratio", "2", "--attack-ms", "15", "--release-ms", "150")))
        whys.append("tape saturation (drive 3, mix 0.5) — harmonic density so loud reads full, not just loud")
        steps.append(("sat", ("--drive", "3", "--tone-hz", "14000", "--mix", "0.5")))
        drive = 4.0 if m["crest"] >= 14.0 else 2.5
        whys.append(f"crest {m['crest']:.1f} dB -> soft clipper drive {drive:g} dB @ -0.8 — shaves transients so the limiter works less")
        steps.append(("clipper", ("--drive", f"{drive:g}", "--ceiling", "-0.8")))
    else:
        whys.append("dynamics-first: no compressor / saturation / clipper — corrective EQ then a true-peak limiter only")
    return steps, whys


# ---------------- rendering (subprocess into the other freefx tools) ----------------

def run_tool(name, in_path, out_path, args, dry_run):
    cmd = ["uv", "run", str(HERE / f"{name}.py"), str(in_path), str(out_path), *args]
    print("  $ " + " ".join(cmd), flush=True)
    if not dry_run:
        subprocess.run(cmd, cwd=HERE, check=True)


def render_profile(profile, in_path, out_path, m, dry_run, keep_temp):
    p = PROFILES[profile]
    target, ceiling = p["target"], p["ceiling"]
    steps, whys = plan_steps(m, profile)
    print(f"\nmaster_assist [{profile}]: {p['blurb']} (target {target:g} LUFS, ceiling {ceiling:g} dBTP)")
    for w in whys:
        print(f"  - {w}")

    tmpdir = Path(tempfile.mkdtemp(prefix=f"master-assist-{profile}-"))
    try:
        current = in_path
        for i, (tool, args) in enumerate(steps, start=1):
            nxt = tmpdir / f"{i:02d}-{tool}.wav"
            run_tool(tool, current, nxt, args, dry_run)
            current = nxt

        if dry_run:
            print(f"  $ uv run {HERE / 'tplimit.py'} {current} {out_path} "
                  f"--gain {{{target:g} - pre-limit LUFS, measured at render}} --ceiling {ceiling:g}")
            print(f"master_assist [{profile}]: dry run — nothing rendered")
            return

        # measure the pre-limit chain output, compute the limiter drive from it
        x, sr = sf.read(current)
        meter = pyln.Meter(sr)
        pre = meter.integrated_loudness(x.astype(np.float64))
        gain = target - pre
        print(f"  pre-limit: {pre:.1f} LUFS -> limiter gain {gain:+.1f} dB")
        run_tool("tplimit", current, out_path, ("--gain", f"{gain:.2f}", "--ceiling", f"{ceiling:g}"), False)

        # RE-measure; the limiter eats some loudness at loud targets — one correction pass
        y, sr2 = sf.read(out_path)
        got = pyln.Meter(sr2).integrated_loudness(y.astype(np.float64))
        if abs(got - target) > 0.7:
            gain += target - got
            print(f"  achieved {got:.1f} LUFS is >0.7 LU off target -> retry with gain {gain:+.1f} dB")
            run_tool("tplimit", current, out_path, ("--gain", f"{gain:.2f}", "--ceiling", f"{ceiling:g}"), False)
            y, sr2 = sf.read(out_path)
            got = pyln.Meter(sr2).integrated_loudness(y.astype(np.float64))
        tp = true_peak_db(y.astype(np.float64), sr2)

        lo, hi = p["window"]
        flag = "ok" if (lo <= got <= hi and tp <= ceiling + 0.1) else "NOTE: outside window"
        print(f"master_assist [{profile}]: measured {got:.1f} LUFS (window {lo:g}..{hi:g}), "
              f"true peak {tp:.2f} dBTP (ceiling {ceiling:g}) [{flag}] -> {out_path}")
    finally:
        if keep_temp and not dry_run:
            print(f"  kept temp renders: {tmpdir}")
        else:
            shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="master_assist — mastering assistant (freefx, MIT)")
    ap.add_argument("input")
    ap.add_argument("output", nargs="?",
                    help="base path; renders <stem>-soundcloud.wav / <stem>-spotify.wav next to it")
    ap.add_argument("--profile", choices=["soundcloud", "spotify", "both"], default="both")
    ap.add_argument("--analyze", action="store_true", help="analysis only, skip rendering")
    ap.add_argument("--dry-run", action="store_true", help="print the planned steps without rendering")
    ap.add_argument("--keep-temp", action="store_true", help="keep intermediate chain renders")
    a = ap.parse_args()

    in_path = Path(a.input).expanduser()
    if not in_path.exists():
        sys.exit(f"input not found: {in_path}")
    x, sr = sf.read(in_path)
    m = analyze(x, sr)
    print_analysis(in_path, m)
    if a.analyze:
        return

    if not a.output:
        sys.exit("output base path required unless --analyze is used")
    base = Path(a.output).expanduser()
    profiles = ["soundcloud", "spotify"] if a.profile == "both" else [a.profile]
    for profile in profiles:
        out = base.with_name(f"{base.stem}-{profile}.wav")
        render_profile(profile, in_path, out, m, a.dry_run, a.keep_temp)


if __name__ == "__main__":
    main()
