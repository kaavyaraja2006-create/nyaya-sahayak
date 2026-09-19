"""Typed I/O contracts for the EvidenceConflictAgent.

Reuses `SourceReference` and `Claim` from `agents.case_understanding` so the
two agents chain naturally: the CaseUnderstandingAgent's claims are this
agent's primary input. Every output model that asserts a relationship
between sources carries the original SourceReference(s) it was built from —
never a restated or re-typed quote — so nothing here can drift from what the
CaseUnderstandingAgent (or the raw evidence record) actually established.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..case_understanding.schemas import Claim, SourceReference

# Phrases that would turn a neutral "relationship detected" statement into a
# credibility/guilt/liability determination. This is a defense-in-depth
# guard, not the primary control (the primary control is that these models
# have no field in which such a determination could even be expressed) — but
# it catches a model that tries to smuggle a verdict into free text anyway.
_VERDICT_LANGUAGE = (
    "is lying", "is truthful", "is untruthful", "is credible", "is not credible",
    "is guilty", "is innocent", "is liable", "is not liable", "should win",
    "should lose", "is admissible", "is inadmissible", "committed the",
    "is the perpetrator", "beyond reasonable doubt", "is at fault",
)


def _assert_neutral(value: str) -> str:
    lowered = value.lower()
    for phrase in _VERDICT_LANGUAGE:
        if phrase in lowered:
            raise ValueError(
                f"text must describe a detected relationship, not a verdict "
                f"(found disallowed phrase {phrase!r}): {value!r}"
            )
    return value


# --------------------------------------------------------------------------
# Input contracts
# --------------------------------------------------------------------------


class EvidenceType(str, Enum):
    DOCUMENT = "DOCUMENT"
    PHYSICAL = "PHYSICAL"
    DIGITAL = "DIGITAL"
    TESTIMONY = "TESTIMONY"
    FORENSIC = "FORENSIC"
    OTHER = "OTHER"


class EvidenceItem(BaseModel):
    """A single piece of evidence already segmented with its own provenance.

    This does not have to come from an LLM — it can be a CCTV log entry, a
    forensic report line, a document extract, etc. — as long as it carries a
    real SourceReference.
    """

    evidence_id: str
    evidence_type: EvidenceType = EvidenceType.OTHER
    description: str = Field(min_length=1)
    source: SourceReference
    item_date: Optional[str] = None
    entities: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class EvidenceConflictInput(BaseModel):
    case_id: str
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)

    @field_validator("claims")
    @classmethod
    def _at_least_one_claim(cls, v: list[Claim]) -> list[Claim]:
        if not v:
            raise ValueError("EvidenceConflictAgent requires at least one claim to evaluate.")
        return v


# --------------------------------------------------------------------------
# Output contracts
# --------------------------------------------------------------------------


class RelationshipType(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    MENTIONS = "MENTIONS"  # touches the same subject without clearly supporting or contradicting


class ClaimEvidenceRelationship(BaseModel):
    """One claim <-> one evidence item, with both original sources attached."""

    relationship_id: str
    claim_id: str
    evidence_id: str
    relationship_type: RelationshipType
    reasoning: str = Field(min_length=1)
    claim_source: SourceReference
    evidence_source: SourceReference

    model_config = ConfigDict(extra="forbid")

    @field_validator("reasoning")
    @classmethod
    def _reasoning_is_neutral(cls, v: str) -> str:
        return _assert_neutral(v)


class ConflictType(str, Enum):
    INCONSISTENT_STATEMENTS = "INCONSISTENT_STATEMENTS"          # claim vs claim
    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"            # evidence vs evidence
    CLAIM_EVIDENCE_CONTRADICTION = "CLAIM_EVIDENCE_CONTRADICTION"  # claim vs evidence


class ConflictSide(BaseModel):
    """One side of a conflict. Exactly one of claim_id/evidence_id identifies
    what this side is, and `source` is always the real SourceReference copied
    from that claim or evidence item — never re-derived by the model."""

    claim_id: Optional[str] = None
    evidence_id: Optional[str] = None
    source: SourceReference

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _needs_an_id(self) -> "ConflictSide":
        if not self.claim_id and not self.evidence_id:
            raise ValueError("A conflict side must reference a claim_id or an evidence_id.")
        if self.claim_id and self.evidence_id:
            raise ValueError("A conflict side must reference only one of claim_id or evidence_id, not both.")
        return self


class Conflict(BaseModel):
    """A detected inconsistency between two sources. `result` is a fixed
    literal — this type cannot express a resolution, only a detection."""

    conflict_id: str
    conflict_type: ConflictType
    description: str = Field(min_length=1)
    side_a: ConflictSide
    side_b: ConflictSide
    result: Literal["CONFLICT_DETECTED"] = "CONFLICT_DETECTED"

    model_config = ConfigDict(extra="forbid")

    @field_validator("description")
    @classmethod
    def _description_is_neutral(cls, v: str) -> str:
        return _assert_neutral(v)

    @model_validator(mode="after")
    def _sides_are_distinct_and_present(self) -> "Conflict":
        a = self.side_a.claim_id or self.side_a.evidence_id
        b = self.side_b.claim_id or self.side_b.evidence_id
        if a == b:
            raise ValueError(
                "A conflict must reference two different sources; side_a and side_b "
                "resolved to the same id."
            )
        return self


class GapType(str, Enum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"            # nothing in the case material addresses this claim
    INSUFFICIENT_SUPPORT = "INSUFFICIENT_SUPPORT"    # some evidence exists but does not establish the claim


class SupportGap(BaseModel):
    """A claim that evidence does not adequately establish. `result` is fixed
    to the literal the spec requires — INSUFFICIENT_EVIDENCE — so this type
    cannot be used to assert anything stronger."""

    gap_id: str
    claim_id: str
    claim_source: SourceReference
    gap_type: GapType
    related_evidence_ids: list[str] = Field(default_factory=list)
    note: str = Field(min_length=1)
    result: Literal["INSUFFICIENT_EVIDENCE"] = "INSUFFICIENT_EVIDENCE"

    model_config = ConfigDict(extra="forbid")

    @field_validator("note")
    @classmethod
    def _note_is_neutral(cls, v: str) -> str:
        return _assert_neutral(v)

    @model_validator(mode="after")
    def _missing_means_no_evidence(self) -> "SupportGap":
        if self.gap_type == GapType.MISSING_EVIDENCE and self.related_evidence_ids:
            raise ValueError(
                "gap_type MISSING_EVIDENCE means no evidence addresses the claim; "
                "related_evidence_ids must be empty. Use INSUFFICIENT_SUPPORT if some "
                "evidence exists but falls short."
            )
        return self


class RejectedFinding(BaseModel):
    """A candidate relationship/conflict/gap the agent refused to construct,
    kept for audit instead of being silently discarded."""

    kind: Literal["relationship", "conflict", "support_gap"]
    raw: dict
    reason: str


class EvidenceConflictResult(BaseModel):
    """The complete, deterministic output of one agent run."""

    case_id: str
    relationships: list[ClaimEvidenceRelationship] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    support_gaps: list[SupportGap] = Field(default_factory=list)
    rejected_findings: list[RejectedFinding] = Field(default_factory=list)
    claims_processed: list[str] = Field(default_factory=list)
    evidence_processed: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    degraded: bool = False

    model_config = ConfigDict(extra="forbid")
