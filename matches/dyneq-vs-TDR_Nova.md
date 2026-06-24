# Behavioural match: freefx `dyneq` vs `TDR Nova`

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
  - `band_1_active` = `False`
  - `band_2_active` = `False`
  - `band_3_active` = `False`
  - `band_4_active` = `True`
  - `band_4_type` = `Bell`
  - `band_4_dyn` = `On`
  - `band_4_frequency_hz` = `7000.0`
  - `band_4_gain_db` = `0.0`
  - `band_4_q` = `2.0`
  - `band_4_threshold_db` = `-30.0`
  - `band_4_ratio` = `4.0`
  - `band_4_attack_ms` = `3.0`
  - `band_4_release_ms` = `120.0`
  - `hp_active` = `False`
  - `lp_active` = `False`

## Converged freefx parameters
```
uv run dyneq --band 7000:2.0:-45.0:7.13:cut --attack-ms 8.7 --release-ms 223.9
```

## Result
- **Mean null residual: -18.0 dB** (lower = closer; 0 dB = unrelated).
- Coarse-seed null was -13.3 dB; Nelder-Mead used 72 evaluations.
- Verdict: **Approximate** — same family of effect, topologies differ; broad match only.

Dynamic band — topology differs (NOVA split vs parallel-bandpass), expect a moderate null. Drive search with the dynamics-step probe.

### Per-probe breakdown
| probe | null (dB) | Δ tilt (dB) | Δ LUFS (dB) |
|-------|-----------|-------------|-------------|
| sweep | -12.1 | +5.28 | +1.50 |
| impulse | -37.2 | +0.06 | +0.00 |
| noise | -8.0 | +3.56 | +3.00 |
| dynstep | -14.5 | +0.01 | +0.30 |

*Δ tilt / Δ LUFS = freefx output minus proprietary output. Near-zero = matched spectral balance and loudness.*
