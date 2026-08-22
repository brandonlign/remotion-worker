#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("orbittrace_paper_hyperparam_robustness_v1")
OUT = Path("chunk-output")
OUT.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location("frozen_run", ROOT / "run.py")
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

canonical = pd.read_csv(
    ROOT / "canonical_2025_2026_ids.tsv",
    sep="\t",
    names=["year", "unique_trajectory_identifier"],
    dtype={"year": int, "unique_trajectory_identifier": str},
)
assert len(canonical) == 63 and canonical["unique_trajectory_identifier"].nunique() == 63

frames = [mod.load_month(2025), mod.load_month(2026)]
all_april = pd.concat(frames, ignore_index=True)
missing = sorted(set(canonical["unique_trajectory_identifier"]) - set(all_april["unique_trajectory_identifier"]))
if missing:
    raise RuntimeError(f"Canonical IDs absent after fixed manuscript quality/dedup filters: {missing}")

diagnostic = all_april.loc[
    np.abs(mod.circ_diff(all_april["sol_lon_deg"].to_numpy(float), mod.CENTER[3])) <= mod.SOL_HALF_WIDTH
].reset_index(drop=True)
missing_diag = sorted(set(canonical["unique_trajectory_identifier"]) - set(diagnostic["unique_trajectory_identifier"]))
if missing_diag:
    raise RuntimeError(f"Canonical IDs outside fixed diagnostic band: {missing_diag}")

settings = mod.build_settings()
assert len(settings) == 41
chunk = int(os.environ["CHUNK"])
start = chunk * 5
end = min(len(settings), start + 5)
if start >= len(settings):
    raise RuntimeError(f"empty chunk {chunk}")

rows = []
for i in range(start, end):
    sid, family, setting = settings[i]
    print(f"chunk={chunk} setting={i+1}/41 {sid} {setting}", flush=True)
    rows.append(mod.evaluate_setting(diagnostic, canonical, setting, sid, family))

pd.DataFrame(rows).to_csv(OUT / f"chunk_{chunk:02d}.csv", index=False)
(OUT / f"chunk_{chunk:02d}_input.json").write_text(json.dumps({
    "chunk": chunk,
    "start": start,
    "end": end,
    "quality_sporadics_2025": int(len(frames[0])),
    "quality_sporadics_2026": int(len(frames[1])),
    "quality_sporadics_pooled": int(len(all_april)),
    "diagnostic_rows": int(len(diagnostic)),
}, indent=2, sort_keys=True) + "\n")
