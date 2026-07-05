# Build vs Buy Map

Purpose: decide which recommended music-production purchases are worth replacing with focused command-line tools for the MusicOld lane: emo trap, cloud rap, crisp vocals, loud SoundCloud masters, and text-driven iteration through Claude/Codex.

This is not a plan to clone proprietary plugins. The rule remains clean-room only: build the subset of behavior we need from public DSP and open-source libraries.

## Reuse First

These projects have active open-source code or useful communities. Prefer wrapping or interoperating before writing DSP from scratch.

| Area | Reuse candidate | Use in freefx |
| --- | --- | --- |
| Audio I/O, VST3 hosting, offline rendering | Spotify `pedalboard` | Continue using for VST3 verification, installed-plugin checks, and optional third-party render tests. |
| Time-stretch / pitch-shift | Rubber Band Library | Candidate backend for higher-quality `formant.py`, `timefx.py`, and tempo tools. Check GPL/commercial licensing before embedding. CLI subprocess use is safest. |
| Loudness metering | `pyloudnorm` | Candidate for `master_assist.py`; current `tplimit.py` already uses ffmpeg for target LUFS. |
| Audio/music analysis | `librosa`, `aubio`, Essentia | Candidate for BPM/key/crest/spectral analysis and automatic chain decisions. Essentia's AGPL license needs care. |
| Pitch tracking | WORLD/pyworld, torchcrepe | WORLD is already used by `pitchpin`/`autotune`. torchcrepe is a future higher-accuracy option. |
| Saturation/color DSP references | Airwindows | MIT reference/community for clean-room saturation, console/tape color, and utility processors. |

## Already Covered Enough

| Recommended buy/demo | What we use instead |
| --- | --- |
| Auto-Tune/Graillon for hard tune | `autotune.py`, `pitchpin.py`, `chain.py --preset vocal-hard-tune` or `vocal-natural-tune`. |
| TDR Nova / Pro-Q style EQ and dynamic EQ | `eq.py`, `dyneq.py`, `deesser.py`, `mbcomp.py`; VST3s installed for most of these. |
| Pro-C / 1176 basic compression | `comp.py`, `mbcomp.py`, `chain.py` presets. |
| Fresh Air / air enhancer | `exciter.py`, high shelf in `eq.py`. |
| Valhalla / TAL reverb for basic space | `verb.py`, `irverb.py`, plus `space` chain preset. |
| MicroShift-style width | `doubler.py`, `width.py`, `chorus.py`. |
| H-Delay basics | `delay.py` covers milliseconds and ping-pong. |
| RC-20 basics | `texture.py`, `sat.py`, `bitcrush.py`, `lofi` chain preset. |
| Ozone Elements basics | `master-loud` and `trap-loud` chains using `eq`, `mbcomp`, `sat`, `clipper`, `tplimit`. |

## Worth Building Next

These are small, command-line-friendly subsets of commercial apps that fit the actual workflow.

1. `rider.py` — vocal gain rider
   - Replaces the useful part of Waves Vocal Rider.
   - Input: vocal stem.
   - Output: level-smoothed vocal before compression.
   - Core behavior: target RMS/LUFS window, max gain change, attack/release, optional automation CSV.

2. `master_assist.py` — one-click mastering assistant
   - Replaces the useful part of Ozone Elements for this lane.
   - Analyze LUFS, true peak, crest factor, spectral tilt, bass mono risk.
   - Render two outputs: SoundCloud loud master and Spotify/dynamic master.

3. `delay.py` upgrade — tempo sync and ducking
   - Add `--bpm`, `--note 1/4|1/8|1/8d|1/16`, and `--duck`.
   - This covers the useful H-Delay / Tempo Delay workflow.

4. `timefx.py` — stutter, tape stop, half-time, repeat throws
   - Replaces the useful parts of Gross Beat / ShaperBox for trap effects.
   - Command-line patterns: `--pattern`, `--grid`, `--mix`, `--bpm`.

5. `formant.py` — dedicated pitch/formant color tool
   - Focused Little AlterBoy subset.
   - Separate from full autotune: transpose/formant shift/dry-wet for alter-ego textures.

6. `retro.py` — one-knob lo-fi color macro
   - Bundles `texture`, `sat`, `bitcrush`, tone filtering, dropout/wobble.
   - Replaces the useful RC-20 workflow without trying to copy its UI.

## Probably Not Worth Building Now

| Tool category | Why not now |
| --- | --- |
| Full Melodyne | Manual note editor, timing editor, and polyphonic editing are too large. Build a simple monophonic note-map editor later if needed. |
| Full DAW / FL Studio replacement | The command-line workflow only needs renders and chain presets, not a timeline UI. |
| Serum/Vital/Kontakt/Splice replacement | Synths and sample libraries are separate product categories. Use free Vital/LABS/samples for now. |
| Real-time live monitoring | Current goal is offline render via Claude/Codex. Real-time latency adds complexity with little current benefit. |

## One-Program Shape

`freefx.py` is the single entry point:

```bash
uv run freefx.py list
uv run freefx.py describe vocal.wav out.wav "hard tune, de-ess, add air, compress" --key A
uv run freefx.py chain vocal.wav out.wav --preset vocal-modern --key A
uv run freefx.py run eq in.wav out.wav -- --band hpf:80::0.707
uv run freefx.py plugins
uv run freefx.py verify-vst3
```

Claude/Codex should prefer `freefx.py describe` for normal music work, then inspect the printed chain and adjust individual tool arguments only when needed.
