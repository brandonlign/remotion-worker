from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable

import cv2
import mediapipe as mp
import numpy as np
from scipy.stats import pearsonr, spearmanr
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import StandardScaler

DATASET_NAME = "SCUT-FBP5500"
DATASET_SIZE = 5500
CROP_SIZE = 24
RIGHT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
LEFT_EYE = [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466]
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
RIGHT_BROW = [46, 53, 52, 65, 55, 70, 63, 105, 66, 107]
LEFT_BROW = [276, 283, 282, 295, 285, 300, 293, 334, 296, 336]
NOSE = [1, 2, 4, 5, 6, 19, 45, 48, 49, 64, 94, 97, 98, 168, 195, 197, 278, 279, 294, 326, 327]
MOUTH = [0, 13, 14, 17, 37, 39, 40, 61, 78, 80, 81, 82, 84, 87, 88, 91, 95, 146, 178, 181, 185, 191, 267, 269, 270, 291, 308, 310, 311, 312, 314, 317, 318, 321, 324, 375, 402, 405, 409, 415]


def unique(values: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    output: list[int] = []
    for value in values:
        if value not in seen:
            output.append(value)
            seen.add(value)
    return output


SELECTED_INDICES = unique(FACE_OVAL + RIGHT_EYE + LEFT_EYE + RIGHT_BROW + LEFT_BROW + NOSE + MOUTH)
ALPHAS = [10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0]


def parse_labels(official_repo: Path) -> tuple[dict[str, float], dict[str, int]]:
    labels: dict[str, float] = {}
    fold_by_name: dict[str, int] = {}
    data_root = official_repo / "data"
    for fold in range(1, 6):
        fold_root = data_root / str(fold)
        for split in ("train", "test"):
            path = fold_root / f"{split}_{fold}.txt"
            if not path.exists():
                raise FileNotFoundError(f"Missing official split file: {path}")
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                name, score_text = line.split()
                score = float(score_text)
                previous = labels.get(name)
                if previous is not None and not math.isclose(previous, score, abs_tol=1e-7):
                    raise ValueError(f"Conflicting score for {name}: {previous} vs {score}")
                labels[name] = score
                if split == "test":
                    if name in fold_by_name:
                        raise ValueError(f"{name} appears in more than one official test fold")
                    fold_by_name[name] = fold - 1
    if len(labels) != DATASET_SIZE:
        raise ValueError(f"Expected {DATASET_SIZE} labels, found {len(labels)}")
    if len(fold_by_name) != DATASET_SIZE:
        raise ValueError(f"Expected each sample in one test fold, found {len(fold_by_name)}")
    return labels, fold_by_name


def find_images(dataset_root: Path) -> dict[str, Path]:
    images: dict[str, Path] = {}
    for extension in ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"):
        for path in dataset_root.rglob(extension):
            if path.name in images and images[path.name] != path:
                raise ValueError(f"Duplicate image filename: {path.name}")
            images[path.name] = path
    return images


def eye_center(points: np.ndarray, indices: list[int]) -> np.ndarray:
    return points[np.asarray(indices, dtype=np.int32)].mean(axis=0)


def aligned_geometry(points: np.ndarray) -> np.ndarray | None:
    right_eye = eye_center(points, RIGHT_EYE)
    left_eye = eye_center(points, LEFT_EYE)
    delta = left_eye - right_eye
    eye_distance = float(np.linalg.norm(delta))
    if eye_distance < 1e-6:
        return None
    midpoint = (right_eye + left_eye) / 2.0
    theta = math.atan2(float(delta[1]), float(delta[0]))
    angle = -theta
    cosine = math.cos(angle)
    sine = math.sin(angle)
    centered = points[np.asarray(SELECTED_INDICES, dtype=np.int32)] - midpoint
    aligned = np.empty_like(centered, dtype=np.float32)
    aligned[:, 0] = cosine * centered[:, 0] - sine * centered[:, 1]
    aligned[:, 1] = sine * centered[:, 0] + cosine * centered[:, 1]
    aligned /= eye_distance
    flat = aligned.reshape(-1)
    return np.concatenate([flat, np.square(flat)], dtype=np.float32)


def aligned_crop(image_rgb: np.ndarray, points: np.ndarray) -> np.ndarray | None:
    right_eye = eye_center(points, RIGHT_EYE)
    left_eye = eye_center(points, LEFT_EYE)
    delta = left_eye - right_eye
    eye_distance = float(np.linalg.norm(delta))
    if eye_distance < 1e-6:
        return None
    midpoint = (right_eye + left_eye) / 2.0
    direction = delta / eye_distance
    downward = np.asarray([-direction[1], direction[0]], dtype=np.float32)
    source = np.asarray(
        [right_eye, left_eye, midpoint + downward * eye_distance],
        dtype=np.float32,
    )
    edge = float(CROP_SIZE - 1)
    destination_right = np.asarray([0.32 * edge, 0.38 * edge], dtype=np.float32)
    destination_left = np.asarray([0.68 * edge, 0.38 * edge], dtype=np.float32)
    destination_midpoint = (destination_right + destination_left) / 2.0
    destination = np.asarray(
        [
            destination_right,
            destination_left,
            destination_midpoint + np.asarray([0.0, 0.36 * edge], dtype=np.float32),
        ],
        dtype=np.float32,
    )
    transform = cv2.getAffineTransform(source, destination)
    crop = cv2.warpAffine(
        image_rgb,
        transform,
        (CROP_SIZE, CROP_SIZE),
        flags=cv2.INTER_AREA,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    return crop.astype(np.float32).reshape(-1) / 255.0


def extract_features(
    names: list[str],
    image_paths: dict[str, Path],
) -> tuple[np.ndarray, list[str], list[str]]:
    features: list[np.ndarray] = []
    accepted: list[str] = []
    failures: list[str] = []
    face_mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=False,
        min_detection_confidence=0.5,
    )
    try:
        for position, name in enumerate(names, start=1):
            path = image_paths.get(name)
            if path is None:
                failures.append(f"{name}:missing-image")
                continue
            image_bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image_bgr is None:
                failures.append(f"{name}:decode-failed")
                continue
            image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
            result = face_mesh.process(image_rgb)
            if not result.multi_face_landmarks or len(result.multi_face_landmarks) != 1:
                failures.append(f"{name}:face-detection-failed")
                continue
            height, width = image_rgb.shape[:2]
            landmarks = result.multi_face_landmarks[0].landmark
            if len(landmarks) < 468:
                failures.append(f"{name}:insufficient-landmarks")
                continue
            points = np.asarray(
                [[landmark.x * width, landmark.y * height] for landmark in landmarks[:468]],
                dtype=np.float32,
            )
            geometry = aligned_geometry(points)
            appearance = aligned_crop(image_rgb, points)
            if geometry is None or appearance is None or not np.all(np.isfinite(geometry)):
                failures.append(f"{name}:feature-failed")
                continue
            features.append(np.concatenate([geometry, appearance], dtype=np.float32))
            accepted.append(name)
            if position % 250 == 0 or position == len(names):
                print(f"Processed {position}/{len(names)}; accepted={len(accepted)} failures={len(failures)}", flush=True)
    finally:
        face_mesh.close()
    if not features:
        raise RuntimeError("No usable SCUT features were extracted")
    return np.vstack(features), accepted, failures


def evaluate_model(
    features: np.ndarray,
    ratings: np.ndarray,
    folds: np.ndarray,
    alpha: float,
) -> tuple[np.ndarray, list[dict[str, float]]]:
    predictions = np.full(ratings.shape, np.nan, dtype=np.float64)
    fold_metrics: list[dict[str, float]] = []
    for fold in range(5):
        train_mask = folds != fold
        test_mask = folds == fold
        scaler = StandardScaler()
        train_features = scaler.fit_transform(features[train_mask])
        test_features = scaler.transform(features[test_mask])
        model = Ridge(alpha=alpha, solver="lsqr", tol=1e-5, max_iter=10000)
        model.fit(train_features, ratings[train_mask])
        fold_prediction = np.clip(model.predict(test_features), 1.0, 5.0)
        predictions[test_mask] = fold_prediction
        truth = ratings[test_mask]
        fold_metrics.append(
            {
                "fold": fold + 1,
                "samples": int(test_mask.sum()),
                "pearson": float(pearsonr(truth, fold_prediction).statistic),
                "spearman": float(spearmanr(truth, fold_prediction).statistic),
                "mae": float(mean_absolute_error(truth, fold_prediction)),
                "rmse": float(math.sqrt(mean_squared_error(truth, fold_prediction))),
            }
        )
    if np.any(~np.isfinite(predictions)):
        raise RuntimeError("Out-of-fold predictions were incomplete")
    return predictions, fold_metrics


def rounded(values: np.ndarray, digits: int = 7) -> list[float]:
    return np.round(values.astype(np.float64), digits).tolist()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--official-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".cache/mog-scut-features.npz"))
    args = parser.parse_args()

    labels, fold_by_name = parse_labels(args.official_repo)
    names = sorted(labels)
    image_paths = find_images(args.dataset_root)
    print(f"Found {len(image_paths)} image files under {args.dataset_root}", flush=True)

    if args.cache.exists():
        cache = np.load(args.cache, allow_pickle=False)
        features = cache["features"]
        accepted = cache["names"].astype(str).tolist()
        failures = cache["failures"].astype(str).tolist()
        print(f"Loaded cached features for {len(accepted)} faces", flush=True)
    else:
        features, accepted, failures = extract_features(names, image_paths)
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            args.cache,
            features=features,
            names=np.asarray(accepted),
            failures=np.asarray(failures),
        )

    ratings = np.asarray([labels[name] for name in accepted], dtype=np.float64)
    folds = np.asarray([fold_by_name[name] for name in accepted], dtype=np.int32)
    detection_rate = len(accepted) / len(names)
    print(f"Feature matrix {features.shape}; detection rate={detection_rate:.4f}", flush=True)

    candidates: list[dict[str, float]] = []
    best_alpha = ALPHAS[0]
    best_pearson = -1.0
    best_predictions: np.ndarray | None = None
    best_fold_metrics: list[dict[str, float]] = []
    for alpha in ALPHAS:
        predictions, fold_metrics = evaluate_model(features, ratings, folds, alpha)
        pearson = float(pearsonr(ratings, predictions).statistic)
        spearman = float(spearmanr(ratings, predictions).statistic)
        mae = float(mean_absolute_error(ratings, predictions))
        rmse = float(math.sqrt(mean_squared_error(ratings, predictions)))
        candidates.append(
            {
                "alpha": alpha,
                "pearson": pearson,
                "spearman": spearman,
                "mae": mae,
                "rmse": rmse,
            }
        )
        print(f"alpha={alpha:g} pearson={pearson:.4f} spearman={spearman:.4f} mae={mae:.4f} rmse={rmse:.4f}", flush=True)
        if pearson > best_pearson:
            best_pearson = pearson
            best_alpha = alpha
            best_predictions = predictions
            best_fold_metrics = fold_metrics

    assert best_predictions is not None
    scaler = StandardScaler()
    standardized = scaler.fit_transform(features)
    final_model = Ridge(alpha=best_alpha, solver="lsqr", tol=1e-5, max_iter=10000)
    final_model.fit(standardized, ratings)
    final_training_predictions = np.clip(final_model.predict(standardized), 1.0, 5.0)

    overall_metrics = {
        "pearson": float(pearsonr(ratings, best_predictions).statistic),
        "spearman": float(spearmanr(ratings, best_predictions).statistic),
        "mae": float(mean_absolute_error(ratings, best_predictions)),
        "rmse": float(math.sqrt(mean_squared_error(ratings, best_predictions))),
    }
    enabled = bool(
        detection_rate >= 0.90
        and overall_metrics["pearson"] >= 0.55
        and overall_metrics["spearman"] >= 0.52
    )

    output = {
        "schemaVersion": 1,
        "modelVersion": "scut-fbp5500-aligned-ridge-v1",
        "createdBy": "scripts/calibrate_mog_scut.py",
        "dataset": {
            "name": DATASET_NAME,
            "totalFaces": DATASET_SIZE,
            "ratedBy": 60,
            "ratingScale": [1, 5],
            "scope": "Frontal faces in the SCUT-FBP5500 benchmark only",
            "license": "Non-commercial research use only; see the official SCUT-FBP5500 repository.",
        },
        "percentileDefinition": "Empirical percentile of the model prediction relative to out-of-fold predictions for accepted SCUT-FBP5500 faces.",
        "enabled": enabled,
        "gate": {
            "minimumDetectionRate": 0.90,
            "minimumPearson": 0.55,
            "minimumSpearman": 0.52,
        },
        "samples": {
            "accepted": len(accepted),
            "failed": len(failures),
            "detectionRate": detection_rate,
            "failureExamples": failures[:50],
        },
        "features": {
            "cropSize": CROP_SIZE,
            "selectedLandmarkIndices": SELECTED_INDICES,
            "rightEyeIndices": RIGHT_EYE,
            "leftEyeIndices": LEFT_EYE,
            "geometryIncludesSquares": True,
            "appearance": "Eye-aligned 24x24 RGB crop flattened in RGB order and scaled to [0,1]",
            "featureCount": int(features.shape[1]),
        },
        "validation": {
            "protocol": "Official five-fold splits with strictly out-of-fold predictions",
            "selectedAlpha": best_alpha,
            "overall": overall_metrics,
            "folds": best_fold_metrics,
            "alphaCandidates": candidates,
        },
        "model": {
            "type": "standardized-ridge",
            "alpha": best_alpha,
            "intercept": round(float(final_model.intercept_), 7),
            "mean": rounded(scaler.mean_),
            "scale": rounded(scaler.scale_),
            "coefficients": rounded(final_model.coef_),
            "predictionClamp": [1, 5],
        },
        "calibration": {
            "oofPredictionCdf": rounded(np.sort(best_predictions)),
            "oofRatingCdf": rounded(np.sort(ratings)),
            "finalTrainingPredictionRange": [
                round(float(final_training_predictions.min()), 7),
                round(float(final_training_predictions.max()), 7),
            ],
            "uncertaintyRatingRmse": round(overall_metrics["rmse"], 7),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, separators=(",", ":")), encoding="utf-8")
    report_path = args.output.with_suffix(".md")
    report_path.write_text(
        "\n".join(
            [
                "# Mog SCUT-FBP5500 calibration",
                "",
                f"- Enabled: **{enabled}**",
                f"- Accepted faces: **{len(accepted)} / {len(names)}** ({detection_rate:.2%})",
                f"- Selected ridge alpha: **{best_alpha:g}**",
                f"- Out-of-fold Pearson: **{overall_metrics['pearson']:.4f}**",
                f"- Out-of-fold Spearman: **{overall_metrics['spearman']:.4f}**",
                f"- Out-of-fold MAE: **{overall_metrics['mae']:.4f}** rating points",
                f"- Out-of-fold RMSE: **{overall_metrics['rmse']:.4f}** rating points",
                "",
                "The resulting percentile is valid only as a model-based standing within the frontal SCUT-FBP5500 benchmark. It is not a universal population percentile.",
                "",
                "SCUT-FBP5500 is restricted to non-commercial research use.",
            ]
        ),
        encoding="utf-8",
    )
    print(report_path.read_text(encoding="utf-8"), flush=True)


if __name__ == "__main__":
    main()
