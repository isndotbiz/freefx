# Behavioural match: freefx `autotune` vs `Auburn Sounds Graillon 3`

> **Method: black-box behavioural matching (legal, clean-room).** Probe signals are
> rendered through the proprietary plugin and the freefx module; only the *audio
> output* of the proprietary plugin is measured. Its binary, code, presets, and
> coefficients are never read, decompiled, or extracted. This is the lawful way
> clones are built (cf. Airwindows). See `matches/README.md`.

## Target (proprietary plugin configuration)
Plugin: `Auburn Sounds Graillon 3.vst3` — documented automation parameters set via pedalboard:
  - `correction` = `True`
  - `corr_amount` = `100.0`
  - `formant` = `False`
  - `formant_amount` = `100.0`
  - `pitch_shift_st` = `0.0`
  - `formant_shift_st` = `0.0`
  - `reference_hz` = `440.0`
  - `wet_mix_db` = `0.0`
  - `dry_mix_db` = `-inf`
  - `chorus` = `False`
  - `preamp` = `False`
  - `allow_a` = `True`
  - `allow_b` = `True`
  - `allow_c` = `True`
  - `allow_d` = `True`
  - `allow_e` = `True`
  - `allow_f` = `True`
  - `allow_g` = `True`
  - `allow_a_sharp` = `False`
  - `allow_c_sharp` = `False`
  - `allow_d_sharp` = `False`
  - `allow_f_sharp` = `False`
  - `allow_g_sharp` = `False`

## Converged freefx parameters
```
uv run autotune --key A --scale minor --retune-ms 0.0 --strength 0.500
```

## Result
- **Median F0 agreement: 50.1 cents** (0 = identical pitch; a waveform null is meaningless under pitch shift).
- Verdict: **Loose** — only broad pitch-class agreement.

Pitch correction — different engines (WORLD vocoder vs Graillon's proprietary PSOLA-class shifter). A waveform null is MEANINGLESS here: any pitch shift fully decorrelates the wave (even Graillon-vs-its-own-input nulls at 0 dB). So this pair is scored by F0-contour agreement in cents — how closely the two engines snap pitch to the same A-minor notes. Vocal stem only.

### Per-probe breakdown
| probe | F0 diff (cents) | Δ tilt (dB) |
|-------|-----------------|-------------|
| clip | 50.1 | -2.95 |

*F0 diff = median absolute cents difference between the two engines' pitch contours. Δ tilt = freefx minus proprietary spectral balance.*
