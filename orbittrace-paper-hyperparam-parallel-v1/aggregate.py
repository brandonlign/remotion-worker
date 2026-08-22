#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path("all-chunks")
OUT = Path("aggregate-output")
OUT.mkdir(parents=True, exist_ok=True)
files = sorted(ROOT.rglob("chunk_*.csv"))
if not files:
    raise RuntimeError("no chunk CSVs found")
frame = pd.concat([pd.read_csv(p) for p in files], ignore_index=True)
if len(frame) != 41 or frame["setting_id"].nunique() != 41:
    raise RuntimeError(f"expected 41 unique settings; got rows={len(frame)} unique={frame['setting_id'].nunique()}")

metrics = {}
for col in ["precision", "recall", "f1", "jaccard", "nearest_centroid_distance"]:
    vals = pd.to_numeric(frame[col], errors="coerce").dropna()
    metrics[col] = {"min": float(vals.min()), "median": float(vals.median()), "max": float(vals.max())}
fractions = {str(t): float((frame["recall"] >= t).mean()) for t in [0.50, 0.75, 0.90]}
both8 = float(((frame["year_2025_overlap"] >= 8) & (frame["year_2026_overlap"] >= 8)).mean())
assoc_frac = float((frame["associated_clusters"] > 0).mean())
baseline = frame.loc[frame["setting_id"] == "baseline"]
if len(baseline) != 1:
    raise RuntimeError("baseline setting missing or duplicated")
b = baseline.iloc[0]

result = {
    "protocol": "orbittrace_paper_hyperparam_robustness_v1",
    "settings": 41,
    "recall_threshold_fractions": fractions,
    "both_years_overlap_at_least_8_fraction": both8,
    "associated_cluster_fraction": assoc_frac,
    "metric_summary": metrics,
    "baseline": {k: (v.item() if hasattr(v, "item") else v) for k, v in b.to_dict().items()},
    "claim_boundary": "Retrospective target-association robustness only; the 41-setting scientific grid and association rule were frozen before execution, and no setting was selected from the result.",
}

lines = [
    "# OrbitTrace ACRF/HDBSCAN hyperparameter robustness v1 — result",
    "",
    "The scientific grid and association rule were frozen before execution. Forty-one settings were evaluated: the baseline plus one-factor perturbations of all four metric scales and both HDBSCAN support parameters, together with 16 joint low/high corner stresses.",
    "",
    "## Baseline in the fixed 25-degree diagnostic band",
    "",
    f"Associated leaves: {int(b['associated_clusters'])}; union size: {int(b['associated_union_members'])}; canonical overlap: {int(b['canonical_overlap'])}/63; precision={b['precision']:.3f}; recall={b['recall']:.3f}; F1={b['f1']:.3f}; Jaccard={b['jaccard']:.3f}; year overlaps={int(b['year_2025_overlap'])}/34 (2025) and {int(b['year_2026_overlap'])}/29 (2026).",
    "",
    "## Across all 41 frozen settings",
    "",
    f"- OrbitTrace-associated density structure found: {assoc_frac*100:.1f}% of settings",
    f"- canonical recall >= 0.50: {fractions['0.5']*100:.1f}%",
    f"- canonical recall >= 0.75: {fractions['0.75']*100:.1f}%",
    f"- canonical recall >= 0.90: {fractions['0.9']*100:.1f}%",
    f"- both 2025 and 2026 retain >=8 canonical members: {both8*100:.1f}%",
    f"- recall min/median/max: {metrics['recall']['min']:.3f} / {metrics['recall']['median']:.3f} / {metrics['recall']['max']:.3f}",
    f"- precision min/median/max: {metrics['precision']['min']:.3f} / {metrics['precision']['median']:.3f} / {metrics['precision']['max']:.3f}",
    f"- F1 min/median/max: {metrics['f1']['min']:.3f} / {metrics['f1']['median']:.3f} / {metrics['f1']['max']:.3f}",
    f"- Jaccard min/median/max: {metrics['jaccard']['min']:.3f} / {metrics['jaccard']['median']:.3f} / {metrics['jaccard']['max']:.3f}",
    f"- nearest-centroid standardized distance min/median/max: {metrics['nearest_centroid_distance']['min']:.3f} / {metrics['nearest_centroid_distance']['median']:.3f} / {metrics['nearest_centroid_distance']['max']:.3f}",
    "",
    "## Claim boundary",
    "",
    result["claim_boundary"],
]

frame.to_csv(OUT / "settings.csv", index=False)
(OUT / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
(OUT / "RESULT.md").write_text("\n".join(lines) + "\n")
print((OUT / "RESULT.md").read_text())
