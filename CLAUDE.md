# freefx

Open-source, scriptable audio effects (mixing/mastering DSP) — clean-room
implementations built from published DSP literature (Audio EQ Cookbook,
Freeverb, look-ahead limiting, WORLD vocoder), not decompiled or
reverse-engineered from any commercial plugin. Sibling repo to `pitchpin`
(pitch correction). MIT-licensed.

## Why it exists
Most open-source effects are real-time DAW plugins. This is the offline,
command-line, pipeline-friendly kind: master a folder, script a chain,
reproduce a mix exactly, no DAW/GUI/license required.

## Stack
Python, each tool a self-contained `uv` script (PEP 723 inline deps — no
separate install step, `uv run <tool>.py` resolves numpy/scipy/soundfile
automatically; `verb`/`dyneq` also pull `numba` for JIT). I/O via libsndfile
(WAV/FLAC/OGG). `tplimit --target-lufs` needs `ffmpeg` on PATH.

## Run
```bash
uv run eq.py in.wav out.wav --band peak:300:-3:0.9
uv run comp.py vox.wav out.wav --threshold -18 --ratio 4 --makeup auto
uv run verb.py in.wav out.wav --roomsize 0.7 --wet 0.3
```
~24 tools total (eq, comp, verb, dyneq, autotune, sat, clipper, transient,
exciter, doubler, gate, width, mbcomp, harmonizer, bitcrush, delay, chorus,
duck, deesser, flanger, phaser, tremolo, vocoder, texture, irverb) — see
README.md for full per-tool flags and examples.

## Layout
- Top-level `*.py` — one file per effect, self-documenting header + argparse
- `vst3/` — JUCE VST3 ports (currently `eq`, `clipper`, `sat`; CMake-based,
  remaining ~23 modules planned via the same pattern)
- `matches/` — A/B null-test reports vs commercial plugins (via `ab.py`),
  proving the clean-room DSP matches reference behavior without copying it

## Invariant
Every effect must trace to published DSP, never to a decompiled/reverse-
engineered commercial plugin — that would be both illegal and un-licensable
as open source (see README "Principle: clean-room only"). Each tool's README
entry documents a verification result (e.g. measured LUFS/dBTP, harmonic
content, crest-factor change) — new tools should keep that pattern.
