# /// script
# requires-python = ">=3.11"
# dependencies = ["pedalboard", "numpy"]
# ///
"""Load every built freefx VST3 with pedalboard and check finite, non-silent output.

Usage: uv run vst3/verify.py [vst3/build]
"""
import glob
import sys

import numpy as np
from pedalboard import load_plugin

SR = 48000
rng = np.random.default_rng(7)
audio = (rng.standard_normal((2, SR * 2)) * 0.1).astype(np.float32)

root = sys.argv[1] if len(sys.argv) > 1 else "vst3/build"
bundles = sorted(set(
    glob.glob(root + "/**/VST3/*.vst3", recursive=True)
    + glob.glob(root + "/*.vst3")
))
if not bundles:
    print("NO BUNDLES FOUND under", root)
    sys.exit(2)

failed = []
for b in bundles:
    name = b.rsplit("/", 1)[-1]
    try:
        plug = load_plugin(b)
        out = plug(audio, SR)
        finite = bool(np.all(np.isfinite(out)))
        nonsilent = bool(np.any(np.abs(out) > 0))
        ok = finite and nonsilent
        print(f"{name}: {'OK' if ok else f'BAD finite={finite} nonsilent={nonsilent}'}")
        if not ok:
            failed.append(name)
    except Exception as e:
        print(f"{name}: LOAD FAILED — {e}")
        failed.append(name)

print(f"\n{len(bundles) - len(failed)}/{len(bundles)} passed")
sys.exit(1 if failed else 0)
