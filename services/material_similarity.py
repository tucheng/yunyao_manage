"""Material oxide-composition similarity helpers."""

from __future__ import annotations

from collections.abc import Sequence


OXIDE_FIELDS = (
    "sio2", "al2o3", "fe2o3", "tio2", "cao", "mgo", "na2o", "k2o",
    "zno", "b2o3", "p2o5", "li2o", "mno2", "coo", "sno2", "cuo",
    "cr2o3", "pbo", "bao", "sro", "loi",
)
TOP_SIMILAR_MATERIALS = 8


def oxide_profile(material) -> tuple[float, ...]:
    """Return all oxide percentages, treating a missing value as zero."""
    return tuple(float(getattr(material, field, 0) or 0) for field in OXIDE_FIELDS)


def has_oxide_data(profile: Sequence[float]) -> bool:
    return any(value > 0 for value in profile)


def oxide_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Return Bray-Curtis percentage similarity for two oxide profiles.

    Unlike cosine similarity, this compares the actual percentage values. A
    score of 100 is reserved for profiles whose values match field-for-field.
    """
    total = sum(abs(value) for value in left) + sum(abs(value) for value in right)
    if total <= 0:
        return 0.0

    difference = sum(abs(a - b) for a, b in zip(left, right))
    if difference <= 1e-9:
        return 100.0

    score = max(0.0, (1 - difference / total) * 100)
    # A non-identical pair must never become 100 after rounding.
    return min(round(score, 2), 99.99)


def material_similarity(left, right) -> float:
    return oxide_similarity(oxide_profile(left), oxide_profile(right))
