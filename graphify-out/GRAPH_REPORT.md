# Graph Report - Freefx  (2026-09-21)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1199 nodes · 1454 edges · 78 communities (73 shown, 5 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 13 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `6fd4df9a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- Community 43
- Community 44
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 55
- Community 56
- Community 57
- Community 58
- Community 59
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70

## God Nodes (most connected - your core abstractions)
1. `Tools` - 18 edges
2. `run_pair()` - 15 edges
3. `BiquadFilter` - 12 edges
4. `BandCompressor` - 12 edges
5. `BiquadCoefficients` - 11 edges
6. `build_parser()` - 10 edges
7. `OnePoleLowpass` - 10 edges
8. `Channel` - 10 edges
9. `DryDelay` - 9 edges
10. `BandParamIds` - 9 edges

## Surprising Connections (you probably didn't know these)
- `run_pair()` --calls--> `find_vst3()`  [EXTRACTED]
  match.py → ab.py
- `run_pair()` --calls--> `measure_lufs()`  [EXTRACTED]
  match.py → ab.py
- `pair_cost()` --calls--> `spectral_tilt_db()`  [EXTRACTED]
  match.py → ab.py
- `run_pair()` --calls--> `spectral_tilt_db()`  [EXTRACTED]
  match.py → ab.py
- `pair_cost()` --calls--> `null_residual_db()`  [EXTRACTED]
  match.py → ab.py

## Import Cycles
- None detected.

## Communities (78 total, 5 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (26): BandCompressor, atkCoef, detectorEnv, halfKnee, knee, relCoef, slope, smoothedGain (+18 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (21): vector, OnePoleLowpass, alpha, enabled, sampleRate, states, changeProgramName(), AudioBuffer (+13 more)

### Community 2 - "Community 2"
Cohesion: 0.09
Nodes (33): best_align(), cmd_compare(), cmd_vst(), _coerce(), find_vst3(), main(), measure_lufs(), null_residual_db() (+25 more)

### Community 3 - "Community 3"
Cohesion: 0.05
Nodes (20): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+12 more)

### Community 4 - "Community 4"
Cohesion: 0.06
Nodes (24): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+16 more)

### Community 5 - "Community 5"
Cohesion: 0.06
Nodes (23): Band, carHpf, carLpf, env, modHpf, modLpf, changeProgramName(), AudioBuffer (+15 more)

### Community 6 - "Community 6"
Cohesion: 0.06
Nodes (19): AudioProcessorValueTreeState, NormalisableRange, readParameter(), skewedRange(), changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout (+11 more)

### Community 7 - "Community 7"
Cohesion: 0.06
Nodes (20): maxStages, changeProgramName(), ChannelState, last, zs, array, AudioBuffer, AudioProcessorEditor (+12 more)

### Community 8 - "Community 8"
Cohesion: 0.08
Nodes (17): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+9 more)

### Community 9 - "Community 9"
Cohesion: 0.07
Nodes (18): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+10 more)

### Community 10 - "Community 10"
Cohesion: 0.08
Nodes (18): changeProgramName(), coefFromMs(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout (+10 more)

### Community 11 - "Community 11"
Cohesion: 0.08
Nodes (17): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+9 more)

### Community 12 - "Community 12"
Cohesion: 0.07
Nodes (18): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+10 more)

### Community 13 - "Community 13"
Cohesion: 0.08
Nodes (18): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+10 more)

### Community 14 - "Community 14"
Cohesion: 0.07
Nodes (18): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+10 more)

### Community 15 - "Community 15"
Cohesion: 0.07
Nodes (16): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+8 more)

### Community 16 - "Community 16"
Cohesion: 0.07
Nodes (16): changeProgramName(), coefFromMs(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout (+8 more)

### Community 17 - "Community 17"
Cohesion: 0.08
Nodes (17): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+9 more)

### Community 18 - "Community 18"
Cohesion: 0.07
Nodes (17): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+9 more)

### Community 19 - "Community 19"
Cohesion: 0.07
Nodes (16): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+8 more)

### Community 20 - "Community 20"
Cohesion: 0.08
Nodes (17): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+9 more)

### Community 21 - "Community 21"
Cohesion: 0.07
Nodes (15): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+7 more)

### Community 22 - "Community 22"
Cohesion: 0.07
Nodes (15): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+7 more)

### Community 23 - "Community 23"
Cohesion: 0.07
Nodes (15): changeProgramName(), AudioBuffer, AudioProcessorEditor, BusesLayout, MemoryBlock, MidiBuffer, ParameterLayout, String (+7 more)

### Community 24 - "Community 24"
Cohesion: 0.10
Nodes (15): Allpass, buffer, index, Channel, allpasses, combs, Freeverb, left (+7 more)

### Community 25 - "Community 25"
Cohesion: 0.08
Nodes (25): `ab` — A/B comparison harness, `autotune` — hard pitch tuning (the creative effect), `chain` — assistant-friendly effect chains, `clipper` — soft / hard clipper (trap loudness), `comp` — full-band compressor / de-esser, `dyneq` — dynamic EQ (per-band compression / expansion), `eq` — parametric EQ, `formant` — pitch/formant color (alter-ego voice) (+17 more)

### Community 26 - "Community 26"
Cohesion: 0.12
Nodes (15): BiquadKind, BiquadCoefficients, a1, a2, b0, b1, b2, BiquadFilter (+7 more)

### Community 27 - "Community 27"
Cohesion: 0.10
Nodes (6): AudioProcessorEditor, BusesLayout, MemoryBlock, createEditor(), getStateInformation(), isBusesLayoutSupported()

### Community 28 - "Community 28"
Cohesion: 0.19
Nodes (17): bitcrush_fx(), drive_fx(), dropout_gain(), main(), noise_bed(), Tape hiss (highpassed white) + sparse band-limited vinyl crackle, level gently…, Random raised-cosine level dips (worn tape). Returns a gain curve in (0,1];…, age -> per-component defaults; explicit sub-flags override. (+9 more)

### Community 29 - "Community 29"
Cohesion: 0.31
Nodes (16): ArgumentParser, build_parser(), cmd_chain(), cmd_describe(), cmd_list(), cmd_master(), cmd_plugins(), cmd_run_tool() (+8 more)

### Community 30 - "Community 30"
Cohesion: 0.24
Nodes (13): analyze(), main(), plan_steps(), print_analysis(), Return (pre-limit steps, why-lines). Every move states its reason., dBTP estimate: 4x oversample (resample_poly) then take the sample max., Max loudness over sliding 3 s windows, 1 s hop (short-term approximation)., dB/octave slope of the average spectrum (Welch), log-log fit 40 Hz..16 kHz. (+5 more)

### Community 31 - "Community 31"
Cohesion: 0.24
Nodes (11): _edge_fades(), fx_gate(), fx_halftime(), fx_stutter(), fx_tapestop(), main(), Trance-gate: x/1 = open, anything else = closed; linear attack/release ramps., Short linear fade-in/out on a retriggered slice to kill boundary clicks. (+3 more)

### Community 32 - "Community 32"
Cohesion: 0.29
Nodes (10): _biquad(), bpf_0db(), coef(), _dynamic_gain(), main(), parse_band(), njit, RBJ constant 0 dB peak-gain bandpass. Magnitude 1 (zero phase) at f0. (+2 more)

### Community 33 - "Community 33"
Cohesion: 0.33
Nodes (10): coef(), _detection_signal(), _high_shelf_sos(), main(), njit, _rms_frames_db(), _shift_earlier(), _smooth_gain_db() (+2 more)

### Community 34 - "Community 34"
Cohesion: 0.18
Nodes (11): BandParamIds, enable, freq, mode, q, ratio, threshold, changeProgramName() (+3 more)

### Community 35 - "Community 35"
Cohesion: 0.51
Nodes (9): chain_from_description(), main(), Path, render_chain(), script_path(), sort_steps(), Step, with_bpm() (+1 more)

### Community 36 - "Community 36"
Cohesion: 0.36
Nodes (7): blend(), main(), Scale voiced F0 by 2^(semitones/12); unvoiced frames (F0=0) stay 0., Shift the spectral envelope (formants) by N semitones without touching F0.…, Weighted sum of processed and dry. WORLD resynthesis keeps the original timing,…, transpose_f0(), warp_formants()

### Community 37 - "Community 37"
Cohesion: 0.25
Nodes (7): Constraints, Criteria, freefx — Ideal State Artifact, Goal, Out of Scope, Problem, Vision

### Community 38 - "Community 38"
Cohesion: 0.46
Nodes (7): main(), make_mix(), make_vocalish(), Path, Voiced-ish tone with alternating loud/quiet seconds (rider/comp fodder)., Kick + noise-burst + pad pseudo-mix for master/timefx tests., run()

### Community 39 - "Community 39"
Cohesion: 0.25
Nodes (7): Anti-instructions / gotchas, HARD RULE (load-bearing — asked 3×, held every time), Mission anchor, 🎯 NEXT SESSION AGENDA (exact order), STATE — freefx (clean-room MIT audio effects suite), VST3 ports — IN FLIGHT (this is the unfinished thread), What's DONE & pushed (origin/master was at `58d60ed`)

### Community 40 - "Community 40"
Cohesion: 0.25
Nodes (8): bandIds(), AudioBuffer, MidiBuffer, ParameterLayout, createLayout(), makeBandpass0dB(), onePoleCoef(), processBlock()

### Community 41 - "Community 41"
Cohesion: 0.43
Nodes (6): allowed_classes(), main(), Hard-snap each voiced F0 to the nearest scale note, then slew toward the target…, Shift the spectral envelope (formants) by N semitones without touching F0.…, snap_and_glide(), warp_formants()

### Community 42 - "Community 42"
Cohesion: 0.29
Nodes (6): Already Covered Enough, Build vs Buy Map, One-Program Shape, Probably Not Worth Building Now, Reuse First, Worth Building Next — ✅ ALL BUILT (2026-07-04)

### Community 43 - "Community 43"
Cohesion: 0.29
Nodes (6): freefx, Invariant, Layout, Run, Stack, Why it exists

### Community 44 - "Community 44"
Cohesion: 0.52
Nodes (6): coef(), _duckgain(), _fbdelay(), main(), njit, tempo_ms()

### Community 45 - "Community 45"
Cohesion: 0.52
Nodes (6): main(), master(), freefx master_assist -> <outbase>-<target>.wav (SoundCloud/Spotify/both)., Separate on the rig, pitchpin the vocal, remix. Returns the remixed wav path., run(), tune_vocal()

### Community 46 - "Community 46"
Cohesion: 0.29
Nodes (7): Band, detectorEnv, enabled, filter, modeCut, ratio, threshold

### Community 47 - "Community 47"
Cohesion: 0.29
Nodes (6): Build, freefx VST3 plugins, Implementation notes, Non-passthrough check (clipper / sat actually alter driven audio), Scope / omissions (v1), Status: all modules have targets; verify with `uv run vst3/verify.py`

### Community 48 - "Community 48"
Cohesion: 0.47
Nodes (5): coef(), _compress(), main(), njit, Soft-knee compressor gain trajectory (linear) from a detection signal. det :…

### Community 49 - "Community 49"
Cohesion: 0.33
Nodes (5): Behavioural match: freefx `autotune` vs `Auburn Sounds Graillon 3`, Converged freefx parameters, Per-probe breakdown, Result, Target (proprietary plugin configuration)

### Community 50 - "Community 50"
Cohesion: 0.33
Nodes (5): Behavioural match: freefx `dyneq` vs `TDR Nova`, Converged freefx parameters, Per-probe breakdown, Result, Target (proprietary plugin configuration)

### Community 51 - "Community 51"
Cohesion: 0.33
Nodes (5): Behavioural match: freefx `eq` vs `TDR Nova`, Converged freefx parameters, Per-probe breakdown, Result, Target (proprietary plugin configuration)

### Community 52 - "Community 52"
Cohesion: 0.33
Nodes (5): Behavioural match: freefx `verb` vs `ValhallaSupermassive`, Converged freefx parameters, Per-probe breakdown, Result, Target (proprietary plugin configuration)

### Community 53 - "Community 53"
Cohesion: 0.53
Nodes (5): coef(), _comp_gain(), compress_band(), main(), njit

### Community 54 - "Community 54"
Cohesion: 0.47
Nodes (5): flutter(), main(), Oversampled asymmetric tanh waveshaper. bias adds even harmonics (warmth); DC…, Slow pitch wobble via a modulated fractional delay (tape wow/flutter)., saturate()

### Community 55 - "Community 55"
Cohesion: 0.60
Nodes (5): allpass(), comb(), main(), njit, reverb_channel()

### Community 56 - "Community 56"
Cohesion: 0.60
Nodes (4): coef(), _gain(), main(), njit

### Community 57 - "Community 57"
Cohesion: 0.60
Nodes (4): coef(), _duck(), main(), njit

### Community 58 - "Community 58"
Cohesion: 0.60
Nodes (4): coef(), _gate(), main(), njit

### Community 59 - "Community 59"
Cohesion: 0.40
Nodes (4): freefx behavioural matches, Run it, The method is black-box behavioural matching (legal, clean-room), What "close" means

### Community 60 - "Community 60"
Cohesion: 0.60
Nodes (4): coef(), main(), njit, _shape()

### Community 61 - "Community 61"
Cohesion: 0.67
Nodes (3): detuned_copy(), main(), A delayed, slightly pitch/time-shifted copy (resample = detune + drift).

### Community 62 - "Community 62"
Cohesion: 0.83
Nodes (3): biquad(), main(), parse_band()

### Community 63 - "Community 63"
Cohesion: 0.67
Nodes (3): _flange(), main(), njit

### Community 64 - "Community 64"
Cohesion: 0.67
Nodes (3): main(), _phase(), njit

### Community 65 - "Community 65"
Cohesion: 0.83
Nodes (3): limit(), main(), measure_lufs()

## Knowledge Gaps
- **120 isolated node(s):** `b0`, `b1`, `b2`, `a1`, `a2` (+115 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Band` connect `Community 46` to `Community 26`, `Community 27`?**
  _High betweenness centrality (0.011) - this node is a cross-community bridge._
- **What connects `b0`, `b1`, `b2` to the rest of the system?**
  _120 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.0545876887340302 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.052564102564102565 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.09446693657219973 - nodes in this community are weakly interconnected._
- **Should `Community 3` be split into smaller, more focused modules?**
  _Cohesion score 0.05398110661268556 - nodes in this community are weakly interconnected._
- **Should `Community 4` be split into smaller, more focused modules?**
  _Cohesion score 0.06072874493927125 - nodes in this community are weakly interconnected._