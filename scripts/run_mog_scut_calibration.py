from __future__ import annotations

import build_mog_scut_calibration as builder

_original_percentile_summary = builder.percentile_summary


def safe_percentile_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    return _original_percentile_summary(values)


builder.percentile_summary = safe_percentile_summary
builder.main()
