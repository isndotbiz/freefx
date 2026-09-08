#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["matchering", "soundfile", "numpy<2"]
# ///
"""master_match.py -- reference-matched mastering (Matchering 2.0).

Research finding for AI-generated music: engine output tends to come out quiet,
over-compressed, and spectrally lopsided. Reference-matching fixes exactly that
class of problem -- it matches your track's loudness curve, spectral balance, and
limiting to a REFERENCE master in the same genre, rather than applying a fixed
chain blind. This is the community's top DIY mastering move (Matchering 2.0,
sergree/matchering), and it complements the freefx master chain rather than
replacing it: match to a good reference here, or run the freefx master_assist
chain for a target-LUFS render -- or both (match, then loudness-cap).

  ./master_match.py target.wav reference.wav out.wav [--bit 16]

The reference should be a finished master you like in the same style. Use one of
your own best-sounding tracks if you don't have a licensed commercial reference;
matchering only reads its spectral/loudness fingerprint, it does not copy audio.
"""
import argparse, sys

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("reference")
    ap.add_argument("out")
    ap.add_argument("--bit", type=int, default=16, choices=[16, 24])
    a = ap.parse_args()

    import matchering as mg
    mg.log(print)
    results = [mg.pcm16(a.out)] if a.bit == 16 else [mg.pcm24(a.out)]
    mg.process(target=a.target, reference=a.reference, results=results)
    print(f"\nmatched -> {a.out}", file=sys.stderr)

if __name__ == "__main__":
    main()
