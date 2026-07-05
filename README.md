# freefx

**Open-source, scriptable audio effects.** Clean-room implementations of common mixing/mastering DSP — written from public textbook algorithms, not reverse-engineered from any commercial plugin. Each tool is a self-contained `uv` script: no DAW, no GUI, no license, fully batchable.

MIT-licensed. Sibling of [`pitchpin`](https://github.com/isndotbiz/pitchpin) (pitch correction). Python first; VST3 ports planned.

## One command

Use `freefx.py` as the suite entry point:

```bash
uv run freefx.py list
uv run freefx.py describe vocal.wav out.wav "hard tune, de-ess, add air, compress" --key A
uv run freefx.py chain vocal.wav out.wav --preset vocal-modern --key A --scale minor
uv run freefx.py run eq in.wav out.wav -- --band hpf:80::0.707
uv run freefx.py plugins
uv run freefx.py verify-vst3
```

## Why
Most open-source effects are real-time DAW plugins. `freefx` is the *offline, command-line, pipeline-friendly* kind — master a folder, script a chain, reproduce a mix exactly. Built so the community can read, learn from, and improve the DSP.

## Tools

### `chain` — assistant-friendly effect chains
Describe the sound you want, or pick a named preset, and `chain.py` renders a
repeatable sequence of freefx tools. This is the easiest way to use Claude/Codex
like a text-driven plugin rack: ask for the sound, inspect the printed commands,
then rerun or tweak the chain.
```bash
uv run chain.py vocal.wav vocal-polished.wav --preset vocal-modern --key A --scale minor
uv run chain.py vocal.wav vocal-hard.wav --describe "hard tune vocal, de-ess, add air, compress, reverb"
uv run chain.py mix.wav master.wav --describe "loud warm trap master with clipper and limiter"
uv run chain.py in.wav out.wav --preset lofi --dry-run
uv run chain.py --list-presets
```
Current presets: `vocal-clean`, `vocal-modern`, `vocal-hard-tune`,
`vocal-natural-tune`, `master-loud`, `trap-loud`, `lofi`, `space`.

### `tplimit` — true-peak limiter / loudness maximizer
Oversampled look-ahead brickwall limiting. Catches inter-sample peaks so the output never exceeds the ceiling in dBTP; `--target-lufs` auto-calibrates gain to a loudness target.
```bash
uv run tplimit.py in.wav out.wav --ceiling -1
uv run tplimit.py in.wav out.wav --target-lufs -9 --ceiling -1   # maximize, TP-safe
```
*Verified: maximizes to the target LUFS while keeping true-peak ≤ ceiling (e.g. −8.8 LUFS @ −1.2 dBTP).*

### `eq` — parametric EQ
Biquad cascade (Robert Bristow-Johnson's Audio EQ Cookbook). Any number of bands: `peak | lowshelf | highshelf | hpf | lpf`. Prints the actual gain at each band center as a self-check.
```bash
uv run eq.py in.wav out.wav --band peak:300:-3:0.9 --band highshelf:10000:2:0.7 --band hpf:30::0.707
```
Band format: `TYPE:FREQ_HZ:GAIN_DB:Q`.

### `verb` — algorithmic reverb
Clean-room Freeverb topology: 8 parallel damped comb filters → 4 series allpass filters per channel. Delay loops are JIT-compiled (numba) so it's fast on a full track.
```bash
uv run verb.py in.wav out.wav --roomsize 0.7 --damp 0.4 --wet 0.3
uv run verb.py vocal.wav wet.wav --roomsize 0.85 --wet 0.22 --predelay-ms 25 --tail-sec 2
```
Params: `--roomsize` (decay), `--damp` (HF absorption), `--wet`/`--dry`, `--width` (stereo), `--predelay-ms`, `--tail-sec` (ring-out). *Verified: stable, monotonic decay (no blowup).*

### `dyneq` — dynamic EQ (per-band compression / expansion)
A peaking band whose gain is driven by the signal's own level *inside that band* — de-ess, tame a boomy resonance only when it spikes, or add air only on loud notes. Clean-room parallel form `y = x + k(t)·BPF(x)` with a standard compressor static curve and attack/release.
```bash
uv run dyneq.py vocal.wav out.wav --band 7000:2.5:-28:4:cut          # dynamic de-ess
uv run dyneq.py mix.wav out.wav --band 220:1.2:-24:3:cut --band 12000:0.8:-30:2:boost \
      --attack-ms 5 --release-ms 120 --range-db 9
```
Band format: `FREQ_HZ:Q:THRESHOLD_DB:RATIO[:cut|boost]` (`cut` compresses above threshold, `boost` expands below). Global: `--attack-ms --release-ms --range-db --makeup-db`. Prints the gain range applied per band. *Verified: cut-only −6.8 dB @ 7 kHz / −10.3 dB @ 220 Hz on a real vocal master, output finite & non-clipping.*

### `autotune` — hard pitch tuning (the creative effect)
The T-Pain / trap effect, not transparent correction (that's [`pitchpin`](https://github.com/isndotbiz/pitchpin)). Snaps dead-flat to the scale via the WORLD vocoder, with a `--retune-ms` glide knob (0 = robotic staircase, higher = slurred glide), a `--formant` shift for a deeper/bigger or brighter/smaller voice, and a `--pitch` transpose. Monophonic only.
```bash
uv run autotune.py vox.wav out.wav --key A --scale minor                  # hard tune
uv run autotune.py vox.wav out.wav --key C --scale major --retune-ms 40   # T-Pain glide
uv run autotune.py vox.wav out.wav --key A --scale minor --formant -3 --pitch -2  # deep/dark
```
Params: `--key/--scale`, `--retune-ms` (slew), `--strength` (1=full snap), `--formant` (semitones, negative = deeper), `--pitch` (transpose), `--fast`. *Verified on a real vocal stem: hard tune moved notes-in-scale 39%→70% and halved cents-off; `--pitch -2` transposed −2 semitones to within 0.5%.*

### `comp` — full-band compressor / de-esser
Feed-forward compressor: soft-knee static curve, peak or RMS detection, attack/release, makeup (`auto` or fixed dB), stereo-linked so the image holds. Add `--sidechain-hpf` and it only reacts to bright/loud content — a de-esser.
```bash
uv run comp.py vox.wav out.wav --threshold -18 --ratio 4 --attack-ms 5 --release-ms 120 --makeup auto
uv run comp.py drums.wav out.wav --threshold -12 --ratio 6 --knee 4 --rms
uv run comp.py vox.wav out.wav --threshold -26 --ratio 5 --sidechain-hpf 5500   # de-ess
```
Params: `--threshold --ratio --knee --attack-ms --release-ms --rms[/--rms-ms] --makeup --sidechain-hpf`. Prints gain-reduction range + makeup. *Verified: compressed a clean 20 dB loud/quiet test signal to 12.6 dB (loud clamped, quiet untouched).*

### `sat` — tape / analog saturation
The warmth/grit/glue colour. Drives the signal into an oversampled (4×, anti-aliased) asymmetric tanh waveshaper for even+odd harmonics, with a tape-style HF rolloff and optional wow/flutter pitch wobble.
```bash
uv run sat.py vox.wav out.wav --drive 6                              # gentle warmth
uv run sat.py mix.wav out.wav --drive 10 --tone-hz 12000 --mix 0.8   # tape glue
uv run sat.py vox.wav out.wav --drive 8 --flutter 6 --bias 0.15      # lo-fi wobble
```
Params: `--drive` (dB in), `--bias` (asymmetry → even harmonics), `--tone-hz` (HF rolloff), `--flutter[/--flutter-hz]` (cents of wow), `--mix`, `--oversample`. *Verified: 1 kHz sine gained a 2nd harmonic at −25 dB / 3rd at −16 dB (from a −124 dB noise floor) — real harmonic generation, no aliasing.*

### `clipper` — soft / hard clipper (trap loudness)
Flattens peaks instantly instead of riding gain like a limiter — the aggressive way trap/hip-hop masters get loud. Oversampled 4× so the clipping harmonics don't alias. Soft (tanh knee) or `--hard`.
```bash
uv run clipper.py master.wav out.wav --drive 4 --ceiling -1        # soft clip 4 dB in
uv run clipper.py 808.wav out.wav --drive 6 --ceiling -0.5 --hard  # hard clip
uv run clipper.py mix.wav out.wav --drive 3 --mix 0.7             # parallel clip
```
Params: `--drive --ceiling --hard --mix --oversample`. Reports % samples clipped + crest change. *Verified: hard clip 10 dB into −1 dBTP flattened a drum hit 5.6% of samples, crest 15.8→9.0 dB.*

### `transient` — transient shaper (attack / sustain)
Level-independent punch control: snap an 808/snare attack or fatten its tail, without the level-dependent behaviour of a compressor. Dual-envelope (fast vs slow follower) design.
```bash
uv run transient.py drums.wav out.wav --attack 6                # snappier
uv run transient.py 808.wav out.wav --attack 4 --sustain -3     # punchier, tighter tail
uv run transient.py loop.wav out.wav --attack -4               # soften the hits
```
Params: `--attack` (+ snap / − soften), `--sustain` (+ fatter / − tighter), `--max-db`. *Verified on a synthetic drum: `--attack +8` raised crest to 16.2 dB, `−8` lowered it to 14.7 dB (dry 15.8) — punch up/down as intended.*

### `ab` — A/B comparison harness
Render a source through a real plugin (pedalboard), then measure + null-test any set of renders and emit a blind-labelled pair for a listening panel.
```bash
uv run ab.py vst dope_boy_fresh.wav nova.wav "TDR Nova" --param Mix=0.3     # B = a real plugin
uv run ab.py compare freefx_out.wav nova.wav --src dope_boy_fresh.wav --blind ./ab_out
```
`compare` prints integrated LUFS, true-peak dBTP, spectral tilt, and null residual (gain- & time-aligned) of each candidate vs the first file, then writes `blind_1/2.wav` + a hidden `BLIND_KEY.txt`. *Verified: `verb` vs Valhalla on dope_boy_fresh — −5.0 dB null, blind pair written.*

### More modules (verified)
Full docs are in each script's header; quick reference:
```bash
uv run exciter.py    vox.wav out.wav --freq 5000 --amount 4          # HF "air" exciter (synth harmonics)
uv run doubler.py    vox.wav out.wav --voices 2 --detune 12          # ADT / stereo widener (mono->wide)
uv run gate.py       vox.wav out.wav --threshold -45 --range 40      # gate / expander (cleanup, gated snare)
uv run width.py      mix.wav out.wav --width 1.4 --mono-hz 120       # M/S stereo width + bass mono-maker
uv run mbcomp.py     master.wav out.wav --xover 200 2500 --ratio 3   # 3-band multiband compressor (exact split)
uv run harmonizer.py vox.wav out.wav --interval -12 --mix 0.4        # pitch harmonizer (oct/5th, WORLD)
uv run bitcrush.py   loop.wav out.wav --bits 6 --downsample 3        # bit/rate crusher (lo-fi)
uv run delay.py      vox.wav out.wav --time-ms 375 --feedback 0.4 --pingpong   # stereo/ping-pong throw
uv run chorus.py     pad.wav out.wav --voices 3 --rate 0.6 --depth 4 # 80s modulated-delay chorus
uv run duck.py       pads.wav out.wav --key kick.wav --amount 9      # sidechain pump / ducking
uv run deesser.py    vox.wav out.wav --freq 6500 --threshold -30     # dedicated split de-esser
uv run flanger.py    gtr.wav out.wav --rate 0.3 --depth 3 --feedback 0.6  # jet-sweep flanger
uv run phaser.py     pad.wav out.wav --stages 6 --rate 0.4           # swept all-pass phaser
uv run tremolo.py    gtr.wav out.wav --rate 5 --depth 0.6 [--pan]    # tremolo / auto-pan
uv run vocoder.py    vox.wav out.wav --carrier saw --bands 24        # channel vocoder (robot vox)
uv run texture.py    beat.wav out.wav --crackle 0.4 --hiss 0.2       # vinyl/hiss lo-fi texture
uv run irverb.py     vox.wav out.wav --ir plate.wav --mix 0.25       # convolution reverb (real IRs)
```
*All verified: exciter raises HF energy, doubler/width/chorus create measured stereo width, gate attenuates sub-threshold frames, mbcomp reconstructs to −240 dB at ratio 1:1, harmonizer adds +5 dB sub-octave, bitcrush/clipper/transient pass their signal tests.*

## Install & run
Requires [`uv`](https://docs.astral.sh/uv/) — it resolves all deps (numpy, scipy, soundfile; `verb` and `dyneq` also pull `numba` for JIT) automatically. I/O: WAV/FLAC/OGG (libsndfile). `--target-lufs` in `tplimit` also needs `ffmpeg` on PATH for loudness measurement.

## Principle: clean-room only
Every effect here is built from **published DSP** (EQ cookbook, look-ahead limiting, oversampling for true-peak). No commercial plugin was decompiled or reverse-engineered — that would be illegal *and* un-licensable as open source. We build the math from scratch and stand on prior open work (e.g. [Airwindows](https://www.airwindows.com/), public-domain).

## Roadmap
- [x] `verb` — algorithmic reverb (Freeverb topology) ✅
- [x] `dyneq` — dynamic EQ (per-band compression / expansion) ✅
- [x] `autotune` — hard pitch tuning effect (WORLD, glide + formant/pitch shift) ✅
- [x] `comp` — full-band compressor + de-esser ✅
- [x] `sat` — tape / analog saturation (oversampled waveshaper) ✅
- [x] `clipper` — soft/hard clipper (trap loudness) ✅
- [x] `transient` — transient shaper (attack/sustain designer) ✅
- [x] `ab` — A/B harness: null-test + LUFS/TP/spectral diff vs reference plugins ✅
- [x] `exciter` — HF harmonic exciter (air / "crisp") ✅
- [x] `doubler` — vocal ADT / stereo widener ✅
- [x] `gate` — noise gate / downward expander (gated-reverb snare) ✅
- [x] `width` — M/S stereo width + bass mono-maker ✅
- [x] `mbcomp` — 3-band multiband compressor ✅
- [x] `harmonizer` — pitch harmonizer (octaves/fifths, WORLD) ✅
- [x] `bitcrush` — bit-depth / sample-rate crusher ✅
- [x] `delay` — stereo / ping-pong feedback delay ✅
- [x] `chorus` — 80s modulated-delay chorus ✅
- [x] `duck` — sidechain ducking / pump ✅
- [x] `deesser` — dedicated split de-esser ✅
- [x] `flanger` · `phaser` · `tremolo`/auto-pan — modulation FX ✅
- [x] `vocoder` — channel vocoder (robot/talkbox vocals) ✅
- [x] `texture` — vinyl crackle / tape hiss / wow lo-fi ✅
- [x] `irverb` — convolution reverb (load real IRs) ✅
- [x] JUCE VST3 ports — `eq`, `clipper`, `sat` built + pedalboard-verified (`vst3/`) ✅
- [ ] VST3 ports of the remaining 23 modules — the scaling frontier (same CMake pattern)

## License
MIT (see `LICENSE`). Not affiliated with or derived from any commercial audio product.
