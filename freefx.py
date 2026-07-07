#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# ///
"""freefx command-line suite.

One entry point for the clean-room freefx tools and the sibling pitchpin tuner.

Examples:
  uv run freefx.py list
  uv run freefx.py chain vocal.wav out.wav --preset vocal-modern --key A
  uv run freefx.py describe vocal.wav out.wav "hard tune, de-ess, add air, compress"
  uv run freefx.py run eq in.wav out.wav -- --band hpf:80::0.707
  uv run freefx.py master mix.wav master.wav --profile both
  uv run freefx.py plugins
  uv run freefx.py verify-vst3
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
PITCHPIN = HERE.parent / "pitchpin" / "pitchpin.py"

TOOLS = [
    "autotune", "bitcrush", "chorus", "clipper", "comp", "deesser", "delay",
    "doubler", "duck", "dyneq", "eq", "exciter", "flanger", "formant", "gate",
    "harmonizer", "irverb", "master_assist", "mbcomp", "phaser", "retro",
    "rider", "sat", "texture", "timefx", "tplimit", "transient", "tremolo",
    "verb", "vocoder", "width",
]


def run(cmd: list[str]) -> int:
    return subprocess.run(cmd, cwd=HERE).returncode


def tool_script(name: str) -> Path:
    if name == "pitchpin":
        return PITCHPIN
    return HERE / f"{name}.py"


def cmd_list(_: argparse.Namespace) -> int:
    print("freefx tools:", flush=True)
    for name in TOOLS:
        print(f"  {name}")
    print("  pitchpin  (sibling repo: transparent monophonic pitch correction)")
    print(flush=True)
    return run(["uv", "run", str(HERE / "chain.py"), "--list-presets"])


def cmd_chain(args: argparse.Namespace) -> int:
    cmd = ["uv", "run", str(HERE / "chain.py"), args.input, args.output]
    if args.preset:
        cmd += ["--preset", args.preset]
    if args.key:
        cmd += ["--key", args.key]
    if args.scale:
        cmd += ["--scale", args.scale]
    if args.bpm:
        cmd += ["--bpm", str(args.bpm)]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.keep_temp:
        cmd.append("--keep-temp")
    return run(cmd)


def cmd_describe(args: argparse.Namespace) -> int:
    cmd = ["uv", "run", str(HERE / "chain.py"), args.input, args.output, "--describe", args.description]
    if args.key:
        cmd += ["--key", args.key]
    if args.scale:
        cmd += ["--scale", args.scale]
    if args.bpm:
        cmd += ["--bpm", str(args.bpm)]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.keep_temp:
        cmd.append("--keep-temp")
    return run(cmd)


def cmd_run_tool(args: argparse.Namespace) -> int:
    script = tool_script(args.tool)
    if not script.exists():
        print(f"unknown tool or missing script: {args.tool}", file=sys.stderr)
        return 2
    tool_args = list(args.tool_args)
    if tool_args and tool_args[0] == "--":
        tool_args = tool_args[1:]
    return run(["uv", "run", str(script), args.input, args.output, *tool_args])


def cmd_master(args: argparse.Namespace) -> int:
    cmd = ["uv", "run", str(HERE / "master_assist.py"), args.input]
    if args.output:
        cmd.append(args.output)
    cmd += ["--profile", args.profile]
    if args.analyze:
        cmd.append("--analyze")
    if args.dry_run:
        cmd.append("--dry-run")
    if args.keep_temp:
        cmd.append("--keep-temp")
    return run(cmd)


def cmd_plugins(_: argparse.Namespace) -> int:
    roots = [
        Path.home() / "Library" / "Audio" / "Plug-Ins" / "VST3",
        Path("/Library/Audio/Plug-Ins/VST3"),
    ]
    seen = []
    for root in roots:
        for item in sorted(glob.glob(str(root / "freefx-*.vst3"))):
            p = Path(item)
            target = os.readlink(p) if p.is_symlink() else "real-dir"
            seen.append(p.name)
            print(f"{p.name}\t{target}")
    print(f"\n{len(seen)} freefx VST3 plugin(s) installed")
    return 0


def cmd_verify_vst3(args: argparse.Namespace) -> int:
    root = args.path or str(Path.home() / "Library" / "Audio" / "Plug-Ins" / "VST3")
    return run(["uv", "run", str(HERE / "vst3" / "verify.py"), root])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="list tools and chain presets")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("chain", help="render a named chain preset")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--preset")
    p.add_argument("--key")
    p.add_argument("--scale", default="minor")
    p.add_argument("--bpm", type=float)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--keep-temp", action="store_true")
    p.set_defaults(func=cmd_chain)

    p = sub.add_parser("describe", help="render from a plain-language description")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("description")
    p.add_argument("--key")
    p.add_argument("--scale", default="minor")
    p.add_argument("--bpm", type=float)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--keep-temp", action="store_true")
    p.set_defaults(func=cmd_describe)

    p = sub.add_parser("run", help="run one tool directly")
    p.add_argument("tool")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("tool_args", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_run_tool)

    p = sub.add_parser("master", help="analyze + render SoundCloud/Spotify masters")
    p.add_argument("input")
    p.add_argument("output", nargs="?")
    p.add_argument("--profile", choices=["soundcloud", "spotify", "both"], default="both")
    p.add_argument("--analyze", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--keep-temp", action="store_true")
    p.set_defaults(func=cmd_master)

    p = sub.add_parser("plugins", help="list installed freefx VST3 plugins")
    p.set_defaults(func=cmd_plugins)

    p = sub.add_parser("verify-vst3", help="load/process installed VST3 plugins")
    p.add_argument("path", nargs="?")
    p.set_defaults(func=cmd_verify_vst3)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
