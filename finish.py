#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["soundfile", "numpy<2"]
# ///
"""finish.py -- the ENGINE-AGNOSTIC finishing stage for AI-generated songs.

The three song makers -- ACE-Step, LeVo, MiniMax -- are GENERATORS. Each takes a
lyric sheet + caption and returns a finished, mixed audio file (vocal and music
already bounced together). They do NOT host plugins. So the freefx plugins and
pitchpin are not something you wire INTO an engine; they are a POST stage that
runs on whatever ANY of the three hands back. One finishing stage, three
interchangeable sources -- that is the whole integration.

    render (ACE-Step) ┐
    songctl levo      ├─►  finish.py  ─►  mastered .wav (+ optional tuned vocal)
    minimax           ┘

WHAT IT DOES
  master (always):  freefx master chain -> streaming-target loudness.
  tune (opt-in):    stem-separate on the rig, pitchpin the ISOLATED vocal to a
                    key, remix with the instrumental, THEN master. Off by default
                    because (a) pitchpin needs a single voice, so it must run on a
                    separated stem not the mix, and (b) separation needs the rig.

USAGE
  ./finish.py song.wav --target soundcloud
  ./finish.py song.wav --target both
  ./finish.py song.wav --target spotify --tune --key A --scale minor
      (--tune needs an SSH tunnel/host to the rig's audio-separator; see --rig-host)

Works on the output of ANY engine -- it only cares that the input is an audio
file. Same command finishes an ACE-Step render, a LeVo flac, or a MiniMax wav.
"""
import argparse, os, subprocess, sys, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))


def run(cmd, **kw):
    print("  $ " + " ".join(cmd[:6]) + (" ..." if len(cmd) > 6 else ""), file=sys.stderr)
    return subprocess.run(cmd, check=True, **kw)


def master(inp, outbase, target):
    """freefx master_assist -> <outbase>-<target>.wav (SoundCloud/Spotify/both)."""
    run(["uv", "run", os.path.join(HERE, "master_assist.py"), inp, outbase, "--profile", target])


def tune_vocal(inp, key, scale, strength, rig_host, rig_url, sep_model):
    """Separate on the rig, pitchpin the vocal, remix. Returns the remixed wav path."""
    tmp = tempfile.mkdtemp(prefix="finish_")
    base = os.path.splitext(os.path.basename(inp))[0]
    # 1. push to rig, separate. BS-Roformer is the 2026 SotA for vocal isolation
    # (SDR ~12.1 vocals / 16.3 instrumental vs UVR-MDX-NET-Inst_HQ_4's 10.36),
    # and separation quality is the single biggest lever on final vocal-tune
    # quality -- artifacts get AMPLIFIED by pitch correction, so a cleaner stem
    # matters more here than anywhere. Override with SEP_MODEL.
    run(["scp", inp, f"{rig_host}:C:/temp/{base}.wav"])
    # Write the remote script to a FILE and run `wsl bash <file>`. Passing it
    # inline as `ssh host wsl -e bash -c "..."` is broken: ssh joins its argv with
    # spaces and drops the quotes, so everything after the first ';' runs in the
    # wrong shell (documented trap; hit live 2026-09-07). A file has no quoting.
    script = (
        "source ~/miniconda3/etc/profile.d/conda.sh\n"
        "conda activate seedvc\n"
        "rm -rf /mnt/c/temp/finish_out; mkdir -p /mnt/c/temp/finish_out\n"
        f"audio-separator /mnt/c/temp/{base}.wav "
        f"--model_filename {sep_model} --output_dir /mnt/c/temp/finish_out\n"
        "ls /mnt/c/temp/finish_out/\n"
    )
    sf = os.path.join(tmp, "sep.sh")
    open(sf, "w").write(script)
    run(["scp", sf, f"{rig_host}:C:/temp/finish_sep.sh"])
    listing = run(["ssh", rig_host, "wsl", "-e", "bash", "/mnt/c/temp/finish_sep.sh"],
                  capture_output=True, text=True).stdout
    def pick(kind):
        for ln in listing.splitlines():
            if f"({kind})" in ln:
                return ln.strip()
        raise SystemExit(f"separation produced no {kind} stem; got:\n{listing}")
    voc = os.path.join(tmp, "vocals" + os.path.splitext(pick("Vocals"))[1])
    inst = os.path.join(tmp, "inst" + os.path.splitext(pick("Instrumental"))[1])
    run(["scp", f"{rig_host}:C:/temp/finish_out/{pick('Vocals')}", voc])
    run(["scp", f"{rig_host}:C:/temp/finish_out/{pick('Instrumental')}", inst])
    # 2. pitchpin the isolated vocal
    tuned = os.path.join(tmp, "vocals_tuned.wav")
    pin = os.path.join(os.path.dirname(HERE), "Pitchpin", "pitchpin.py")
    run(["uv", "run", pin, voc, tuned, "--key", key, "--scale", scale, "--strength", str(strength)])
    # 3. remix tuned vocal under the untouched instrumental
    remix = os.path.join(tmp, f"{base}_tuned_mix.wav")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", tuned, "-i", inst,
         "-filter_complex",
         "[0:a]aformat=channel_layouts=stereo[v];[v][1:a]amix=inputs=2:duration=longest:normalize=0[o]",
         "-map", "[o]", remix])
    return remix, tmp


def main():
    ap = argparse.ArgumentParser(description="engine-agnostic finishing stage")
    ap.add_argument("input", help="audio from ANY engine (ACE-Step / LeVo / MiniMax)")
    ap.add_argument("--out", default=None, help="output base path (default: alongside input)")
    ap.add_argument("--target", default="soundcloud", choices=["soundcloud", "spotify", "both"])
    ap.add_argument("--tune", action="store_true", help="stem-separate + pitchpin the vocal first (needs the rig)")
    ap.add_argument("--key", default="A")
    ap.add_argument("--scale", default="minor")
    ap.add_argument("--strength", type=float, default=0.7)
    ap.add_argument("--rig-host", default=os.environ.get("RIG_HOST", "win"))
    ap.add_argument("--rig-url", default=os.environ.get("ACE_URL", "http://127.0.0.1:8901"))
    ap.add_argument("--sep-model", default=os.environ.get("SEP_MODEL",
                    "model_bs_roformer_ep_368_sdr_12.9628.ckpt"),
                    help="audio-separator model for --tune (default: BS-Roformer, SotA vocals)")
    ap.add_argument("--match", default=None, metavar="REF.wav",
                    help="reference-match (Matchering) to REF before the loudness master")
    a = ap.parse_args()

    src = a.input
    tmp = None
    if a.tune:
        print("[tune] separating + pitch-correcting the vocal on the rig ...", file=sys.stderr)
        src, tmp = tune_vocal(a.input, a.key, a.scale, a.strength, a.rig_host, a.rig_url, a.sep_model)

    if a.match:
        matched = os.path.splitext(src)[0] + "_matched.wav"
        run(["uv", "run", os.path.join(HERE, "master_match.py"), src, a.match, matched])
        src = matched
    outbase = a.out or (os.path.splitext(a.input)[0] + ("_tuned_master" if a.tune else "_master"))
    master(src, outbase, a.target)
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nfinished -> {outbase}-*.wav", file=sys.stderr)


if __name__ == "__main__":
    main()
