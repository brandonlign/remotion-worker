from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import urllib.request

import numpy as np

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
SOURCE_MODEL_BLOB_SHA = "34284d986d8175d4e122cc94fb6138bab9269178"

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "mog-scut"
DOWNLOADS = ROOT / "build" / "downloads"
MODEL_H5 = DOWNLOADS / "attractiveNet_mnv2.h5"
MODEL_DIR = BUILD / "model"
MODEL_ONNX = MODEL_DIR / "attractiveness.onnx"


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


def convert_and_validate_model() -> dict[str, object]:
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    import onnx  # pylint: disable=import-outside-toplevel
    import onnxruntime as ort  # pylint: disable=import-outside-toplevel
    import tensorflow as tf  # pylint: disable=import-outside-toplevel
    import tf2onnx  # pylint: disable=import-outside-toplevel

    model = tf.keras.models.load_model(MODEL_H5, compile=False)
    input_shape = [dimension if dimension is not None else None for dimension in model.input_shape]
    output_shape = [dimension if dimension is not None else None for dimension in model.output_shape]
    if input_shape != [None, 350, 350, 3]:
        raise RuntimeError(f"Unexpected AttractiveNet input shape: {input_shape}")
    if output_shape not in ([None, 1], [None]):
        raise RuntimeError(f"Unexpected AttractiveNet output shape: {output_shape}")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    input_name = model.inputs[0].name.split(":", maxsplit=1)[0]
    signature = (tf.TensorSpec(model.inputs[0].shape, tf.float32, name=input_name),)
    tf2onnx.convert.from_keras(
        model,
        input_signature=signature,
        opset=13,
        output_path=str(MODEL_ONNX),
    )

    onnx_model = onnx.load(MODEL_ONNX)
    onnx.checker.check_model(onnx_model)
    session = ort.InferenceSession(
        str(MODEL_ONNX),
        providers=["CPUExecutionProvider"],
    )
    session_input = session.get_inputs()[0]
    session_output = session.get_outputs()[0]

    # Deterministic parity check. The browser will use the same NHWC float32 input.
    test_input = np.linspace(
        0.0,
        1.0,
        num=350 * 350 * 3,
        dtype=np.float32,
    ).reshape(1, 350, 350, 3)
    keras_prediction = np.asarray(model.predict(test_input, verbose=0)).reshape(-1)
    onnx_prediction = np.asarray(
        session.run([session_output.name], {session_input.name: test_input})[0]
    ).reshape(-1)
    max_absolute_difference = float(np.max(np.abs(keras_prediction - onnx_prediction)))
    if max_absolute_difference > 1e-4:
        raise RuntimeError(
            "ONNX conversion parity check failed: "
            f"maximum absolute difference {max_absolute_difference}"
        )

    return {
        "inputShape": input_shape,
        "outputShape": output_shape,
        "onnxInputName": session_input.name,
        "onnxOutputName": session_output.name,
        "parity": {
            "kerasPrediction": float(keras_prediction[0]),
            "onnxPrediction": float(onnx_prediction[0]),
            "maxAbsoluteDifference": max_absolute_difference,
        },
    }


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    train_path = DOWNLOADS / "train_1.txt"
    test_path = DOWNLOADS / "test_1.txt"
    download(MODEL_URL, MODEL_H5)
    download(TRAIN_URL, train_path)
    download(TEST_URL, test_path)

    model_size = MODEL_H5.stat().st_size
    if model_size < 20_000_000:
        raise RuntimeError(f"Model download is unexpectedly small: {model_size} bytes")

    conversion = convert_and_validate_model()

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
        "runtimeFormat": "ONNX",
        "model": "AttractiveNet MobileNetV2 regression checkpoint",
        "modelSource": "gustavz/AttractiveNet",
        "originalModelBytes": model_size,
        "originalModelSha256": sha256(MODEL_H5),
        "sourceBlobSha": SOURCE_MODEL_BLOB_SHA,
        "convertedModelBytes": MODEL_ONNX.stat().st_size,
        **conversion,
        "preprocessing": {
            "resize": [350, 350],
            "pixelScale": "RGB values divided by 255",
            "layout": "NHWC",
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

    print(
        json.dumps(
            {
                "input_shape": conversion["inputShape"],
                "output_shape": conversion["outputShape"],
                "onnx_model_bytes": MODEL_ONNX.stat().st_size,
                "artifact_bytes": sum(
                    path.stat().st_size for path in BUILD.rglob("*") if path.is_file()
                ),
                "rating_summary": distribution["summary"],
                "parity": conversion["parity"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
