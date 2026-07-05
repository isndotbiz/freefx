# freefx — Ideal State Artifact

## Problem
Most open-source audio effects are real-time DAW plugins: GUI-bound, license-gated,
and impossible to script or reproduce exactly. There is no clean, offline,
command-line-first suite of mixing/mastering DSP that the community can read, batch,
and verify — built from public textbook algorithms rather than reverse-engineered
from commercial plugins.

## Vision
A complete, MIT-licensed library of self-contained audio effects: each a single
`uv`-runnable Python script (no DAW, no GUI, no license) plus clean-room JUCE/VST3
ports for in-DAW use. Every module is built from published DSP (RBJ EQ Cookbook,
oversampled waveshaping, Freeverb topology, WORLD vocoder), prints its own
behavioural self-check, and is independently verifiable against a reference.

## Goal
Maintain a clean-room, scriptable audio-effects suite where every Python module runs
standalone via `uv` and produces finite, behaviourally-correct output, and the JUCE
VST3 ports build reproducibly from in-tree JUCE and load/process in a host.

## Criteria
- [ ] All ~28 Python effect scripts compile cleanly (`python3 -m py_compile *.py`).
- [ ] Each effect, run on a test signal via `uv run <mod>.py`, produces finite,
      non-NaN/non-Inf output and prints its documented self-check measurement.
- [ ] The VST3 CMake project configures and builds in Release from in-tree JUCE
      (`cmake -B vst3/build -S vst3 && cmake --build vst3/build`).
- [ ] Every built VST3 loads in a host (pedalboard) and processes a sine to finite output.
- [ ] README usage examples match the actual CLI flags of each script (docs accurate).
- [ ] Clean-room invariant holds: no module references, decompiles, or copies any
      commercial plugin — only published/public-domain DSP.

## Constraints
- **Clean-room only** — never reference, decompile, or port from any commercial plugin.
  All DSP must trace to published textbook sources (cite them in headers).
- **`uv` single-file scripts** — each module stays self-contained with its inline
  `# /// script` dependency block; do not introduce a shared package/install step
  that breaks `uv run <mod>.py`.
- **Python deps pinned via uv inline metadata** (`numpy<2`, scipy, soundfile, numba
  where used). Do not silently bump or unpin them.
- **VST3 build pulls JUCE in-tree via FetchContent** (pinned tag) — do not require a
  system JUCE install.
- **Off-limits / destructive:** never delete user audio (`*.wav/*.flac/*.ogg`), the
  `matches/` reports, or `vst3/build/` artefacts in a way that loses work; never push,
  open PRs, or publish; never modify `LICENSE`. No secrets/PII live here.

## Out of Scope
- Real-time / low-latency processing guarantees (this is an offline, batch suite).
- Custom plugin GUIs (VST3 ports use JUCE's generic editor in v1).
- Polyphonic pitch operations (autotune/harmonizer are monophonic by design).
- Reverse-engineering or behaviour-cloning specific commercial plugins beyond
  legal black-box behavioural matching (`match.py`).
- VST3 ports of every module — porting the remaining ~23 is roadmap, not a gate.
