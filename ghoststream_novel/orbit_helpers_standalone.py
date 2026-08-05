#!/usr/bin/env python3
"""Orbit-distance helpers with no GMN API dependency."""
from __future__ import annotations

from typing import Any
import numpy as np


def perihelion_vector(orbits: np.ndarray) -> np.ndarray:
    inc = np.deg2rad(orbits[:, 2])
    arg = np.deg2rad(orbits[:, 3])
    node = np.deg2rad(orbits[:, 4])
    return np.column_stack([
        np.cos(node) * np.cos(arg) - np.sin(node) * np.sin(arg) * np.cos(inc),
        np.sin(node) * np.cos(arg) + np.cos(node) * np.sin(arg) * np.cos(inc),
        np.sin(arg) * np.sin(inc),
    ])


def orbit_distance_matrix(a: np.ndarray, b: np.ndarray | None = None) -> np.ndarray:
    b = a if b is None else b
    e1, q1 = a[:, 0][:, None], a[:, 1][:, None]
    e2, q2 = b[:, 0][None, :], b[:, 1][None, :]
    i1, n1 = np.deg2rad(a[:, 2])[:, None], np.deg2rad(a[:, 4])[:, None]
    i2, n2 = np.deg2rad(b[:, 2])[None, :], np.deg2rad(b[:, 4])[None, :]
    plane = np.arccos(np.clip(
        np.cos(i1) * np.cos(i2) + np.sin(i1) * np.sin(i2) * np.cos(n1 - n2),
        -1.0, 1.0,
    ))
    p1, p2 = perihelion_vector(a), perihelion_vector(b)
    peri = np.arccos(np.clip(p1 @ p2.T, -1.0, 1.0))
    d2 = (
        (e1 - e2) ** 2 + (q1 - q2) ** 2
        + (2.0 * np.sin(plane / 2.0)) ** 2
        + (((e1 + e2) / 2.0) * 2.0 * np.sin(peri / 2.0)) ** 2
    )
    return np.sqrt(np.maximum(d2, 0.0))


def orbit_summary(orbits: np.ndarray) -> dict[str, Any]:
    matrix = orbit_distance_matrix(orbits)
    index = int(np.argmin(np.median(matrix, axis=1)))
    distances = matrix[index]
    return {
        "medoid": orbits[index],
        "median_d": float(np.median(distances)),
        "q90_d": float(np.percentile(distances, 90)),
    }
