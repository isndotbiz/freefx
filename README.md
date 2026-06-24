# freefx

**Open-source, scriptable audio effects.** Clean-room implementations of common mixing/mastering DSP — written from public textbook algorithms, not reverse-engineered from any commercial plugin. Each tool is a self-contained `uv` script: no DAW, no GUI, no license, fully batchable.

MIT-licensed. Sibling of [`pitchpin`](https://github.com/isndotbiz/pitchpin) (pitch correction). Python first; VST3 ports planned.

## Why
Most open-source effects are real-time DAW plugins. `freefx` is the *offline, command-line, pipeline-friendly* kind — master a folder, script a chain, reproduce a mix exactly. Built so the community can read, learn from, and improve the DSP.

## Tools

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

## Install & run
Requires [`uv`](https://docs.astral.sh/uv/) — it resolves all deps (numpy, scipy, soundfile) automatically. I/O: WAV/FLAC/OGG (libsndfile). `--target-lufs` in `tplimit` also needs `ffmpeg` on PATH for loudness measurement.

## Principle: clean-room only
Every effect here is built from **published DSP** (EQ cookbook, look-ahead limiting, oversampling for true-peak). No commercial plugin was decompiled or reverse-engineered — that would be illegal *and* un-licensable as open source. We build the math from scratch and stand on prior open work (e.g. [Airwindows](https://www.airwindows.com/), public-domain).

## Roadmap
- [x] `verb` — algorithmic reverb (Freeverb topology) ✅
- [ ] `dyneq` — dynamic EQ (per-band compression)
- [ ] `autotune` — real-time-style pitch correction (offline)
- [ ] VST3 ports (JUCE) of the proven modules
- [ ] dynamics: compressor / de-esser

## License
MIT (see `LICENSE`). Not affiliated with or derived from any commercial audio product.
