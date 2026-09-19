"""Relationship domain model."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def uid() -> str:
    return uuid.uuid4().hex


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Relationship:
    id: str = field(default_factory=uid)
    relationship_id: str = ""  # R-01
    case_id: str = ""
    claim_id: str = ""
    evidence_id: str = ""
    relationship: str = "MENTIONS"  # SUPPORTS, CONFLICTS, CONTEXTUALIZES, UNCERTAIN, MENTIONS
    reason: str | None = None
    assessment_signal: str | None = None
    created_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "relationship_id": self.relationship_id or self.id,
            "case_id": self.case_id,
            "claim_id": self.claim_id,
            "evidence_id": self.evidence_id,
            "relationship": self.relationship,
            "reason": self.reason,
            "assessment_signal": self.assessment_signal,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Relationship:
        return cls(
            id=data.get("id") or uid(),
            relationship_id=data.get("relationship_id") or data.get("id") or "",
            case_id=data.get("case_id", ""),
            claim_id=data.get("claim_id", ""),
            evidence_id=data.get("evidence_id", ""),
            relationship=data.get("relationship", "MENTIONS"),
            reason=data.get("reason"),
            assessment_signal=data.get("assessment_signal"),
            created_at=data.get("created_at") or utcnow(),
        )
