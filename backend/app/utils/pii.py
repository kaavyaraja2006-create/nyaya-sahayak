"""Basic, deterministic PII detection.

Prototype-grade only: this is not comprehensive privacy protection or legal
compliance. Detection is rule-based so it behaves identically on every run.
"""
from __future__ import annotations

import re

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)")
AADHAAR_LIKE_RE = re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")

DISCLAIMER = (
    "Basic prototype PII redaction. This is not comprehensive privacy "
    "protection or legal compliance."
)


def find_pii(text: str) -> list[dict]:
    hits: list[dict] = []
    for kind, pattern in (("email", EMAIL_RE), ("phone", PHONE_RE), ("aadhaar_like", AADHAAR_LIKE_RE)):
        for m in pattern.finditer(text or ""):
            hits.append({"kind": kind, "value": m.group(0), "start": m.start(), "end": m.end()})
    return hits


def redact(text: str) -> str:
    if not text:
        return text
    out = EMAIL_RE.sub("[EMAIL REDACTED]", text)
    out = AADHAAR_LIKE_RE.sub("[ID-LIKE NUMBER REDACTED]", out)
    out = PHONE_RE.sub("[PHONE REDACTED]", out)
    return out
