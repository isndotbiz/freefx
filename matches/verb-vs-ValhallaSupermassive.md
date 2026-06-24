# Behavioural match: freefx `verb` vs `ValhallaSupermassive`

> **Method: black-box behavioural matching (legal, clean-room).** Probe signals are
> rendered through the proprietary plugin and the freefx module; only the *audio
> output* of the proprietary plugin is measured. Its binary, code, presets, and
> coefficients are never read, decompiled, or extracted. This is the lawful way
> clones are built (cf. Airwindows). See `matches/README.md`.

## Target (proprietary plugin configuration)
Plugin: `ValhallaSupermassive.vst3` — documented automation parameters set via pedalboard:
  - `mode` = `Gemini`
  - `mix` = `40.0`
  - `feedback` = `55.0`
  - `density` = `80.0`
  - `delay_ms` = `20.0`
  - `delaywarp` = `0.0`
  - `moddepth` = `30.0`
  - `modrate` = `0.5`
  - `width` = `100.0`
  - `lowcut` = `20.0`
  - `highcut` = `18000.0`

## Converged freefx parameters
```
uv run verb --roomsize 0.300 --damp 0.900 --wet 0.100
```

## Result
- **Mean null residual: -5.3 dB** (lower = closer; 0 dB = unrelated).
- Coarse-seed null was -4.7 dB; Nelder-Mead used 57 evaluations.
- Verdict: **Loose** — fundamentally different topology; only coarse spectral/decay match.

Reverb topologies differ fundamentally (Freeverb combs vs Valhalla's Supermassive network). A deep null is impossible; we match decay/tilt as best the params allow and report that honestly.

### Per-probe breakdown
| probe | null (dB) | Δ tilt (dB) | Δ LUFS (dB) |
|-------|-----------|-------------|-------------|
| sweep | -5.7 | +1.36 | +2.20 |
| impulse | -4.6 | -0.28 | +2.70 |
| noise | -4.8 | -0.30 | +2.20 |
| dynstep | -6.2 | -14.93 | +3.10 |

*Δ tilt / Δ LUFS = freefx output minus proprietary output. Near-zero = matched spectral balance and loudness.*
