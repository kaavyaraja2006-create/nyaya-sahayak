"""Conflict domain model."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def uid() -> str:
    return uuid.uuid4().hex


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Conflict:
    id: str = field(default_factory=uid)
    finding_id: str = ""  # F-001
    case_id: str = ""
    kind: str = "conflict"
    category: str | None = None
    group_name: str = "evidence"
    priority: str = "medium"
    claim_id: str | None = None
    title: str = ""
    reason: str | None = None
    conflict_type: str | None = None
    comparison_json: dict | list | None = None
    relationship_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    authority_id: str | None = None
    status: str = "open"
    requires_human_review: bool = True
    created_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "finding_id": self.finding_id or self.id,
            "case_id": self.case_id,
            "kind": self.kind,
            "category": self.category,
            "group_name": self.group_name,
            "priority": self.priority,
            "claim_id": self.claim_id,
            "title": self.title,
            "reason": self.reason,
            "conflict_type": self.conflict_type,
            "comparison_json": self.comparison_json,
            "relationship_ids": self.relationship_ids,
            "evidence_ids": self.evidence_ids,
            "authority_id": self.authority_id,
            "status": self.status,
            "requires_human_review": self.requires_human_review,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Conflict:
        rel_ids = data.get("relationship_ids") or []
        ev_ids = data.get("evidence_ids") or []
        return cls(
            id=data.get("id") or uid(),
            finding_id=data.get("finding_id") or data.get("id") or "",
            case_id=data.get("case_id", ""),
            kind=data.get("kind", "conflict"),
            category=data.get("category"),
            group_name=data.get("group_name", "evidence"),
            priority=data.get("priority", "medium"),
            claim_id=data.get("claim_id"),
            title=data.get("title", ""),
            reason=data.get("reason"),
            conflict_type=data.get("conflict_type"),
            comparison_json=data.get("comparison_json"),
            relationship_ids=rel_ids if isinstance(rel_ids, list) else [],
            evidence_ids=ev_ids if isinstance(ev_ids, list) else [],
            authority_id=data.get("authority_id"),
            status=data.get("status", "open"),
            requires_human_review=data.get("requires_human_review", True),
            created_at=data.get("created_at") or utcnow(),
        )
