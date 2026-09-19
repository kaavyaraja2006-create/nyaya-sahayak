"""RiskItem domain model — the persisted output of the RiskReviewReportAgent.

Risk levels are produced by deterministic rules inside the agent. They are
stored as given, together with `rules_applied`, so any level shown in the UI
can be traced back to the rule that set it.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def uid() -> str:
    return uuid.uuid4().hex


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RiskItem:
    id: str = field(default_factory=uid)
    risk_id: str = ""
    case_id: str = ""
    run_id: str | None = None
    risk_level: str = "LOW"          # HIGH, MEDIUM, LOW
    issue_type: str = ""
    reason: str = ""
    finding_id: str = ""             # the upstream finding this risk is about
    finding_kind: str = ""           # CLAIM, CONFLICT, CITATION_FINDING, ...
    claim_id: str | None = None
    source_references_json: list = field(default_factory=list)
    rules_applied: list[str] = field(default_factory=list)
    requires_review: bool = True
    created_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "risk_id": self.risk_id or self.id,
            "case_id": self.case_id,
            "run_id": self.run_id,
            "risk_level": self.risk_level,
            "issue_type": self.issue_type,
            "reason": self.reason,
            "finding_id": self.finding_id,
            "finding_kind": self.finding_kind,
            "claim_id": self.claim_id,
            "source_references_json": list(self.source_references_json),
            "rules_applied": list(self.rules_applied),
            "requires_review": self.requires_review,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RiskItem:
        return cls(
            id=data.get("id") or uid(),
            risk_id=data.get("risk_id") or data.get("id") or "",
            case_id=data.get("case_id", ""),
            run_id=data.get("run_id"),
            risk_level=data.get("risk_level", "LOW"),
            issue_type=data.get("issue_type", ""),
            reason=data.get("reason", ""),
            finding_id=data.get("finding_id", ""),
            finding_kind=data.get("finding_kind", ""),
            claim_id=data.get("claim_id"),
            source_references_json=list(data.get("source_references_json") or []),
            rules_applied=list(data.get("rules_applied") or []),
            requires_review=bool(data.get("requires_review", True)),
            created_at=data.get("created_at") or utcnow(),
        )
