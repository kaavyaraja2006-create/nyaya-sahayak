"""Human-readable, per-case sequential identifiers (C-01, E-03, DOC-004 …)."""
from __future__ import annotations


def seq_id(prefix: str, index: int, width: int = 2) -> str:
    return f"{prefix}-{str(index).zfill(width)}"


def next_index(existing: list[str], prefix: str) -> int:
    best = 0
    for value in existing:
        if not value or not value.startswith(prefix + "-"):
            continue
        tail = value.split("-", 1)[1]
        if tail.isdigit():
            best = max(best, int(tail))
    return best + 1
