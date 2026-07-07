#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2"]
# ///
"""
smoke — render-level health check for the freefx suite.

Generates synthetic WAVs in a temp dir, runs every recently added tool plus the
suite entry points, and asserts each command exits 0 and writes real audio.
No user files touched. Clean-room. MIT. Part of `freefx`.

Usage:
  uv run smoke.py            # full run (renders everything, a few minutes cold)
  uv run smoke.py --quick    # dry-run/preset checks only, no heavy renders
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
SR = 44100


def make_vocalish(path: Path, sec: float = 3.0) -> None:
    """Voiced-ish tone with alternating loud/quiet seconds (rider/comp fodder)."""
    t = np.arange(int(SR * sec)) / SR
    x = np.zeros_like(t)
    for k in range(1, 8):                       # band-limited saw at 165 Hz
        x += np.sin(2 * np.pi * 165 * k * t) / k
    x *= 0.5 + 0.5 * np.sin(2 * np.pi * 3.0 * t) ** 2   # AM, speech-ish
    env = np.where((t % 2) < 1, 10 ** (-30 / 20), 10 ** (-14 / 20))
    x = x / np.max(np.abs(x)) * env
    sf.write(path, np.stack([x, x], axis=1), SR)


def make_mix(path: Path, sec: float = 4.0) -> None:
    """Kick + noise-burst + pad pseudo-mix for master/timefx tests."""
    rng = np.random.default_rng(7)
    n = int(SR * sec)
    t = np.arange(n) / SR
    y = np.zeros(n)
    for beat in np.arange(0, sec, 60 / 140):            # 140 bpm kicks
        i = int(beat * SR)
        seg = np.arange(min(6000, n - i))
        y[i:i + len(seg)] += 0.8 * np.sin(2 * np.pi * (55 + 40 * np.exp(-seg / 800)) * seg / SR) * np.exp(-seg / 2500)
    y += 0.1 * np.sin(2 * np.pi * 220 * t) + 0.05 * rng.standard_normal(n)
    y = y / np.max(np.abs(y)) * 0.5
    sf.write(path, np.stack([y, y * 0.95], axis=1), SR)


def run(label: str, cmd: list[str], outputs: list[Path] = ()) -> bool:
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    ok = r.returncode == 0
    for out in outputs:
        if ok and (not out.exists() or out.stat().st_size < 1000):
            ok = False
    if ok:
        for out in outputs:                              # audio sanity: finite, non-silent
            data, _ = sf.read(out)
            if not np.all(np.isfinite(data)) or float(np.max(np.abs(data))) < 1e-6:
                ok = False
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print("      " + " ".join(str(c) for c in cmd))
        tail = (r.stdout + r.stderr).strip().splitlines()[-6:]
        for line in tail:
            print("      " + line)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="freefx smoke test")
    ap.add_argument("--quick", action="store_true", help="skip heavy renders")
    a = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="freefx-smoke-"))
    vox, mix = tmp / "vox.wav", tmp / "mix.wav"
    make_vocalish(vox)
    make_mix(mix)
    results = []

    def o(name: str) -> Path:
        return tmp / name

    results.append(run("freefx list", ["uv", "run", "freefx.py", "list"]))
    results.append(run("describe --dry-run",
                       ["uv", "run", "freefx.py", "describe", str(vox), str(o("x.wav")),
                        "hard tune, de-ess, retro, stutter, deep voice, level the vocal", "--dry-run", "--bpm", "150"]))
    for preset in ("vocal-crisp", "vocal-juice", "master-soundcloud", "master-spotify",
                   "retro-vocal", "stutter-hook", "vocal-modern"):
        results.append(run(f"preset {preset} --dry-run",
                           ["uv", "run", "chain.py", str(vox), str(o("x.wav")),
                            "--preset", preset, "--key", "A", "--bpm", "150", "--dry-run"]))

    if not a.quick:
        results.append(run("rider", ["uv", "run", "rider.py", str(vox), str(o("rider.wav")),
                                     "--target-db", "-18", "--write-automation", str(o("ride.csv"))], [o("rider.wav")]))
        results.append(run("delay tempo+duck", ["uv", "run", "delay.py", str(vox), str(o("dly.wav")),
                                                "--bpm", "160", "--note", "1/8d", "--duck", "0.8", "--pingpong"], [o("dly.wav")]))
        for mode, extra in (("stutter", ["--pattern", "x---x---", "--grid", "1/16"]),
                            ("tapestop", ["--length", "4"]), ("halftime", []), ("gate", [])):
            results.append(run(f"timefx {mode}", ["uv", "run", "timefx.py", str(mix), str(o(f"tf-{mode}.wav")),
                                                  "--mode", mode, "--bpm", "140", *extra], [o(f"tf-{mode}.wav")]))
        results.append(run("formant", ["uv", "run", "formant.py", str(vox), str(o("fmt.wav")),
                                       "--pitch", "-3", "--formant", "-2", "--fast"], [o("fmt.wav")]))
        results.append(run("retro", ["uv", "run", "retro.py", str(mix), str(o("retro.wav")),
                                     "--age", "0.6", "--seed", "42"], [o("retro.wav")]))
        results.append(run("master_assist both",
                           ["uv", "run", "master_assist.py", str(mix), str(o("m.wav"))],
                           [o("m-soundcloud.wav"), o("m-spotify.wav")]))

    passed, total = sum(results), len(results)
    print(f"\nsmoke: {passed}/{total} passed | artifacts: {tmp}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
