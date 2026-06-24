#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2", "scipy", "pedalboard", "pyworld", "setuptools<80"]
# ///
# MIT License. Part of the `freefx` open-source effects suite.
"""
match — black-box behavioral matching: tune a freefx module's parameters to MATCH
the *acoustic behavior* of a proprietary plugin, by measuring input -> output only.

This is the LEGAL, clean-room alternative to decompilation. We feed test signals
through the proprietary plugin (via pedalboard) and MEASURE its audio output, then
search the freefx module's own parameter space to minimise the difference between
the two outputs. We never read the plugin binary, never extract its code, presets,
or coefficients. Measuring acoustic output is exactly how Airwindows and every
legitimate clone works; touching the binary is what we deliberately do NOT do.

Pipeline per match:
  1. build a battery of probe signals (log sweep, impulse, white noise, dyn step)
     plus an optional real audio clip
  2. render every probe through BOTH the proprietary plugin (pedalboard) and the
     freefx module (subprocess `uv run <module>.py` with candidate params)
  3. search the freefx params to MINIMISE the null residual (gain+time-aligned RMS
     difference, reused from ab.py) plus an optional spectral-tilt term
  4. report the best params, achieved null residual + tilt/LUFS deltas, before/after

Search = coarse grid -> local Nelder-Mead refine (scipy) on the continuous params.
During search we use a short clip and downsampled probes for speed; the final
evaluation re-renders on the full probe battery.

Usage:
  uv run match.py eq      --vst "TDR Nova"                # NOVA single bell -> eq
  uv run match.py dyneq   --vst "TDR Nova"                # NOVA dynamic de-ess -> dyneq
  uv run match.py autotune --vst "Graillon 3"            # Graillon A-minor -> autotune
  uv run match.py verb    --vst "Supermassive"           # Valhalla reverb -> verb (approx)
  uv run match.py all                                     # run every pair, write all reports

Each pair has a built-in proprietary-plugin configuration (the "target" we match).
Override the report dir with --outdir (default ./matches).
"""
import argparse
import os
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf

# Reuse the measurement primitives from the A/B harness — do NOT reimplement them.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ab  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 44100

VOCAL = os.path.expanduser("~/Desktop/dbf-tuned-2026-06-20/dbf_tuned_4_vocal.wav")
MIX = os.path.expanduser("~/Desktop/dope-boy-fresh-2026-06-20/dope_boy_fresh_v1.flac")


# ----------------------------------------------------------------------------- #
# Probe signals — these characterise a plugin's behaviour better than music,
# because they excite the whole frequency / dynamic range with known content.
# ----------------------------------------------------------------------------- #
def probe_signals(sr=SR, dur=3.0):
    """Return a dict name -> mono float32 array of clean characterisation probes."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    probes = {}

    # Log sine sweep 20 Hz -> 20 kHz: reveals the full magnitude/phase response.
    f0, f1 = 20.0, 20000.0
    k = np.log(f1 / f0)
    sweep = np.sin(2 * np.pi * f0 * dur / k * (np.exp(t / dur * k) - 1.0))
    win = np.ones(n)
    r = int(0.01 * sr)
    win[:r] = np.linspace(0, 1, r)
    win[-r:] = np.linspace(1, 0, r)
    probes["sweep"] = (0.5 * sweep * win).astype(np.float32)

    # Dirac-ish impulse train (a few spaced impulses): the impulse response.
    imp = np.zeros(n, dtype=np.float32)
    for s in range(int(0.1 * sr), n, int(0.5 * sr)):
        imp[s] = 0.9
    probes["impulse"] = imp

    # White noise: broadband steady-state — great for static EQ / spectral matching.
    rng = np.random.default_rng(1234)
    probes["noise"] = (0.2 * rng.standard_normal(n)).astype(np.float32)

    # Loud/quiet dynamics step: exposes threshold / ratio / attack / release.
    step = np.zeros(n, dtype=np.float32)
    seg = n // 6
    levels = [0.05, 0.6, 0.05, 0.9, 0.2, 0.7]
    tone = np.sin(2 * np.pi * 1000.0 * t)  # 1 kHz carrier, amplitude-stepped
    for i, lv in enumerate(levels):
        a0, b0 = i * seg, min((i + 1) * seg, n)
        step[a0:b0] = lv * tone[a0:b0]
    probes["dynstep"] = step

    return probes


def write_probe_wavs(probes, d, sr=SR):
    paths = {}
    for name, sig in probes.items():
        p = os.path.join(d, f"probe_{name}.wav")
        sf.write(p, sig, sr)
        paths[name] = p
    return paths


# ----------------------------------------------------------------------------- #
# Proprietary-plugin rendering (pedalboard). MEASUREMENT ONLY — we set documented
# automation parameters and read the audio it produces. No binary inspection.
# ----------------------------------------------------------------------------- #
def render_vst(plugin_path, params, in_path, out_path):
    from pedalboard import load_plugin

    plug = load_plugin(plugin_path)
    for k, v in params.items():
        try:
            setattr(plug, k, v)
        except Exception as e:  # noqa: BLE001
            print(f"     ! could not set {k}={v}: {e}", file=sys.stderr)
    x, sr = sf.read(in_path, always_2d=True)
    y = plug(x.T.astype(np.float32), sr).T
    sf.write(out_path, y, sr)
    return out_path


def render_freefx(module, args, in_path, out_path):
    """Run a freefx module as a subprocess: `uv run <module>.py in out <args...>`."""
    cmd = ["uv", "run", os.path.join(HERE, f"{module}.py"), in_path, out_path] + args
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    if r.returncode != 0:
        raise RuntimeError(f"{module} failed: {r.stderr.strip()[:400]}")
    return out_path


# ----------------------------------------------------------------------------- #
# Cost: mean null residual across probes, plus a small spectral-tilt penalty so the
# optimiser also matches broad spectral balance (helps reverbs that won't null).
# ----------------------------------------------------------------------------- #
def f0_contour(sig, sr):
    """Median-of-frames F0 contour (Hz) of voiced frames, via the WORLD harvester.
    Used for pitch matching, where a waveform null is meaningless (a pitch shift
    decorrelates the wave entirely) but the F0 contour is the true behaviour."""
    import pyworld as pw

    x = np.ascontiguousarray(sig.astype(np.float64))
    f0, t = pw.harvest(x, sr)
    return f0, t


def pitch_cost(ref_path, cand_path):
    """Compare two pitch-corrected renders by their F0 contours, frame-aligned.
    Returns (cost, median_abs_cents_diff). Cost is the median absolute cents
    difference between the two contours over commonly-voiced frames — a small
    number means the two engines snapped the pitch to the same notes, regardless
    of waveform phase."""
    ref, sr = sf.read(ref_path)
    cand, _ = sf.read(cand_path)
    refm = ref.mean(axis=1) if ref.ndim > 1 else ref
    candm = cand.mean(axis=1) if cand.ndim > 1 else cand
    n = min(len(refm), len(candm))
    f0r, _ = f0_contour(refm[:n], sr)
    f0c, _ = f0_contour(candm[:n], sr)
    m = min(len(f0r), len(f0c))
    f0r, f0c = f0r[:m], f0c[:m]
    voiced = (f0r > 0) & (f0c > 0)
    if voiced.sum() < 10:
        return 1e3, float("nan")
    cents = 1200.0 * np.abs(np.log2(f0c[voiced] / f0r[voiced]))
    med = float(np.median(cents))
    return med, med


def pair_cost(ref_path, cand_path, tilt_weight=0.0):
    ref, _ = sf.read(ref_path)
    cand, sr = sf.read(cand_path)
    refm = ref.mean(axis=1) if ref.ndim > 1 else ref
    candm = cand.mean(axis=1) if cand.ndim > 1 else cand
    null = ab.null_residual_db(refm, candm)
    if tilt_weight > 0.0:
        dt = abs(ab.spectral_tilt_db(refm, sr) - ab.spectral_tilt_db(candm, sr))
        return null + tilt_weight * dt, null
    return null, null


def battery_cost(target_outputs, build_args, module, probe_paths, work, tilt_weight,
                 metric="null"):
    """Render the freefx candidate on every probe, return mean cost over the battery.

    metric="null"  -> gain/time-aligned waveform RMS difference (EQ/dyneq/verb).
    metric="pitch" -> median absolute F0 cents difference (autotune): the waveform
                      null is meaningless under pitch shift, so we compare the F0
                      contours the two engines produce instead. The reported
                      "score" is in cents (lower = closer pitch behaviour)."""
    nulls, costs = [], []
    for name, ppath in probe_paths.items():
        cand = os.path.join(work, f"cand_{module}_{name}.wav")
        render_freefx(module, build_args, ppath, cand)
        if metric == "pitch":
            c, nl = pitch_cost(target_outputs[name], cand)
        else:
            c, nl = pair_cost(target_outputs[name], cand, tilt_weight)
        costs.append(c)
        nulls.append(nl)
    return float(np.mean(costs)), float(np.mean(nulls))


# ----------------------------------------------------------------------------- #
# Per-pair definitions. Each returns:
#   target_params  : the proprietary plugin's documented automation settings
#   x0, bounds     : the freefx continuous search vector + box bounds
#   to_args(vec)   : map a search vector to freefx CLI args
#   describe(vec)  : human-readable converged params
#   search_probes  : which probes drive the search (a subset = faster + on-target)
#   tilt_weight    : spectral-tilt penalty weight
# ----------------------------------------------------------------------------- #
def pair_eq_nova():
    # Target: a single −4 dB bell at 300 Hz, Q 1.0 on TDR Nova. auto-gain OFF and
    # dry_mix 0 so the plugin output is the pure filtered signal (a fair null target).
    target = {
        "eq_auto_gain": False, "dry_mix": 0.0, "output_gain_db": 0.0,
        "band_1_active": True, "band_1_type": "Bell", "band_1_dyn": "Off",
        "band_1_frequency_hz": 300.0, "band_1_gain_db": -4.0, "band_1_q": 1.0,
        "band_2_active": False, "band_3_active": False, "band_4_active": False,
        "hp_active": False, "lp_active": False,
    }
    # freefx eq vector: [freq_hz, gain_db, Q]
    x0 = np.array([300.0, -4.0, 1.0])
    bounds = [(120.0, 700.0), (-12.0, 0.0), (0.3, 3.0)]

    def to_args(v):
        f, g, q = v
        return ["--band", f"peak:{f:.2f}:{g:.3f}:{q:.4f}"]

    def describe(v):
        f, g, q = v
        return f"eq --band peak:{f:.1f}:{g:.2f}:{q:.3f}"

    return dict(module="eq", vst="TDR Nova", target=target, x0=x0, bounds=bounds,
                to_args=to_args, describe=describe,
                search_probes=["sweep", "noise"], tilt_weight=0.0,
                note="Static bell vs static biquad — should null very deeply (correctness check).")


def pair_dyneq_nova():
    # Target: NOVA dynamic de-ess. Band 4 as a dynamic Bell at 7 kHz, downward
    # (cut on loud), threshold −30 dB, ratio 4, fast attack / medium release.
    target = {
        "eq_auto_gain": False, "dry_mix": 0.0, "output_gain_db": 0.0,
        "band_1_active": False, "band_2_active": False, "band_3_active": False,
        "band_4_active": True, "band_4_type": "Bell", "band_4_dyn": "On",
        "band_4_frequency_hz": 7000.0, "band_4_gain_db": 0.0, "band_4_q": 2.0,
        "band_4_threshold_db": -30.0, "band_4_ratio": 4.0,
        "band_4_attack_ms": 3.0, "band_4_release_ms": 120.0,
        "hp_active": False, "lp_active": False,
    }
    # freefx dyneq vector: [thresh_db, ratio, attack_ms, release_ms]; freq/Q fixed to target.
    x0 = np.array([-30.0, 4.0, 3.0, 120.0])
    bounds = [(-45.0, -10.0), (1.5, 8.0), (0.5, 20.0), (30.0, 300.0)]
    F0, Q = 7000.0, 2.0

    def to_args(v):
        thr, ratio, atk, rel = v
        return ["--band", f"{F0:.0f}:{Q:.2f}:{thr:.2f}:{ratio:.3f}:cut",
                "--attack-ms", f"{atk:.2f}", "--release-ms", f"{rel:.2f}",
                "--range-db", "18"]

    def describe(v):
        thr, ratio, atk, rel = v
        return (f"dyneq --band {F0:.0f}:{Q:.1f}:{thr:.1f}:{ratio:.2f}:cut "
                f"--attack-ms {atk:.1f} --release-ms {rel:.1f}")

    return dict(module="dyneq", vst="TDR Nova", target=target, x0=x0, bounds=bounds,
                to_args=to_args, describe=describe,
                search_probes=["dynstep", "sweep"], tilt_weight=0.3,
                note="Dynamic band — topology differs (NOVA split vs parallel-bandpass), "
                     "expect a moderate null. Drive search with the dynamics-step probe.")


def pair_autotune_graillon():
    # Target: Graillon 3 in A-minor (allow A B C D E F G, sharps off), full correction.
    allow = {
        "allow_a": True, "allow_b": True, "allow_c": True, "allow_d": True,
        "allow_e": True, "allow_f": True, "allow_g": True,
        "allow_a_sharp": False, "allow_c_sharp": False, "allow_d_sharp": False,
        "allow_f_sharp": False, "allow_g_sharp": False,
    }
    target = {
        "correction": True, "corr_amount": 100.0, "formant": False,
        "formant_amount": 100.0, "pitch_shift_st": 0.0, "formant_shift_st": 0.0,
        "reference_hz": 440.0, "wet_mix_db": 0.0, "dry_mix_db": -np.inf,
        "chorus": False, "preamp": False, **allow,
    }
    # freefx autotune is monophonic WORLD-based; pitch CLASS set is fixed to A-minor
    # to match Graillon's allow-mask. The tunable continuous knobs are retune-ms
    # (glide) and strength (how hard it snaps). We search those two.
    x0 = np.array([8.0, 1.0])
    bounds = [(0.0, 60.0), (0.5, 1.0)]

    def to_args(v):
        retune, strength = v
        return ["--key", "A", "--scale", "minor",
                "--retune-ms", f"{retune:.2f}", "--strength", f"{strength:.3f}"]

    def describe(v):
        retune, strength = v
        return f"autotune --key A --scale minor --retune-ms {retune:.1f} --strength {strength:.3f}"

    return dict(module="autotune", vst="Auburn Sounds Graillon 3", target=target,
                x0=x0, bounds=bounds, to_args=to_args, describe=describe,
                # Pitch matching needs real voiced material, not synthetic probes.
                search_probes=None, real_clip=VOCAL, clip_seconds=8.0,
                tilt_weight=0.0, metric="pitch",
                note="Pitch correction — different engines (WORLD vocoder vs Graillon's "
                     "proprietary PSOLA-class shifter). A waveform null is MEANINGLESS here: "
                     "any pitch shift fully decorrelates the wave (even Graillon-vs-its-own-"
                     "input nulls at 0 dB). So this pair is scored by F0-contour agreement in "
                     "cents — how closely the two engines snap pitch to the same A-minor notes. "
                     "Vocal stem only.")


def pair_verb_valhalla():
    # Target: Valhalla Supermassive, a clear reverb wash. Gemini mode, ~50% mix,
    # medium feedback (decay), gentle modulation.
    target = {
        "mode": "Gemini", "mix": 40.0, "feedback": 55.0, "density": 80.0,
        "delay_ms": 20.0, "delaywarp": 0.0, "moddepth": 30.0, "modrate": 0.5,
        "width": 100.0, "lowcut": 20.0, "highcut": 18000.0,
    }
    # freefx verb (Freeverb) vector: [roomsize, damp, wet]. dry fixed so wet/dry ~ mix.
    x0 = np.array([0.7, 0.4, 0.35])
    bounds = [(0.3, 0.95), (0.0, 0.9), (0.1, 0.6)]

    def to_args(v):
        room, damp, wet = v
        dry = max(0.0, 1.0 - wet)
        return ["--roomsize", f"{room:.4f}", "--damp", f"{damp:.4f}",
                "--wet", f"{wet:.4f}", "--dry", f"{dry:.4f}",
                "--predelay-ms", "20", "--tail-sec", "0"]

    def describe(v):
        room, damp, wet = v
        return f"verb --roomsize {room:.3f} --damp {damp:.3f} --wet {wet:.3f}"

    return dict(module="verb", vst="ValhallaSupermassive", target=target,
                x0=x0, bounds=bounds, to_args=to_args, describe=describe,
                search_probes=["impulse", "noise"], tilt_weight=0.6,
                note="Reverb topologies differ fundamentally (Freeverb combs vs Valhalla's "
                     "Supermassive network). A deep null is impossible; we match decay/tilt "
                     "as best the params allow and report that honestly.")


PAIRS = {
    "eq": pair_eq_nova,
    "dyneq": pair_dyneq_nova,
    "autotune": pair_autotune_graillon,
    "verb": pair_verb_valhalla,
}


# ----------------------------------------------------------------------------- #
# Search: coarse random/grid seed -> Nelder-Mead local refine (bounded by clipping
# the simplex vertices back into the box on each evaluation).
# ----------------------------------------------------------------------------- #
def clamp(v, bounds):
    return np.array([min(max(x, lo), hi) for x, (lo, hi) in zip(v, bounds)])


def coarse_seed(spec, target_outputs, probe_paths, work, n_grid=4):
    """Evaluate a small grid (or random LHS for high-dim) and return the best vector."""
    bounds = spec["bounds"]
    dim = len(bounds)
    # Build candidate vectors: full grid if dim<=2, else random Latin-ish sample.
    cands = []
    if dim <= 2:
        axes = [np.linspace(lo, hi, n_grid) for lo, hi in bounds]
        grids = np.meshgrid(*axes, indexing="ij")
        for idx in np.ndindex(*[g.shape for g in [grids[0]]][0] if False else grids[0].shape):
            cands.append(np.array([g[idx] for g in grids]))
    else:
        rng = np.random.default_rng(7)
        n = 12
        for _ in range(n):
            cands.append(np.array([rng.uniform(lo, hi) for lo, hi in bounds]))
        cands.append(spec["x0"])  # always include the informed guess

    metric = spec.get("metric", "null")
    best_v, best_c, best_n = None, 1e9, 0.0
    for v in cands:
        try:
            c, nl = battery_cost(target_outputs, spec["to_args"](v), spec["module"],
                                 probe_paths, work, spec["tilt_weight"], metric=metric)
        except Exception as e:  # noqa: BLE001
            print(f"     ! cand {v} failed: {e}", file=sys.stderr)
            continue
        if c < best_c:
            best_v, best_c, best_n = v, c, nl
    return best_v if best_v is not None else spec["x0"], best_c, best_n


def refine(spec, seed, target_outputs, probe_paths, work, maxiter=40):
    from scipy.optimize import minimize
    bounds = spec["bounds"]
    metric = spec.get("metric", "null")
    evals = {"n": 0}

    def f(v):
        evals["n"] += 1
        vc = clamp(v, bounds)
        try:
            c, _ = battery_cost(target_outputs, spec["to_args"](vc), spec["module"],
                                probe_paths, work, spec["tilt_weight"], metric=metric)
        except Exception:  # noqa: BLE001
            return 1e6
        return c

    res = minimize(f, seed, method="Nelder-Mead",
                   options={"maxiter": maxiter, "xatol": 1e-2, "fatol": 1e-2})
    best = clamp(res.x, bounds)
    return best, evals["n"]


# ----------------------------------------------------------------------------- #
# Drive one pair end to end and write its report.
# ----------------------------------------------------------------------------- #
def run_pair(name, outdir, quick=False):
    spec = PAIRS[name]()
    module, vst = spec["module"], spec["vst"]
    plugin_path = ab.find_vst3(vst)
    print(f"\n=== match {module}  ->  {os.path.basename(plugin_path)} ===")
    print(f"    {spec['note']}")

    with tempfile.TemporaryDirectory() as work:
        # --- build the probe set the SEARCH uses ---
        if spec.get("search_probes") is None:
            # real-clip-driven (pitch): use a short slice of the vocal as the only probe
            clip = os.path.join(work, "clip.wav")
            x, sr = sf.read(spec["real_clip"], always_2d=True)
            x = x.mean(axis=1)
            secs = spec.get("clip_seconds", 8.0)
            x = x[: int(secs * sr)]
            sf.write(clip, x, sr)
            search_paths = {"clip": clip}
            full_probe_paths = dict(search_paths)
        else:
            dur = 1.5 if quick else 3.0
            probes = probe_signals(dur=dur)
            full_probe_paths = write_probe_wavs(probes, work)
            search_paths = {k: full_probe_paths[k] for k in spec["search_probes"]}

        # --- render the TARGET (proprietary plugin) once per probe ---
        target_outputs = {}
        for nm, ppath in full_probe_paths.items():
            tp = os.path.join(work, f"target_{nm}.wav")
            render_vst(plugin_path, spec["target"], ppath, tp)
            target_outputs[nm] = tp

        # --- coarse seed on the search probes, then local refine ---
        print("    coarse seed ...")
        seed, seed_cost, seed_null = coarse_seed(spec, target_outputs, search_paths, work)
        print(f"      seed cost={seed_cost:+.2f}  null={seed_null:+.2f} dB  -> {seed}")
        print("    refine (Nelder-Mead) ...")
        maxiter = 20 if quick else 40
        best, nevals = refine(spec, seed, target_outputs, search_paths, work, maxiter=maxiter)

        metric = spec.get("metric", "null")

        # --- final evaluation on the FULL probe battery ---
        final_args = spec["to_args"](best)
        final_cost, final_score = battery_cost(target_outputs, final_args, module,
                                               full_probe_paths, work, spec["tilt_weight"],
                                               metric=metric)

        # --- per-probe breakdown for the report table ---
        rows = []
        for nm, ppath in full_probe_paths.items():
            cand = os.path.join(work, f"final_{nm}.wav")
            render_freefx(module, final_args, ppath, cand)
            tref, srr = sf.read(target_outputs[nm])
            tcand, _ = sf.read(cand)
            tm = tref.mean(axis=1) if tref.ndim > 1 else tref
            cm = tcand.mean(axis=1) if tcand.ndim > 1 else tcand
            if metric == "pitch":
                _, cents = pitch_cost(target_outputs[nm], cand)
                # for pitch we report cents-diff in the "null" column slot
                d_tilt = ab.spectral_tilt_db(cm, srr) - ab.spectral_tilt_db(tm, srr)
                rows.append((nm, cents, d_tilt, float("nan")))
            else:
                nl = ab.null_residual_db(tm, cm)
                d_tilt = ab.spectral_tilt_db(cm, srr) - ab.spectral_tilt_db(tm, srr)
                d_lufs = ab.measure_lufs(cand) - ab.measure_lufs(target_outputs[nm])
                rows.append((nm, nl, d_tilt, d_lufs))

        report = write_report(name, spec, plugin_path, best, final_score, rows,
                              seed_null, nevals, outdir)
        unit = "cents" if metric == "pitch" else "dB null"
        print(f"    converged: {spec['describe'](best)}")
        print(f"    score = {final_score:+.1f} {unit}   report -> {report}")
        return name, spec, best, final_score, rows, report


def write_report(name, spec, plugin_path, best, final_score, rows, seed_null, nevals, outdir):
    os.makedirs(outdir, exist_ok=True)
    plug = os.path.splitext(os.path.basename(plugin_path))[0]
    path = os.path.join(outdir, f"{spec['module']}-vs-{plug.replace(' ', '_')}.md")
    metric = spec.get("metric", "null")

    if metric == "pitch":
        # score is median absolute cents difference between the two F0 contours.
        if final_score <= 15:
            verdict = "**Good** — both engines snap pitch to essentially the same notes."
        elif final_score <= 40:
            verdict = "**Approximate** — same scale, comparable correction, frame timing differs."
        else:
            verdict = "**Loose** — only broad pitch-class agreement."
        result_line = (f"- **Median F0 agreement: {final_score:.1f} cents** "
                       f"(0 = identical pitch; a waveform null is meaningless under pitch shift).")
        tbl_header = "| probe | F0 diff (cents) | Δ tilt (dB) |\n|-------|-----------------|-------------|"
        tbl = "\n".join(f"| {nm} | {nl:.1f} | {dt:+.2f} |" for nm, nl, dt, _dl in rows)
        tbl_note = ("*F0 diff = median absolute cents difference between the two engines' "
                    "pitch contours. Δ tilt = freefx minus proprietary spectral balance.*")
    else:
        if final_score <= -40:
            verdict = "**Excellent** — deep null, behaviourally near-identical."
        elif final_score <= -18:
            verdict = "**Good** — close behavioural match; audible character preserved."
        elif final_score <= -8:
            verdict = "**Approximate** — same family of effect, topologies differ; broad match only."
        else:
            verdict = "**Loose** — fundamentally different topology; only coarse spectral/decay match."
        result_line = (f"- **Mean null residual: {final_score:+.1f} dB** "
                       f"(lower = closer; 0 dB = unrelated).\n"
                       f"- Coarse-seed null was {seed_null:+.1f} dB; Nelder-Mead used {nevals} evaluations.")
        tbl_header = "| probe | null (dB) | Δ tilt (dB) | Δ LUFS (dB) |\n|-------|-----------|-------------|-------------|"
        tbl = "\n".join(f"| {nm} | {nl:+.1f} | {dt:+.2f} | {dl:+.2f} |" for nm, nl, dt, dl in rows)
        tbl_note = ("*Δ tilt / Δ LUFS = freefx output minus proprietary output. Near-zero = "
                    "matched spectral balance and loudness.*")

    tgt_lines = "\n".join(f"  - `{k}` = `{v}`" for k, v in spec["target"].items())
    with open(path, "w") as f:
        f.write(f"""# Behavioural match: freefx `{spec['module']}` vs `{plug}`

> **Method: black-box behavioural matching (legal, clean-room).** Probe signals are
> rendered through the proprietary plugin and the freefx module; only the *audio
> output* of the proprietary plugin is measured. Its binary, code, presets, and
> coefficients are never read, decompiled, or extracted. This is the lawful way
> clones are built (cf. Airwindows). See `matches/README.md`.

## Target (proprietary plugin configuration)
Plugin: `{os.path.basename(plugin_path)}` — documented automation parameters set via pedalboard:
{tgt_lines}

## Converged freefx parameters
```
uv run {spec['describe'](best)}
```

## Result
{result_line}
- Verdict: {verdict}

{spec['note']}

### Per-probe breakdown
{tbl_header}
{tbl}

{tbl_note}
""")
    return path


def write_readme(outdir):
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "README.md")
    with open(path, "w") as f:
        f.write("""# freefx behavioural matches

These reports are produced by `match.py`. Each tunes a freefx module's parameters
to **match the acoustic behaviour** of a proprietary plugin.

## The method is black-box behavioural matching (legal, clean-room)

We send test signals (a log sine sweep, an impulse, white noise, a loud/quiet
dynamics step, and a short real clip) through **both**:

1. the proprietary plugin (loaded with `pedalboard`, set to documented automation
   parameters), and
2. the open-source freefx module (`eq.py`, `dyneq.py`, `autotune.py`, `verb.py`).

We then **measure only the audio the proprietary plugin produces** and search the
freefx module's own parameter space (coarse grid → Nelder-Mead refine) to minimise
the gain- and time-aligned RMS difference (the "null residual") between the two
outputs, plus a small spectral-tilt term.

**What we never do:** decompile, disassemble, read the plugin binary, or extract
its code, coefficients, or presets. Measuring acoustic input→output is legal and is
exactly how Airwindows and other legitimate clones are built. Touching the binary is
what we deliberately avoid.

## What "close" means

- **EQ vs a static bell** nulls very deeply (tens of dB) — a biquad *is* the same
  math, so this is also our correctness check that the loop works.
- **Dynamic EQ / reverb / pitch** use *different topologies* from the proprietary
  plugin, so they will NOT null deeply. We report the honest residual and treat
  these as "same family of effect, approximated", never as exact clones.

## Run it

```bash
uv run match.py eq        # NOVA single bell  -> eq
uv run match.py dyneq     # NOVA dynamic de-ess -> dyneq
uv run match.py autotune  # Graillon A-minor  -> autotune (vocal stem)
uv run match.py verb      # Valhalla reverb   -> verb (approximate)
uv run match.py all       # every pair, all reports
```

Add `--quick` for a faster, lower-resolution search. Reports land in this folder
as `<module>-vs-<plugin>.md`.
""")
    return path


def main():
    ap = argparse.ArgumentParser(description="match — black-box behavioural matching (freefx, MIT)")
    ap.add_argument("pair", choices=list(PAIRS) + ["all"], help="which freefx<->plugin pair")
    ap.add_argument("--vst", default=None, help="(informational) override plugin name; pairs are preconfigured")
    ap.add_argument("--outdir", default=os.path.join(HERE, "matches"))
    ap.add_argument("--quick", action="store_true", help="faster, lower-resolution search")
    a = ap.parse_args()

    write_readme(a.outdir)
    names = list(PAIRS) if a.pair == "all" else [a.pair]
    summary = []
    for nm in names:
        try:
            _, spec, best, final_null, _, report = run_pair(nm, a.outdir, quick=a.quick)
            summary.append((nm, spec["describe"](best), final_null, report))
        except Exception as e:  # noqa: BLE001
            print(f"  !! pair {nm} failed: {e}", file=sys.stderr)
            summary.append((nm, f"FAILED: {e}", float("nan"), ""))

    print("\n=========== SUMMARY ===========")
    for nm, desc, score, _ in summary:
        unit = "cents" if (nm in PAIRS and PAIRS[nm]().get("metric") == "pitch") else "dB null"
        print(f"  {nm:9s} {score:+7.1f} {unit:8s}  {desc}")


if __name__ == "__main__":
    main()
