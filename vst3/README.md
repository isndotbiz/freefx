# freefx VST3 plugins

Clean-room JUCE/VST3 ports of three pure-DSP `freefx` modules. The DSP math is
ported from the project's own clean-room Python scripts (`eq.py`, `clipper.py`,
`sat.py`), which are themselves built from public textbook DSP (Robert
Bristow-Johnson's *Audio EQ Cookbook*, oversampled waveshaping). **No commercial
plugin was referenced, decompiled, or copied.** MIT licensed.

| Plugin            | Source        | DSP                                                                 |
|-------------------|---------------|---------------------------------------------------------------------|
| **freefx-eq**     | `eq.py`       | 3-band RBJ biquad cascade: HPF → peak → high-shelf                   |
| **freefx-clipper**| `clipper.py`  | 4× oversampled soft-`tanh` / hard clip; drive + ceiling + hard + mix |
| **freefx-sat**    | `sat.py`      | 4× oversampled asymmetric-`tanh` saturation; drive + bias + tone + mix |

Each plugin is a `juce::AudioProcessor` driven by an `AudioProcessorValueTreeState`,
with a `GenericAudioProcessorEditor` (no custom GUI in v1). Parameters mirror the
Python CLI flags.

## Build

JUCE is pulled in-tree via CMake `FetchContent` (pinned to tag **`8.0.4`**) — no
system install of JUCE is required. Requires CMake ≥ 3.22 and a C++17 toolchain
(Xcode command-line tools on macOS). Built and verified on Apple Silicon (arm64).

```bash
# from the repo root
cmake -B vst3/build -S vst3 -DCMAKE_BUILD_TYPE=Release
cmake --build vst3/build --config Release -j
```

The first configure clones JUCE (~60 s) and builds `juceaide`; subsequent builds
are incremental. Built bundles land at:

```
vst3/build/freefx_eq_artefacts/Release/VST3/freefx-eq.vst3
vst3/build/freefx_clipper_artefacts/Release/VST3/freefx-clipper.vst3
vst3/build/freefx_sat_artefacts/Release/VST3/freefx-sat.vst3
```

If the JUCE clone/build ever fails, bump `GIT_TAG` in `vst3/CMakeLists.txt`
(`FetchContent_Declare(JUCE …)`) to a newer stable JUCE tag.

## Status: all three built + verified (pedalboard load + process)

Verified on 2026-06-24, macOS arm64, with `pedalboard`. Each plugin loads,
processes a 1 s / 440 Hz sine at 44.1 kHz, and returns finite output:

```
===== freefx-eq =====
OK (1, 44100) True
params: ['hpf_freq', 'peak_freq', 'peak_gain', 'peak_q', 'shelf_freq', 'shelf_gain', 'bypass']
===== freefx-clipper =====
OK (1, 44100) True
params: ['drive', 'ceiling', 'hard', 'mix', 'bypass']
===== freefx-sat =====
OK (1, 44100) True
params: ['drive', 'bias', 'tone', 'mix', 'bypass']
```

(The `bypass` parameter is added automatically by the JUCE VST3 wrapper.)

### Non-passthrough check (clipper / sat actually alter driven audio)

`DIFF` = max absolute sample difference between output and the dry 440 Hz sine:

```
CLIPPER soft drive18 ceil-12: DIFF 0.18802 finite True
CLIPPER hard drive18 ceil-12: DIFF 0.22327 finite True
SAT drive18 bias.3:          DIFF 0.97951 finite True
SAT drive18 tone3k:          DIFF 0.9959  finite True
EQ peak+12@440:              DIFF 0.899   finite True
EQ flat peak:                DIFF 0.03667 finite True
```

The `EQ flat peak` case is small but non-zero by design: the 20 Hz HPF and the
high-shelf still impose phase shift on the 440 Hz tone even at 0 dB gain — that
is correct biquad behaviour, not a bug.

Reproduce any single check:

```bash
uv run --with pedalboard --with numpy --with soundfile python3 -c "from pedalboard import load_plugin; p=load_plugin('vst3/build/freefx_clipper_artefacts/Release/VST3/freefx-clipper.vst3'); import numpy as np; x=(0.3*np.sin(2*np.pi*440*np.arange(44100)/44100)).astype('float32').reshape(1,-1); y=p(x,44100); print('OK', y.shape, bool(np.all(np.isfinite(y))))"
```

## Implementation notes

- **Shared DSP** lives in `vst3/dsp/` (header-only): `Biquad.h` (RBJ coefficients +
  Direct-Form-II-Transposed per-channel state), `ToneFilter.h` (1-pole lowpass for
  the sat tone control), `DryDelay.h` (per-channel ring buffer to latency-align the
  dry path with the oversampler), `ParameterHelpers.h`.
- **Oversampling** (clipper + sat) uses `juce::dsp::Oversampling<float>` at 4× with
  the polyphase **IIR** half-band filter (lower latency than the FIR variant). The
  reported latency is rounded to whole samples and (a) declared via
  `setLatencySamples`, (b) applied to the dry path via `DryDelay` so the dry/wet
  `mix` stays phase-aligned. Plugin latency is reported to the host.
- **Filter / oversampler / tone state is held as members** and reset in
  `prepareToPlay`, never per-block, so there are no zipper/click artifacts at block
  boundaries.
- `ScopedNoDenormals` guards every `processBlock`; mono and stereo are supported and
  output channels beyond the input count are cleared.

## Scope / omissions (v1)

- **`sat.py` flutter** (tape wow/flutter via a modulated fractional delay) is **not**
  ported in v1. The `DryDelay` ring buffer infrastructure is already present, so a
  future LFO-modulated read-tap would be the natural extension.
- Oversampling is JUCE's stock 4× polyphase IIR half-band (matches the "oversampled
  4×" intent of `clipper.py` / `sat.py`; not the exact SciPy `resample_poly` kernel —
  the goal is anti-aliased waveshaping, which both achieve).
- VST3 format only (no AU/Standalone/AAX) to keep the build fast.
