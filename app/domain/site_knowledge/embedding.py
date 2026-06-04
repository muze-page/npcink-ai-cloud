from __future__ import annotations

import hashlib
import math

DETERMINISTIC_EMBEDDING_MODEL = "deterministic-sha256-mvp"
DETERMINISTIC_EMBEDDING_DIMENSIONS = 32


def embed_text_deterministic(
    text: str,
    *,
    dimensions: int = DETERMINISTIC_EMBEDDING_DIMENSIONS,
) -> list[float]:
    normalized = " ".join(str(text or "").lower().split())
    values: list[float] = []
    seed = normalized or "empty"
    counter = 0

    while len(values) < dimensions:
        digest = hashlib.sha256(f"{seed}|{counter}".encode()).digest()
        for byte in digest:
            values.append((byte / 127.5) - 1.0)
            if len(values) >= dimensions:
                break
        counter += 1

    magnitude = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / magnitude for value in values]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    limit = min(len(left), len(right))
    left_norm = math.sqrt(sum(value * value for value in left[:limit])) or 1.0
    right_norm = math.sqrt(sum(value * value for value in right[:limit])) or 1.0
    dot = sum(left[index] * right[index] for index in range(limit))
    return max(0.0, min(1.0, (dot / (left_norm * right_norm) + 1.0) / 2.0))
