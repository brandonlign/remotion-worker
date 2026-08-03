from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

MODEL_URL = (
    "https://raw.githubusercontent.com/gustavz/AttractiveNet/"
    "master/models/attractiveNet_mnv2.h5"
)
TRAIN_URL = (
    "https://raw.githubusercontent.com/HCIILAB/SCUT-FBP5500-Database-Release/"
    "master/data/1/train_1.txt"
)
TEST_URL = (
    "https://raw.githubusercontent.com/HCIILAB/SCUT-FBP5500-Database-Release/"
    "master/data/1/test_1.txt"
)
EXPECTED_MODEL_SHA = "34284d986d8175d4e122cc94fb6138bab9269178"

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "mog-scut"
DOWNLOADS = ROOT / "build" / "downloads"
MODEL_H5 = DOWNLOADS / "attractiveNet_mnv2.h5"
TFJS_DIR = BUILD / "model"


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mog-SCUT-calibration-builder/1.0"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        destination.write_bytes(response.read())
    if destination.stat().st_size == 0:
        raise RuntimeError(f"Downloaded file is empty: {url}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_labels(*paths: Path) -> dict[str, float]:
    labels: dict[str, float] = {}
    for path in paths:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            file_name, score_text = line.split()
            score = float(score_text)
            existing = labels.get(file_name)
            if existing is not None and abs(existing - score) > 1e-9:
                raise RuntimeError(f"Conflicting score for {file_name}: {existing} vs {score}")
            labels[file_name] = score
    if len(labels) != 5500:
        raise RuntimeError(f"Expected 5,500 unique SCUT labels, found {len(labels)}")
    return labels


def percentile_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)

    def quantile(fraction: float) -> float:
        position = fraction * (len(ordered) - 1)
        low = int(position)
        high = min(low + 1, len(ordered) - 1)
        weight = position - low
        return ordered[low] * (1 - weight) + ordered[high] * weight

    return {
        "min": ordered[0],
        "p01": quantile(0.01),
        "p05": quantile(0.05),
        "p10": quantile(0.10),
        "p25": quantile(0.25),
        "median": quantile(0.50),
        "p75": quantile(0.75),
        "p90": quantile(0.90),
        "p95": quantile(0.95),
        "p99": quantile(0.99),
        "max": ordered[-1],
    }


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    TFJS_DIR.mkdir(parents=True, exist_ok=True)

    train_path = DOWNLOADS / "train_1.txt"
    test_path = DOWNLOADS / "test_1.txt"
    download(MODEL_URL, MODEL_H5)
    download(TRAIN_URL, train_path)
    download(TEST_URL, test_path)

    model_size = MODEL_H5.stat().st_size
    if model_size < 20_000_000:
        raise RuntimeError(f"Model download is unexpectedly small: {model_size} bytes")

    # Validate that Keras can deserialize the checkpoint before conversion and capture
    # the actual input/output shape so the browser implementation cannot guess it.
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    from tensorflow import keras  # pylint: disable=import-outside-toplevel

    model = keras.models.load_model(MODEL_H5, compile=False)
    input_shape = [dimension if dimension is not None else None for dimension in model.input_shape]
    output_shape = [dimension if dimension is not None else None for dimension in model.output_shape]

    subprocess.run(
        [
            "tensorflowjs_converter",
            "--input_format=keras",
            "--output_format=tfjs_layers_model",
            "--quantization_bytes=2",
            str(MODEL_H5),
            str(TFJS_DIR),
        ],
        check=True,
    )

    model_json = TFJS_DIR / "model.json"
    if not model_json.exists():
        raise RuntimeError("TensorFlow.js conversion did not create model.json")

    labels = parse_labels(train_path, test_path)
    ordered_scores = sorted(labels.values())
    groups: dict[str, list[float]] = {"AF": [], "AM": [], "CF": [], "CM": []}
    for file_name, score in labels.items():
        prefix = file_name[:2].upper()
        if prefix in groups:
            groups[prefix].append(score)

    distribution = {
        "benchmark": "SCUT-FBP5500",
        "sampleCount": len(ordered_scores),
        "ratingScale": {"minimum": 1, "maximum": 5, "ratersPerImage": 60},
        "sortedScores": [round(value, 6) for value in ordered_scores],
        "summary": percentile_summary(ordered_scores),
        "groups": {
            key: {
                "sampleCount": len(values),
                "summary": percentile_summary(values),
            }
            for key, values in groups.items()
        },
        "source": {
            "dataset": "HCIILAB/SCUT-FBP5500-Database-Release",
            "split": "official five-fold split 1 train + test (all 5,500 unique images)",
            "usage": "non-commercial research only; contact the dataset authors for commercial use",
        },
    }
    (BUILD / "distribution.json").write_text(
        json.dumps(distribution, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    metadata = {
        "benchmark": "SCUT-FBP5500",
        "model": "AttractiveNet MobileNetV2 regression checkpoint",
        "modelSource": "gustavz/AttractiveNet",
        "originalModelBytes": model_size,
        "originalModelSha256": sha256(MODEL_H5),
        "sourceBlobSha": EXPECTED_MODEL_SHA,
        "inputShape": input_shape,
        "outputShape": output_shape,
        "preprocessing": {
            "resize": [350, 350],
            "pixelScale": "RGB values divided by 255",
        },
        "reportedEvaluation": {
            "mae": 0.211983,
            "rmse": 0.285857,
            "note": "Metrics reported by the AttractiveNet repository on its held-out SCUT-FBP5500 test split.",
        },
        "percentileDefinition": (
            "Empirical percentile of the predicted 1–5 rating within all 5,500 "
            "SCUT-FBP5500 mean human ratings."
        ),
        "limitations": [
            "Front-view photographs only; the benchmark does not contain profile views.",
            "The benchmark includes Asian and Caucasian faces but does not represent all populations.",
            "Ratings reflect the benchmark raters and are not universal or objective attractiveness labels.",
            "The dataset and derived use are restricted to non-commercial research unless permission is obtained.",
        ],
    }
    (BUILD / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    manifest = {
        "files": {
            str(path.relative_to(BUILD)): {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in sorted(BUILD.rglob("*"))
            if path.is_file()
        }
    }
    (BUILD / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(json.dumps({
        "input_shape": input_shape,
        "output_shape": output_shape,
        "model_files": len(list(TFJS_DIR.glob("*"))),
        "artifact_bytes": sum(path.stat().st_size for path in BUILD.rglob("*") if path.is_file()),
        "rating_summary": distribution["summary"],
    }, indent=2))


if __name__ == "__main__":
    main()
