#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# ///
"""Render repeatable freefx effect chains from presets or plain-language hints.

Examples:
  uv run chain.py vocal.wav vocal-polished.wav --preset vocal-modern --key A --scale minor
  uv run chain.py mix.wav master.wav --describe "loud warm trap master with clipper and limiter"
  uv run chain.py vocal.wav wet.wav --describe "hard tune, de-ess, add air, compress, reverb"
  uv run chain.py in.wav out.wav --preset lofi --dry-run
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Step:
    name: str
    args: tuple[str, ...] = ()


PRESETS: dict[str, list[Step]] = {
    "vocal-natural-tune": [
        Step("pitchpin", ("--strength", "0.75")),
        Step("deesser", ("--freq", "6500", "--threshold", "-30")),
        Step("comp", ("--threshold", "-20", "--ratio", "3", "--attack-ms", "5", "--release-ms", "120", "--makeup", "auto")),
        Step("eq", ("--band", "hpf:80::0.707", "--band", "peak:300:-2:0.9", "--band", "highshelf:10000:1.5:0.7")),
        Step("tplimit", ("--ceiling", "-1")),
    ],
    "vocal-clean": [
        Step("gate", ("--threshold", "-50", "--range", "30")),
        Step("deesser", ("--freq", "6500", "--threshold", "-30")),
        Step("comp", ("--threshold", "-20", "--ratio", "3", "--attack-ms", "5", "--release-ms", "120", "--makeup", "auto")),
        Step("eq", ("--band", "hpf:80::0.707", "--band", "peak:300:-2:0.9", "--band", "highshelf:10000:1.5:0.7")),
        Step("tplimit", ("--ceiling", "-1")),
    ],
    "vocal-modern": [
        Step("autotune", ("--retune-ms", "25", "--strength", "0.85")),
        Step("deesser", ("--freq", "6500", "--threshold", "-30")),
        Step("rider", ("--target-db", "-18", "--max-gain-db", "6")),
        Step("comp", ("--threshold", "-20", "--ratio", "4", "--attack-ms", "4", "--release-ms", "100", "--makeup", "auto")),
        Step("sat", ("--drive", "4", "--tone-hz", "12000", "--mix", "0.6")),
        Step("exciter", ("--freq", "5500", "--amount", "3")),
        Step("doubler", ("--voices", "2", "--detune", "8", "--mix", "0.18")),
        Step("verb", ("--roomsize", "0.65", "--damp", "0.45", "--wet", "0.16", "--predelay-ms", "20", "--tail-sec", "1.2")),
        Step("tplimit", ("--ceiling", "-1")),
    ],
    "vocal-hard-tune": [
        Step("autotune", ("--retune-ms", "0", "--strength", "1")),
        Step("deesser", ("--freq", "6500", "--threshold", "-31")),
        Step("comp", ("--threshold", "-22", "--ratio", "5", "--attack-ms", "3", "--release-ms", "90", "--makeup", "auto")),
        Step("sat", ("--drive", "5", "--tone-hz", "11000", "--mix", "0.7")),
        Step("exciter", ("--freq", "6000", "--amount", "4")),
        Step("tplimit", ("--ceiling", "-1")),
    ],
    "master-loud": [
        Step("eq", ("--band", "hpf:28::0.707", "--band", "highshelf:12000:1:0.7")),
        Step("mbcomp", ("--xover", "200", "2500", "--ratio", "2.2")),
        Step("sat", ("--drive", "3", "--tone-hz", "14000", "--mix", "0.5")),
        Step("clipper", ("--drive", "2.5", "--ceiling", "-1")),
        Step("tplimit", ("--ceiling", "-1")),
    ],
    "trap-loud": [
        Step("transient", ("--attack", "3", "--sustain", "-1")),
        Step("sat", ("--drive", "5", "--tone-hz", "12000", "--mix", "0.7")),
        Step("clipper", ("--drive", "4", "--ceiling", "-0.8")),
        Step("tplimit", ("--ceiling", "-1")),
    ],
    "lofi": [
        Step("texture", ("--crackle", "0.25", "--hiss", "0.12", "--wow", "0.08")),
        Step("bitcrush", ("--bits", "10", "--downsample", "2", "--mix", "0.25")),
        Step("sat", ("--drive", "6", "--tone-hz", "8500", "--flutter", "4", "--mix", "0.75")),
        Step("eq", ("--band", "hpf:45::0.707", "--band", "lpf:14500::0.707")),
        Step("tplimit", ("--ceiling", "-1.2")),
    ],
    "space": [
        Step("delay", ("--time-ms", "375", "--feedback", "0.32", "--mix", "0.22", "--pingpong")),
        Step("chorus", ("--voices", "3", "--rate", "0.45", "--depth", "3", "--mix", "0.18")),
        Step("verb", ("--roomsize", "0.82", "--damp", "0.35", "--wet", "0.28", "--predelay-ms", "35", "--tail-sec", "2")),
        Step("width", ("--width", "1.25", "--mono-hz", "120")),
        Step("tplimit", ("--ceiling", "-1")),
    ],
    "vocal-crisp": [
        Step("rider", ("--target-db", "-18", "--max-gain-db", "6")),
        Step("deesser", ("--freq", "6800", "--threshold", "-30")),
        Step("comp", ("--threshold", "-20", "--ratio", "3", "--attack-ms", "5", "--release-ms", "110", "--makeup", "auto")),
        Step("eq", ("--band", "hpf:90::0.707", "--band", "peak:250:-2:1.0", "--band", "highshelf:11000:2.5:0.7")),
        Step("exciter", ("--freq", "6500", "--amount", "4")),
        Step("tplimit", ("--ceiling", "-1")),
    ],
    "vocal-juice": [
        Step("autotune", ("--retune-ms", "30", "--strength", "0.92")),
        Step("formant", ("--formant", "-1.5",)),
        Step("deesser", ("--freq", "6500", "--threshold", "-30")),
        Step("rider", ("--target-db", "-18", "--max-gain-db", "6")),
        Step("comp", ("--threshold", "-20", "--ratio", "4", "--attack-ms", "4", "--release-ms", "100", "--makeup", "auto")),
        Step("sat", ("--drive", "4", "--tone-hz", "12000", "--mix", "0.6")),
        Step("doubler", ("--voices", "2", "--detune", "8", "--mix", "0.15")),
        Step("delay", ("--note", "1/4", "--feedback", "0.35", "--mix", "0.22", "--pingpong", "--duck", "0.7")),
        Step("verb", ("--roomsize", "0.75", "--damp", "0.4", "--wet", "0.18", "--predelay-ms", "25", "--tail-sec", "1.6")),
        Step("tplimit", ("--ceiling", "-1")),
    ],
    "master-soundcloud": [
        Step("eq", ("--band", "hpf:28::0.707")),
        Step("mbcomp", ("--xover", "200", "2500", "--ratio", "2.2")),
        Step("sat", ("--drive", "3", "--tone-hz", "14000", "--mix", "0.5")),
        Step("clipper", ("--drive", "3", "--ceiling", "-0.8")),
        Step("tplimit", ("--target-lufs", "-9", "--ceiling", "-1")),
    ],
    "master-spotify": [
        Step("eq", ("--band", "hpf:28::0.707")),
        Step("mbcomp", ("--xover", "200", "2500", "--ratio", "1.8")),
        Step("tplimit", ("--target-lufs", "-14", "--ceiling", "-1")),
    ],
    "retro-vocal": [
        Step("deesser", ("--freq", "6500", "--threshold", "-30")),
        Step("comp", ("--threshold", "-20", "--ratio", "3", "--attack-ms", "5", "--release-ms", "120", "--makeup", "auto")),
        Step("retro", ("--age", "0.45", "--wobble", "0.15", "--dropout", "0", "--mix", "0.85")),
        Step("tplimit", ("--ceiling", "-1")),
    ],
    "stutter-hook": [
        Step("timefx", ("--mode", "stutter", "--grid", "1/16", "--pattern", "x---x---")),
        Step("tplimit", ("--ceiling", "-1")),
    ],
}


CANONICAL_ORDER = [
    "gate", "pitchpin", "autotune", "formant", "deesser", "rider", "eq", "dyneq",
    "comp", "mbcomp", "transient", "sat", "exciter", "bitcrush", "texture", "retro",
    "doubler", "chorus", "flanger", "phaser", "tremolo", "timefx", "delay", "verb",
    "width", "clipper", "tplimit",
]


DESCRIBE_STEPS: dict[str, Step] = {
    "gate": Step("gate", ("--threshold", "-50", "--range", "30")),
    "pitchpin": Step("pitchpin", ("--strength", "0.75")),
    "autotune": Step("autotune", ("--retune-ms", "20", "--strength", "0.9")),
    "hard_tune": Step("autotune", ("--retune-ms", "0", "--strength", "1")),
    "deess": Step("deesser", ("--freq", "6500", "--threshold", "-30")),
    "air": Step("exciter", ("--freq", "6000", "--amount", "4")),
    "compress": Step("comp", ("--threshold", "-20", "--ratio", "4", "--attack-ms", "5", "--release-ms", "110", "--makeup", "auto")),
    "warm": Step("sat", ("--drive", "5", "--tone-hz", "11500", "--mix", "0.65")),
    "clip": Step("clipper", ("--drive", "3.5", "--ceiling", "-1")),
    "limit": Step("tplimit", ("--ceiling", "-1")),
    "reverb": Step("verb", ("--roomsize", "0.72", "--damp", "0.42", "--wet", "0.2", "--predelay-ms", "25", "--tail-sec", "1.5")),
    "delay": Step("delay", ("--time-ms", "375", "--feedback", "0.3", "--mix", "0.2", "--pingpong")),
    "wide": Step("width", ("--width", "1.35", "--mono-hz", "120")),
    "double": Step("doubler", ("--voices", "2", "--detune", "10", "--mix", "0.22")),
    "lofi": Step("texture", ("--crackle", "0.25", "--hiss", "0.12", "--wow", "0.08")),
    "rider": Step("rider", ("--target-db", "-18", "--max-gain-db", "6")),
    "retro": Step("retro", ("--age", "0.5",)),
    "stutter": Step("timefx", ("--mode", "stutter", "--grid", "1/16", "--pattern", "x---x---")),
    "tapestop": Step("timefx", ("--mode", "tapestop",)),
    "halftime": Step("timefx", ("--mode", "halftime",)),
    "deep_voice": Step("formant", ("--formant", "-2",)),
}


def chain_from_description(text: str) -> list[Step]:
    lower = text.lower()
    steps: list[Step] = []

    def add(key: str) -> None:
        step = DESCRIBE_STEPS[key]
        steps[:] = [s for s in steps if s.name != step.name]
        steps.append(step)

    if any(w in lower for w in ("vocal", "voice", "rap", "sing")):
        steps.extend(PRESETS["vocal-clean"][:-1])
    elif any(w in lower for w in ("master", "mix", "loud", "808", "trap")):
        steps.extend(PRESETS["master-loud"][:-1])

    if any(w in lower for w in ("natural tune", "transparent tune", "pitch correct", "pitch-correct", "fix pitch")):
        add("pitchpin")
    elif "hard tune" in lower or "robot" in lower or "t-pain" in lower or "tpain" in lower:
        add("hard_tune")
    elif any(w in lower for w in ("tune", "autotune", "pitch correct", "pitch-correct")):
        add("autotune")
    if any(w in lower for w in ("de-ess", "deess", "sibilance", "harsh s")):
        add("deess")
    if any(w in lower for w in ("air", "bright", "sparkle", "crisp")):
        add("air")
    if any(w in lower for w in ("compress", "level", "even out", "controlled")):
        add("compress")
    if any(w in lower for w in ("warm", "tape", "saturation", "analog", "grit")):
        add("warm")
    if any(w in lower for w in ("clip", "clipped", "aggressive", "trap loud")):
        add("clip")
    if any(w in lower for w in ("limit", "loud", "master")):
        add("limit")
    if any(w in lower for w in ("reverb", "room", "space", "wet")):
        add("reverb")
    if any(w in lower for w in ("delay", "echo", "throw", "ping pong", "ping-pong")):
        add("delay")
    if any(w in lower for w in ("wide", "stereo", "widen")):
        add("wide")
    if any(w in lower for w in ("double", "doubler", "adt", "thick")):
        add("double")
    if any(w in lower for w in ("lofi", "lo-fi", "vinyl", "dusty")):
        add("lofi")
    if any(w in lower for w in ("rider", "ride the", "consistent volume", "even volume", "level the vocal")):
        add("rider")
    if any(w in lower for w in ("retro", "vintage", "cassette", "aged", "old tape", "worn")):
        add("retro")
    if "stutter" in lower:
        add("stutter")
    if any(w in lower for w in ("tape stop", "tape-stop", "tapestop")):
        add("tapestop")
    if any(w in lower for w in ("halftime", "half-time", "half time", "half speed")):
        add("halftime")
    if any(w in lower for w in ("deep voice", "deeper voice", "darker voice", "formant")):
        add("deep_voice")

    if not steps:
        steps = list(PRESETS["vocal-clean"])
    elif not any(s.name == "tplimit" for s in steps):
        steps.append(DESCRIBE_STEPS["limit"])

    return sort_steps(steps)


def sort_steps(steps: list[Step]) -> list[Step]:
    order = {name: i for i, name in enumerate(CANONICAL_ORDER)}
    dedup: dict[str, Step] = {}
    for step in steps:
        dedup[step.name] = step
    return sorted(dedup.values(), key=lambda s: order.get(s.name, 999))


def with_bpm(step: Step, bpm: float | None) -> Step:
    if not bpm:
        return step
    args = list(step.args)
    if step.name == "timefx" and "--bpm" not in args:
        args.extend(["--bpm", f"{bpm:g}"])
    elif step.name == "delay" and "--bpm" not in args and "--time-ms" not in args:
        args.extend(["--bpm", f"{bpm:g}"])
    else:
        return step
    return Step(step.name, tuple(args))


def with_key_scale(step: Step, key: str | None, scale: str | None) -> Step:
    if step.name not in {"autotune", "harmonizer", "pitchpin"}:
        return step
    args = list(step.args)
    if key and "--key" not in args:
        args.extend(["--key", key])
    if scale and "--scale" not in args:
        args.extend(["--scale", scale])
    return Step(step.name, tuple(args))


def script_path(step: Step) -> Path:
    if step.name == "pitchpin":
        return HERE.parent / "pitchpin" / "pitchpin.py"
    return HERE / f"{step.name}.py"


def render_chain(in_path: Path, out_path: Path, steps: list[Step], *, dry_run: bool, keep_temp: bool) -> None:
    if not dry_run and not in_path.exists():
        raise SystemExit(f"input not found: {in_path}")
    tmpdir = Path(tempfile.mkdtemp(prefix="freefx-chain-"))
    try:
        current = in_path
        print("freefx chain:", flush=True)
        for idx, step in enumerate(steps, start=1):
            target = out_path if idx == len(steps) else tmpdir / f"{idx:02d}-{step.name}.wav"
            cmd = ["uv", "run", str(script_path(step)), str(current), str(target), *step.args]
            print("  " + " ".join(cmd), flush=True)
            if not dry_run:
                subprocess.run(cmd, cwd=HERE, check=True)
            current = target
    finally:
        if dry_run:
            shutil.rmtree(tmpdir, ignore_errors=True)
        elif keep_temp:
            print(f"kept temp renders: {tmpdir}")
        else:
            shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?")
    parser.add_argument("output", nargs="?")
    parser.add_argument("--preset", choices=sorted(PRESETS), help="named chain to render")
    parser.add_argument("--describe", help="plain-language sound description")
    parser.add_argument("--key", help="musical key for pitch effects, e.g. A, C#, Eb")
    parser.add_argument("--scale", default="minor", help="scale for pitch effects")
    parser.add_argument("--bpm", type=float, help="tempo for timefx / tempo-synced delay steps")
    parser.add_argument("--list-presets", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args()

    if args.list_presets:
        for name, steps in PRESETS.items():
            print(f"{name}: " + " -> ".join(s.name for s in steps))
        return 0

    if not args.input or not args.output:
        parser.error("input and output are required unless --list-presets is used")

    if args.describe:
        steps = chain_from_description(args.describe)
    else:
        steps = list(PRESETS[args.preset or "vocal-clean"])
    steps = [with_key_scale(step, args.key, args.scale) for step in steps]
    steps = [with_bpm(step, args.bpm) for step in steps]

    render_chain(Path(args.input).expanduser(), Path(args.output).expanduser(), steps, dry_run=args.dry_run, keep_temp=args.keep_temp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
