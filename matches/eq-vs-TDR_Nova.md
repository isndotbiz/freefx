# Behavioural match: freefx `eq` vs `TDR Nova`

> **Method: black-box behavioural matching (legal, clean-room).** Probe signals are
> rendered through the proprietary plugin and the freefx module; only the *audio
> output* of the proprietary plugin is measured. Its binary, code, presets, and
> coefficients are never read, decompiled, or extracted. This is the lawful way
> clones are built (cf. Airwindows). See `matches/README.md`.

## Target (proprietary plugin configuration)
Plugin: `TDR Nova.vst3` — documented automation parameters set via pedalboard:
  - `eq_auto_gain` = `False`
  - `dry_mix` = `0.0`
  - `output_gain_db` = `0.0`
  - `band_1_active` = `True`
  - `band_1_type` = `Bell`
  - `band_1_dyn` = `Off`
  - `band_1_frequency_hz` = `300.0`
  - `band_1_gain_db` = `-4.0`
  - `band_1_q` = `1.0`
  - `band_2_active` = `False`
  - `band_3_active` = `False`
  - `band_4_active` = `False`
  - `hp_active` = `False`
  - `lp_active` = `False`

## Converged freefx parameters
```
uv run eq --band peak:300.1:-4.00:0.998
```

## Result
- **Mean null residual: -60.1 dB** (lower = closer; 0 dB = unrelated).
- Coarse-seed null was -53.8 dB; Nelder-Mead used 75 evaluations.
- Verdict: **Excellent** — deep null, behaviourally near-identical.

Static bell vs static biquad — should null very deeply (correctness check).

### Per-probe breakdown
| probe | null (dB) | Δ tilt (dB) | Δ LUFS (dB) |
|-------|-----------|-------------|-------------|
| sweep | -57.4 | +0.00 | +0.00 |
| impulse | -50.2 | +0.00 | +0.00 |
| noise | -50.2 | +0.00 | +0.00 |
| dynstep | -82.7 | +0.00 | +0.00 |

*Δ tilt / Δ LUFS = freefx output minus proprietary output. Near-zero = matched spectral balance and loudness.*
