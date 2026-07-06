# STATE — freefx (clean-room MIT audio effects suite)

> Resume doc. Read first on session start. `/state` reads it, `/wrap` writes it.
> Last touch: 2026-07-05 — port. **ALL 24 VST3 ports DONE.** The last 5 (delay, chorus, width, doubler, irverb) were written + built + pedalboard-verified + signal-differential-verified (each ENGAGED, rms(out-dry) 0.028–0.070) this session. Full suite now **24/24 built (clean build exit 0, explicit /usr/bin/cc — `~/.local/bin/cc` shadows the compiler) + 24/24 pedalboard-verified (`vst3/verify.py`)**. 26 Python effects + `ab` + `match` shipped. Only the 3 WORLD-pitch modules (autotune/harmonizer/pitchpin) remain deliberately un-ported (offline, out of scope). master well ahead of origin — push awaits Jonathan.

## Mission anchor
A complete, free, **MIT, clean-room** audio-effects suite that anyone can use — the legal answer to "make the paid plugins free for everyone." Built from public DSP only. Pairs with the music-gen work in the parent dir `..` (MusicOld — freefx now lives inside it, moved 2026-07-03). Recreational/for-fun lineage, but the repo is public (github.com/isndotbiz/freefx) and real.

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
| ✅ built + pedalboard-verified + **on master** | eq, clipper, sat, duck, deesser, flanger, phaser, tremolo, vocoder, texture, comp, dyneq, exciter, gate, mbcomp, tplimit, transient, bitcrush, verb (19) | `master` — re-verified via `vst3/verify.py` 2026-07-05 |
| ✅ **NEW** built + pedalboard + signal-differential verified | delay (Fdly), chorus (Fcho), width (Fwid), doubler (Fdbl), irverb (Firv) (5) | `master` — ported 2026-07-05; all ENGAGED (alter signal), all finite |
| ❌ deliberately un-ported (offline WORLD-pitch, out of scope) | autotune, harmonizer, pitchpin (3) | never — need a different real-time algorithm |

## 🎯 NEXT SESSION AGENDA (exact order)
1. **Push** master to origin — it is well AHEAD of origin (all 24 VST3 ports + the CMake refactor + everything past `58d60ed`). Push gate (combined 24/24 build + verify) has PASSED. Awaits Jonathan's go on the public repo.
2. **Install the 5 new `.vst3`** to `~/Library/Audio/Plug-Ins/VST3/` if you want them in a DAW (delay, chorus, width, doubler, irverb) — adhoc-sign + de-quarantine like the earlier 19.
3. Optional polish: the doubler's detune-via-delay-modulation and irverb's synthetic-plate IR are real-time reformulations of the offline Python (documented inline) — a listen test could tune modRate/decay if the character needs it.
4. Optional: `match.py` behavioral A/B for the 5 new ports vs their Python sources.

## Anti-instructions / gotchas
- **Verify-before-merge**: the 9 written modules are UNVERIFIED. Build + load each before merging to master.
- **Don't port autotune/harmonizer/pitchpin to VST3** — WORLD-based offline; out of scope by design.
- **master is ahead of origin** — push only AFTER the combined build passes.
- **Anvil/Kimi is DOWN** — Moonshot account suspended (zero balance). Don't route code to Anvil until topped up. (It also left harmless uncommitted edits in `~/.claude/.env` + `AnvilProgress.ts`.)
- **Forge agents kept dying mid-run** this session (process exits lost in-flight state). Prefer direct work or small verified batches over big parallel agent fan-outs for the rest.
- **Clean-room only** — see HARD RULE above.
