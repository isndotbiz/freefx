# STATE — freefx (clean-room MIT audio effects suite)

> Resume doc. Read first on session start. `/state` reads it, `/wrap` writes it.
> Last touch: 2026-06-26 — /wrap. **26 Python effects + `ab` + `match` shipped & pushed.** JUCE VST3 ports in progress: **10 built+verified+merged, 9 written-but-UNVERIFIED (on branches), 5 not started.**

## Mission anchor
A complete, free, **MIT, clean-room** audio-effects suite that anyone can use — the legal answer to "make the paid plugins free for everyone." Built from public DSP only. Pairs with the music-gen work in `../MusicOld`. Recreational/for-fun lineage, but the repo is public (github.com/isndotbiz/freefx) and real.

## HARD RULE (load-bearing — asked 3×, held every time)
**NEVER reverse-engineer / decompile any proprietary plugin** (Graillon, TDR Nova, Valhalla, Melodyne, Auto-Tune…). It's illegal AND un-MIT-licensable (derivative of their binary). The legal path = **clean-room from public DSP** + `match.py` (black-box behavioral matching: measure the plugin's *output*, never its code). That IS what this repo does.

## What's DONE & pushed (origin/master was at `58d60ed`)
- **26 Python `uv` effect scripts** (all signal-verified): eq, dyneq, comp, mbcomp, gate, transient, tplimit, clipper, autotune, harmonizer, sat, exciter, bitcrush, verb, delay, chorus, width, doubler, duck, deesser, flanger, phaser, tremolo, vocoder, texture, irverb. (+ `pitchpin` sibling repo.)
- **`ab.py`** — A/B harness (pedalboard VST3 render + null-test/LUFS/TP/tilt + blind pairs).
- **`match.py`** + `matches/*.md` — behavioral-match loop. Results: eq→Nova −60 dB (excellent), dyneq→Nova −18 dB, verb→Valhalla −5.3 dB (loose, correct), autotune→Graillon ~50 cents (approx).

## VST3 ports — IN FLIGHT (this is the unfinished thread)
Target: port 21 effects to JUCE VST3 (the 3 WORLD-pitch modules **autotune/harmonizer/pitchpin are deliberately EXCLUDED** — offline vocoder, need a different real-time algorithm; do NOT try them). Pattern: `vst3/<module>/<Module>Processor.cpp` + `vst3/<module>/module.cmake`; CMakeLists.txt **auto-discovers** every `*/module.cmake` (never edit it). Shared DSP in `vst3/dsp/*.h` (read-only). Build: `cmake -B vst3/build -S vst3 -DCMAKE_BUILD_TYPE=Release && cmake --build vst3/build --config Release -j`. Verify: pedalboard `load_plugin` → finite output.

| State | Modules | Where |
|-------|---------|-------|
| ✅ built + verified + **merged to master** | eq, clipper, sat, duck, deesser, flanger, phaser, tremolo, vocoder, texture (10) | `master` (`dde91b3`) |
| ⚠️ WRITTEN but **NOT built/verified** | comp, dyneq, exciter, gate, mbcomp, tplimit, transient (7) | branch `port/dynamics` (`5fe5ffc`) |
| ⚠️ WRITTEN but **NOT built/verified** | bitcrush, verb (2) | branch `port/time-stereo` (`82db518`) |
| ❌ **NOT STARTED** | delay, chorus, width, doubler, irverb (5) | — |

## 🎯 NEXT SESSION AGENDA (exact order)
1. **Build + pedalboard-verify the 9 written modules** on `port/dynamics` + `port/time-stereo`. They are UNVERIFIED — they may not compile. Fix failures. (Worktrees: `~/Workspace/Personal/freefx-wt/{dynamics,time-stereo}`.)
2. **Write the 5 missing**: delay, chorus, width, doubler, irverb. Python sources exist; follow the proven pattern. Hints: `juce::dsp::Convolution` (irverb), `juce::dsp::DelayLine` (delay/chorus/doubler), M/S matrix + low-band mono (width). Assign unique PLUGIN_CODEs (used so far: Feq1 Fclp Fsat Fduk Fdes Ffln Fpha Ftrm Fvoc Ftex Fcmp Fdyn Fexc Fgat Fmbc Ftpl Ftrn Fbit Fvrb — pick Fdly Fcho Fwid Fdbl Firv).
3. **Merge** `port/dynamics` + `port/time-stereo` (+ the 5 new) into master once each is verified.
4. **One combined clean-checkout build** of all 24 VST3s → confirm they compile + load together.
5. **Push** master to origin — it is AHEAD of origin by the CMake refactor (`c4230ab`) + mod-special merge (`dde91b3`) + everything after. Nothing past `58d60ed` is pushed yet.
6. Optional: install all 24 `.vst3` to `~/Library/Audio/Plug-Ins/VST3/` (3 already installed: eq, clipper, sat).

## Anti-instructions / gotchas
- **Verify-before-merge**: the 9 written modules are UNVERIFIED. Build + load each before merging to master.
- **Don't port autotune/harmonizer/pitchpin to VST3** — WORLD-based offline; out of scope by design.
- **master is ahead of origin** — push only AFTER the combined build passes.
- **Anvil/Kimi is DOWN** — Moonshot account suspended (zero balance). Don't route code to Anvil until topped up. (It also left harmless uncommitted edits in `~/.claude/.env` + `AnvilProgress.ts`.)
- **Forge agents kept dying mid-run** this session (process exits lost in-flight state). Prefer direct work or small verified batches over big parallel agent fan-outs for the rest.
- **Clean-room only** — see HARD RULE above.
