"""Review and CounterArgument domain models."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def uid() -> str:
    return uuid.uuid4().hex


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class FindingType(str, Enum):
    """What a Review points at.

    Mirrors the RiskReviewReportAgent's FindingKind so a review item raised by
    the pipeline can be stored without being reshaped; COUNTER_ARGUMENT is
    kept as an accepted alias of COUNTER_ANALYSIS for older records.
    """

    CLAIM = "CLAIM"
    CONFLICT = "CONFLICT"
    SUPPORT_GAP = "SUPPORT_GAP"
    CITATION_FINDING = "CITATION_FINDING"
    COUNTER_ANALYSIS = "COUNTER_ANALYSIS"
    COUNTER_ARGUMENT = "COUNTER_ARGUMENT"
    EVIDENCE = "EVIDENCE"


@dataclass
class CounterArgument:
    """Persisted CounterArgumentFinding from the CounterArgumentAgent.

    The agent's status vocabulary (including NO_CONTRARY_SOURCE_FOUND and
    REQUIRES_HUMAN_REVIEW) is stored as produced; counterpoints and unresolved
    questions keep their own basis/provenance payloads verbatim.
    """

    id: str = field(default_factory=uid)
    finding_id: str = ""
    case_id: str = ""
    run_id: str | None = None
    claim_id: str | None = None
    claim_text: str = ""
    status: str = "REQUIRES_HUMAN_REVIEW"
    analysis_note: str = ""
    argument_text: str = ""
    claim_source_json: dict | None = None
    supporting_evidence_ids: list[str] = field(default_factory=list)
    contrary_evidence_ids: list[str] = field(default_factory=list)
    supporting_authority_ids: list[str] = field(default_factory=list)
    contrary_authority_ids: list[str] = field(default_factory=list)
    counterpoints_json: list = field(default_factory=list)
    unresolved_questions_json: list = field(default_factory=list)
    requires_human_review: bool = True
    created_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "finding_id": self.finding_id or self.id,
            "case_id": self.case_id,
            "run_id": self.run_id,
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "status": self.status,
            "analysis_note": self.analysis_note,
            "argument_text": self.argument_text,
            "claim_source_json": self.claim_source_json,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "contrary_evidence_ids": list(self.contrary_evidence_ids),
            "supporting_authority_ids": list(self.supporting_authority_ids),
            "contrary_authority_ids": list(self.contrary_authority_ids),
            "counterpoints_json": list(self.counterpoints_json),
            "unresolved_questions_json": list(self.unresolved_questions_json),
            "requires_human_review": self.requires_human_review,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CounterArgument:
        return cls(
            id=data.get("id") or uid(),
            finding_id=data.get("finding_id") or data.get("id") or "",
            case_id=data.get("case_id", ""),
            run_id=data.get("run_id"),
            claim_id=data.get("claim_id"),
            claim_text=data.get("claim_text", ""),
            status=data.get("status", "REQUIRES_HUMAN_REVIEW"),
            analysis_note=data.get("analysis_note", ""),
            argument_text=data.get("argument_text", ""),
            claim_source_json=data.get("claim_source_json"),
            supporting_evidence_ids=list(data.get("supporting_evidence_ids") or []),
            contrary_evidence_ids=list(data.get("contrary_evidence_ids") or []),
            supporting_authority_ids=list(data.get("supporting_authority_ids") or []),
            contrary_authority_ids=list(data.get("contrary_authority_ids") or []),
            counterpoints_json=list(data.get("counterpoints_json") or []),
            unresolved_questions_json=list(data.get("unresolved_questions_json") or []),
            requires_human_review=bool(data.get("requires_human_review", True)),
            created_at=data.get("created_at") or utcnow(),
        )


@dataclass
class Review:
    """Human review decision using finding_type + finding_id."""
    id: str = field(default_factory=uid)
    review_id: str = ""
    case_id: str = ""
    finding_type: str = "CLAIM"  # CLAIM, CONFLICT, CITATION_FINDING, COUNTER_ARGUMENT, EVIDENCE
    finding_id: str = ""
    reviewer_id: str = ""
    reviewer_name: str = ""
    decision: str = "NEEDS_REVIEW"  # ACCEPTED, REJECTED, EDITED, NEEDS_VERIFICATION
    comment: str | None = None
    previous_status: str | None = None
    new_status: str | None = None
    # Populated when the item was raised by the RiskReviewReportAgent.
    run_id: str | None = None
    review_type: str | None = None
    risk_level: str | None = None
    question: str | None = None
    reason: str | None = None
    risk_item_ids: list[str] = field(default_factory=list)
    finding_ids: list[str] = field(default_factory=list)
    source: str = "human"  # "human" or "agent"
    created_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "review_id": self.review_id or self.id,
            "case_id": self.case_id,
            "finding_type": self.finding_type,
            "finding_id": self.finding_id,
            "reviewer_id": self.reviewer_id,
            "reviewer_name": self.reviewer_name,
            "decision": self.decision,
            "comment": self.comment,
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "run_id": self.run_id,
            "review_type": self.review_type,
            "risk_level": self.risk_level,
            "question": self.question,
            "reason": self.reason,
            "risk_item_ids": list(self.risk_item_ids),
            "finding_ids": list(self.finding_ids),
            "source": self.source,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Review:
        ft = data.get("finding_type", "CLAIM")
        # Validate finding_type against allowed Enum
        if ft not in [e.value for e in FindingType]:
            ft = FindingType.CLAIM.value
        return cls(
            id=data.get("id") or uid(),
            review_id=data.get("review_id") or data.get("id") or "",
            case_id=data.get("case_id", ""),
            finding_type=ft,
            finding_id=data.get("finding_id", ""),
            reviewer_id=data.get("reviewer_id", ""),
            reviewer_name=data.get("reviewer_name", ""),
            decision=data.get("decision", "NEEDS_REVIEW"),
            comment=data.get("comment"),
            previous_status=data.get("previous_status"),
            new_status=data.get("new_status"),
            run_id=data.get("run_id"),
            review_type=data.get("review_type"),
            risk_level=data.get("risk_level"),
            question=data.get("question"),
            reason=data.get("reason"),
            risk_item_ids=list(data.get("risk_item_ids") or []),
            finding_ids=list(data.get("finding_ids") or []),
            source=data.get("source", "human"),
            created_at=data.get("created_at") or utcnow(),
        )
