# freefx behavioural matches

These reports are produced by `match.py`. Each tunes a freefx module's parameters
to **match the acoustic behaviour** of a proprietary plugin.

## The method is black-box behavioural matching (legal, clean-room)

We send test signals (a log sine sweep, an impulse, white noise, a loud/quiet
dynamics step, and a short real clip) through **both**:

1. the proprietary plugin (loaded with `pedalboard`, set to documented automation
   parameters), and
2. the open-source freefx module (`eq.py`, `dyneq.py`, `autotune.py`, `verb.py`).

We then **measure only the audio the proprietary plugin produces** and search the
freefx module's own parameter space (coarse grid → Nelder-Mead refine) to minimise
the gain- and time-aligned RMS difference (the "null residual") between the two
outputs, plus a small spectral-tilt term.

**What we never do:** decompile, disassemble, read the plugin binary, or extract
its code, coefficients, or presets. Measuring acoustic input→output is legal and is
exactly how Airwindows and other legitimate clones are built. Touching the binary is
what we deliberately avoid.

## What "close" means

- **EQ vs a static bell** nulls very deeply (tens of dB) — a biquad *is* the same
  math, so this is also our correctness check that the loop works.
- **Dynamic EQ / reverb / pitch** use *different topologies* from the proprietary
  plugin, so they will NOT null deeply. We report the honest residual and treat
  these as "same family of effect, approximated", never as exact clones.

## Run it

```bash
uv run match.py eq        # NOVA single bell  -> eq
uv run match.py dyneq     # NOVA dynamic de-ess -> dyneq
uv run match.py autotune  # Graillon A-minor  -> autotune (vocal stem)
uv run match.py verb      # Valhalla reverb   -> verb (approximate)
uv run match.py all       # every pair, all reports
```

Add `--quick` for a faster, lower-resolution search. Reports land in this folder
as `<module>-vs-<plugin>.md`.
