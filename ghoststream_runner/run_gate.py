#!/usr/bin/env python3
"""Known-shower recovery gate for GhostStream using public GMN daily files."""
from __future__ import annotations

import json
import math
import re
import warnings
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from gmn_python_api import data_directory as dd
from gmn_python_api import meteor_trajectory_reader as reader
from sklearn.cluster import HDBSCAN

CALIBRATION = {
    "Quadrantids": ("2025-01-02", "2025-01-05"),
    "Perseids": ("2025-08-10", "2025-08-14"),
}
HELDOUT = {
    "Orionids": ("2025-10-19", "2025-10-23"),
    "Leonids": ("2025-11-15", "2025-11-19"),
    "Geminids": ("2025-12-11", "2025-12-15"),
}
PARAMS = [
    {"min_cluster_size": 25, "min_samples": 8, "scales": [2.5, 2.5, 2.0, 2.0]},
    {"min_cluster_size": 40, "min_samples": 10, "scales": [2.5, 2.5, 2.0, 2.0]},
    {"min_cluster_size": 25, "min_samples": 8, "scales": [4.0, 4.0, 3.0, 3.0]},
    {"min_cluster_size": 40, "min_samples": 10, "scales": [4.0, 4.0, 3.0, 3.0]},
]
MAX_ROWS = 40000
SEED = 20260731


@dataclass
class Score:
    shower: str
    true_count: int
    cluster: int | None
    cluster_size: int
    precision: float
    recall: float
    f1: float
    recovered: bool


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def pick(columns: list[str], choices: list[tuple[str, ...]]) -> str:
    normalized = {column: norm(column) for column in columns}
    for choice in choices:
        terms = [norm(term) for term in choice]
        found = [column for column, value in normalized.items() if all(term in value for term in terms)]
        if found:
            return min(found, key=len)
    raise KeyError(f"No column matched {choices}; columns={columns}")


def columns(frame: pd.DataFrame) -> dict[str, str]:
    cols = list(map(str, frame.columns))
    return {
        "sol": pick(cols, [("sol", "lon", "deg"), ("solar", "longitude")]),
        "lam": pick(cols, [("lamgeo", "deg"), ("geocentric", "ecliptic", "longitude")]),
        "bet": pick(cols, [("betgeo", "deg"), ("geocentric", "ecliptic", "latitude")]),
        "vel": pick(cols, [("vgeo", "km", "s"), ("geocentric", "velocity")]),
        "label": pick(cols, [("iau", "code"), ("shower", "code"), ("shower", "iau", "no"), ("iau", "no")]),
    }


def days(start: str, end: str):
    current, final = date.fromisoformat(start), date.fromisoformat(end)
    while current <= final:
        yield current.isoformat()
        current += timedelta(days=1)


def load_window(name: str, start: str, end: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    frames, log = [], []
    for day in days(start, end):
        try:
            text = dd.get_daily_file_content_by_date(day)
            frame = reader.read_data(text, output_camel_case=True).reset_index(drop=False)
            frames.append(frame)
            log.append({"date": day, "rows": int(len(frame))})
            print(f"{name} {day}: {len(frame):,} rows", flush=True)
        except Exception as exc:
            log.append({"date": day, "error": f"{type(exc).__name__}: {exc}"})
            print(f"{name} {day}: ERROR {exc}", flush=True)
    if not frames:
        raise RuntimeError(f"No readable files for {name}")
    frame = pd.concat(frames, ignore_index=True, sort=False)
    return frame, {"start": start, "end": end, "days": log, "raw_rows": int(len(frame))}


def label(value: Any) -> str:
    if pd.isna(value):
        return "SPORADIC"
    text = str(value).strip().upper()
    if text.endswith(".0") and text[:-2].lstrip("-").isdigit():
        text = text[:-2]
    return "SPORADIC" if text in {"", "-1", "...", "NONE", "NAN", "SPO", "SPORADIC", "0"} else text


def circ_center(values: np.ndarray) -> float:
    radians = np.deg2rad(values)
    return float(np.rad2deg(math.atan2(float(np.sin(radians).mean()), float(np.cos(radians).mean()))) % 360)


def circ_diff(values: np.ndarray, center: np.ndarray | float) -> np.ndarray:
    return (values - center + 180.0) % 360.0 - 180.0


def prepare(frame: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, np.ndarray, dict[str, Any]]:
    col = columns(frame)
    data = pd.DataFrame({
        "sol": pd.to_numeric(frame[col["sol"]], errors="coerce"),
        "lam": pd.to_numeric(frame[col["lam"]], errors="coerce"),
        "bet": pd.to_numeric(frame[col["bet"]], errors="coerce"),
        "vel": pd.to_numeric(frame[col["vel"]], errors="coerce"),
        "label": frame[col["label"]].map(label),
    })
    valid = np.isfinite(data[["sol", "lam", "bet", "vel"]]).all(axis=1)
    valid &= data["sol"].between(0, 360) & data["lam"].between(0, 360)
    valid &= data["bet"].between(-90, 90) & data["vel"].between(5, 75)
    data = data.loc[valid].reset_index(drop=True)
    quality_rows = len(data)
    if len(data) > MAX_ROWS:
        data = data.sample(MAX_ROWS, random_state=seed).sort_index().reset_index(drop=True)
    sol, lam = data["sol"].to_numpy(float), data["lam"].to_numpy(float)
    center = circ_center(sol)
    features = np.column_stack([
        circ_diff(lam, sol),
        data["bet"].to_numpy(float),
        data["vel"].to_numpy(float),
        circ_diff(sol, center),
    ])
    meta = {
        "columns": col,
        "quality_rows": quality_rows,
        "sampled_rows": len(data),
        "solar_longitude_center": center,
        "top_labels": {str(k): int(v) for k, v in data["label"].value_counts().head(15).items()},
    }
    return data, features, meta


def eligible(labels: pd.Series) -> list[str]:
    counts = labels.value_counts()
    threshold = max(40, math.ceil(len(labels) * 0.001))
    return list(map(str, counts[(counts.index != "SPORADIC") & (counts >= threshold)].head(4).index))


def score(labels: pd.Series, clusters: np.ndarray) -> list[Score]:
    truth = labels.to_numpy(str)
    cluster_ids = [int(x) for x in np.unique(clusters) if int(x) >= 0]
    output = []
    for shower in eligible(labels):
        actual = truth == shower
        total = int(actual.sum())
        best = None
        for cluster in cluster_ids:
            predicted = clusters == cluster
            tp = int(np.sum(actual & predicted))
            if not tp:
                continue
            size = int(predicted.sum())
            precision, recall = tp / size, tp / total
            f1 = 2 * precision * recall / (precision + recall)
            candidate = Score(shower, total, cluster, size, precision, recall, f1,
                              precision >= 0.35 and recall >= 0.35 and f1 >= 0.35)
            if best is None or candidate.f1 > best.f1:
                best = candidate
        output.append(best or Score(shower, total, None, 0, 0, 0, 0, False))
    return output


def run(features: np.ndarray, labels: pd.Series, setting: dict[str, Any]) -> dict[str, Any]:
    model = HDBSCAN(
        min_cluster_size=setting["min_cluster_size"],
        min_samples=setting["min_samples"],
        cluster_selection_method="leaf",
        leaf_size=60,
        n_jobs=-1,
    )
    clusters = model.fit_predict(features / np.asarray(setting["scales"])[None, :])
    scores = score(labels, clusters)
    sizes = pd.Series(clusters[clusters >= 0]).value_counts()
    return {
        "setting": setting,
        "clusters": int(len(sizes)),
        "noise_fraction": float(np.mean(clusters < 0)),
        "largest_cluster_fraction": float(sizes.max() / len(clusters)) if len(sizes) else 0,
        "eligible": len(scores),
        "recovered": sum(item.recovered for item in scores),
        "macro_f1": float(np.mean([item.f1 for item in scores])) if scores else 0,
        "scores": [asdict(item) for item in scores],
    }


def main() -> int:
    out = Path("ghoststream_results")
    out.mkdir(exist_ok=True)
    prepared, metadata = {}, {}
    for index, (name, window) in enumerate({**CALIBRATION, **HELDOUT}.items()):
        frame, download = load_window(name, *window)
        data, features, prep = prepare(frame, SEED + index)
        prepared[name] = (data, features)
        metadata[name] = {**download, **prep}
        print(f"{name}: prepared={len(data):,}; eligible={eligible(data['label'])}", flush=True)

    calibration = {}
    best, best_objective = None, None
    for setting in PARAMS:
        results = {name: run(prepared[name][1], prepared[name][0]["label"], setting) for name in CALIBRATION}
        n = sum(item["eligible"] for item in results.values())
        recovered = sum(item["recovered"] for item in results.values())
        macro = float(np.mean([item["macro_f1"] for item in results.values()]))
        largest = max(item["largest_cluster_fraction"] for item in results.values())
        objective = (recovered / n if n else 0, macro, -largest)
        key = json.dumps(setting, sort_keys=True)
        calibration[key] = {"eligible": n, "recovered": recovered, "macro_f1": macro, "largest": largest, "windows": results}
        print(f"calibration {key}: recovered={recovered}/{n}; macro_f1={macro:.3f}", flush=True)
        if best_objective is None or objective > best_objective:
            best, best_objective = setting, objective

    heldout = {name: run(prepared[name][1], prepared[name][0]["label"], best) for name in HELDOUT}
    n = sum(item["eligible"] for item in heldout.values())
    recovered = sum(item["recovered"] for item in heldout.values())
    rate = recovered / n if n else 0
    largest = max((item["largest_cluster_fraction"] for item in heldout.values()), default=1)
    if n < 3:
        verdict = "INCONCLUSIVE_TOO_FEW_HELDOUT_CONTROLS"
    elif largest > 0.30:
        verdict = "NO_GO_DEGENERATE_GIANT_CLUSTER"
    elif rate >= 0.80:
        verdict = "RECOVERY_GATE_PASS"
    else:
        verdict = "RECOVERY_GATE_FAIL"

    summary = {
        "pilot": "GhostStream",
        "stage": "known_shower_recovery_gate",
        "labels_hidden_during_clustering": True,
        "calibration_windows": CALIBRATION,
        "heldout_windows": HELDOUT,
        "parameter_grid": PARAMS,
        "selected_setting": best,
        "frozen_recovery_rule": {"precision": 0.35, "recall": 0.35, "f1": 0.35},
        "frozen_pass_rule": {"minimum_controls": 3, "minimum_rate": 0.80, "maximum_largest_cluster_fraction": 0.30},
        "heldout_eligible": n,
        "heldout_recovered": recovered,
        "heldout_recovery_rate": rate,
        "heldout_largest_cluster_fraction": largest,
        "verdict": verdict,
        "metadata": metadata,
        "calibration": calibration,
        "heldout": heldout,
    }
    metrics = out / "ghoststream_recovery_gate.json"
    metrics.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    lines = [
        "# GhostStream known-shower recovery gate", "", f"**Verdict:** `{verdict}`", "",
        f"- Held-out controls recovered: **{recovered}/{n}** ({rate:.1%})",
        f"- Largest held-out cluster fraction: **{largest:.1%}**",
        f"- Selected setting: `{best}`", "", "## Held-out windows", "",
    ]
    for name, item in heldout.items():
        lines.append(f"- **{name}:** {item['recovered']}/{item['eligible']} recovered; macro F1={item['macro_f1']:.3f}; noise={item['noise_fraction']:.1%}")
        for result in item["scores"]:
            lines.append(f"  - `{result['shower']}`: n={result['true_count']}, precision={result['precision']:.3f}, recall={result['recall']:.3f}, F1={result['f1']:.3f}, recovered={result['recovered']}")
    lines += ["", "Shower labels were used only after clustering to score recovery.", "Passing authorizes null-catalog and weak-stream injection tests; it does not claim a discovery.", ""]
    report = out / "GHOSTSTREAM_RECOVERY_GATE.md"
    report.write_text("\n".join(lines))
    print(f"\nVerdict: {verdict}")
    print(f"Held-out controls recovered: {recovered}/{n}")
    print(f"Held-out recovery rate: {rate:.6f}")
    print(f"Largest held-out cluster fraction: {largest:.6f}")
    print(f"Selected setting: {json.dumps(best, sort_keys=True)}")
    print(f"Report: {report}")
    print(f"Metrics: {metrics}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    raise SystemExit(main())
