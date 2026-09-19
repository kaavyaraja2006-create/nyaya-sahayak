"""Typed I/O contracts for the RiskReviewReportAgent.

This agent aggregates what the earlier stages already established. It creates
no legal facts, so the types here deliberately give it nowhere to put one:

* Every `RiskItem` names the `finding_id` it was derived from. There is no
  way to express a risk that is not traceable to an upstream finding, which
  is what makes the chain `Risk -> Finding -> Claim -> Source` total.
* `RiskItem.rules_applied` must be non-empty: a risk level that cannot be
  explained by naming the deterministic rules that produced it cannot be
  constructed. Levels come from `risk_rules.py`, never from a model.
* `ReviewItem.status` is the fixed literal `REQUIRES_HUMAN_REVIEW`. The agent
  raises issues; it has no vocabulary for resolving one.
* Free text is checked by the same legal-safety guard the CounterArgumentAgent
  uses, so a summary cannot slip into predicting an outcome.

`SourceRef` is a thin envelope around the *original* provenance objects from
upstream (`SourceReference` for case documents, `SourceProvenance` for legal
authority). Provenance is carried through by reference, never re-typed.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..authority_citation.schemas import SourceProvenance
from ..authority_citation.schemas import AuthorityCitationResult
from ..case_understanding.schemas import CaseUnderstandingResult, SourceReference
from ..counter_argument.schemas import CounterArgumentResult, assert_no_outcome_prediction
from ..evidence_conflict.schemas import EvidenceConflictResult

# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class RiskLevel(str, Enum):
    """Exactly three levels, as specified. No numeric scores: a number would
    imply a precision this agent does not have and cannot explain."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


class IssueType(str, Enum):
    """What kind of problem an item records. Each maps to a base risk level in
    `risk_rules.BASE_RISK`."""

    # Claim-level
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    PARTIALLY_SUPPORTED_CLAIM = "PARTIALLY_SUPPORTED_CLAIM"
    UNVERIFIED_CLAIM = "UNVERIFIED_CLAIM"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    # Citation / authority
    CITATION_MISMATCH = "CITATION_MISMATCH"
    PARTIAL_CITATION_SUPPORT = "PARTIAL_CITATION_SUPPORT"
    AMBIGUOUS_CITATION = "AMBIGUOUS_CITATION"
    AUTHORITY_NOT_FOUND = "AUTHORITY_NOT_FOUND"
    UNCITED_LEGAL_PROPOSITION = "UNCITED_LEGAL_PROPOSITION"
    AUTHORITY_STATUS_UNCERTAIN = "AUTHORITY_STATUS_UNCERTAIN"
    POTENTIALLY_OUTDATED_AUTHORITY = "POTENTIALLY_OUTDATED_AUTHORITY"
    # Counter-analysis
    UNRESOLVED_COUNTERARGUMENT = "UNRESOLVED_COUNTERARGUMENT"
    CONTRARY_AUTHORITY = "CONTRARY_AUTHORITY"
    COUNTER_ANALYSIS_INCOMPLETE = "COUNTER_ANALYSIS_INCOMPLETE"
    UNRESOLVED_QUESTION = "UNRESOLVED_QUESTION"
    # Provenance / hygiene
    PROVENANCE_FAILURE = "PROVENANCE_FAILURE"
    METADATA_ISSUE = "METADATA_ISSUE"
    NON_CRITICAL_CITATION_OMISSION = "NON_CRITICAL_CITATION_OMISSION"


class FindingKind(str, Enum):
    """Which upstream record a risk item traces back to."""

    CLAIM = "CLAIM"                          # CaseUnderstandingAgent claim
    CONFLICT = "CONFLICT"                    # EvidenceConflictAgent conflict
    SUPPORT_GAP = "SUPPORT_GAP"              # EvidenceConflictAgent support gap
    CITATION_FINDING = "CITATION_FINDING"    # AuthorityCitationAgent finding
    COUNTER_ANALYSIS = "COUNTER_ANALYSIS"    # CounterArgumentAgent finding


class ReviewType(str, Enum):
    """The question put to the human reviewer."""

    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"
    AMBIGUOUS_CITATION = "AMBIGUOUS_CITATION"
    MISSING_SOURCE = "MISSING_SOURCE"
    UNCERTAIN_AUTHORITY_STATUS = "UNCERTAIN_AUTHORITY_STATUS"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    POTENTIALLY_OUTDATED_AUTHORITY = "POTENTIALLY_OUTDATED_AUTHORITY"
    PROVENANCE_FAILURE = "PROVENANCE_FAILURE"
    UNRESOLVED_COUNTERARGUMENT = "UNRESOLVED_COUNTERARGUMENT"
    OTHER = "OTHER"


class AuthorityStatus(str, Enum):
    """Currency of an authority *as recorded by the source that supplied it*.

    Never inferred by this agent or by a model. UNKNOWN is the honest default
    and is itself reportable — "we do not know whether this is still good
    law" is a real review item.
    """

    CURRENT = "CURRENT"
    POTENTIALLY_OUTDATED = "POTENTIALLY_OUTDATED"
    UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------
# Source references
# --------------------------------------------------------------------------


class SourceRef(BaseModel):
    """A pointer to one source, carrying the original upstream provenance
    object unchanged. Exactly one of `document` / `authority` is set."""

    kind: Literal["DOCUMENT", "AUTHORITY"]
    document: Optional[SourceReference] = None
    authority: Optional[SourceProvenance] = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _exactly_one_side(self) -> "SourceRef":
        if (self.document is None) == (self.authority is None):
            raise ValueError("A SourceRef must carry exactly one of document or authority.")
        if self.kind == "DOCUMENT" and self.document is None:
            raise ValueError("kind=DOCUMENT requires a document reference.")
        if self.kind == "AUTHORITY" and self.authority is None:
            raise ValueError("kind=AUTHORITY requires an authority reference.")
        return self

    @classmethod
    def from_document(cls, ref: SourceReference) -> "SourceRef":
        return cls(kind="DOCUMENT", document=ref)

    @classmethod
    def from_authority(cls, provenance: SourceProvenance) -> "SourceRef":
        return cls(kind="AUTHORITY", authority=provenance)

    @property
    def source_id(self) -> Optional[str]:
        """The artifact this points at, if it identifies one."""
        if self.authority is not None:
            return self.authority.source_id
        return self.document.document_id

    def is_traceable_to_an_artifact(self) -> bool:
        """True if a human could go and open the thing this points at.

        A document reference with a quote but no document_id is not traceable:
        you cannot look it up. That is a provenance failure, not provenance.
        """
        return bool(self.source_id)


# --------------------------------------------------------------------------
# Input contracts
# --------------------------------------------------------------------------


class AuthorityStatusRecord(BaseModel):
    """Currency metadata supplied by whoever provided the authority."""

    authority_id: str
    status: AuthorityStatus = AuthorityStatus.UNKNOWN
    note: Optional[str] = None  # copied from the source record; never authored here

    model_config = ConfigDict(extra="forbid")


class RiskReviewReportInput(BaseModel):
    """Already-produced, source-grounded findings from the earlier stages.

    Every stage is optional: a partial pipeline produces a partial report that
    says which stages were missing, rather than one that quietly assumes the
    missing stage found nothing.

    `material_claim_ids` is supplied by the caller (pipeline configuration or
    a human). This agent never decides for itself which claims are important.
    """

    case_id: str
    case_understanding: Optional[CaseUnderstandingResult] = None
    evidence_conflict: Optional[EvidenceConflictResult] = None
    authority_citation: Optional[AuthorityCitationResult] = None
    counter_argument: Optional[CounterArgumentResult] = None
    material_claim_ids: list[str] = Field(default_factory=list)
    authority_statuses: list[AuthorityStatusRecord] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("authority_statuses")
    @classmethod
    def _unique_authority_ids(cls, v: list[AuthorityStatusRecord]) -> list[AuthorityStatusRecord]:
        ids = [r.authority_id for r in v]
        if len(ids) != len(set(ids)):
            raise ValueError("authority_statuses must not contain duplicate authority_id values.")
        return v


# --------------------------------------------------------------------------
# Output contracts
# --------------------------------------------------------------------------


class RiskItem(BaseModel):
    """One prioritised issue, traceable to the finding it came from."""

    risk_id: str
    risk_level: RiskLevel
    issue_type: IssueType
    reason: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    finding_kind: FindingKind
    claim_id: Optional[str] = None
    source_references: list[SourceRef] = Field(default_factory=list)
    rules_applied: list[str] = Field(min_length=1)
    requires_review: bool

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason")
    @classmethod
    def _reason_is_neutral(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reason must not be blank.")
        return assert_no_outcome_prediction(v)

    @field_validator("rules_applied")
    @classmethod
    def _rules_are_named(cls, v: list[str]) -> list[str]:
        if not all(rule.strip() for rule in v):
            raise ValueError("Every applied rule must be named, so the level is explainable.")
        return v


class ReviewItem(BaseModel):
    """An issue put to a human. The agent cannot resolve it: `status` is a
    fixed literal and there is no field in which an answer could be recorded."""

    review_id: str
    review_type: ReviewType
    risk_level: RiskLevel
    question: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    risk_item_ids: list[str] = Field(min_length=1)
    finding_ids: list[str] = Field(min_length=1)
    claim_id: Optional[str] = None
    source_references: list[SourceRef] = Field(default_factory=list)
    status: Literal["REQUIRES_HUMAN_REVIEW"] = "REQUIRES_HUMAN_REVIEW"

    model_config = ConfigDict(extra="forbid")

    @field_validator("question", "reason")
    @classmethod
    def _text_is_neutral(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be blank.")
        return assert_no_outcome_prediction(v)


class StageStatus(BaseModel):
    """Whether an upstream stage ran, and whether it ran cleanly."""

    stage: str
    present: bool
    degraded: bool = False
    warnings: int = 0
    rejected_items: int = 0

    model_config = ConfigDict(extra="forbid")


class Dashboard(BaseModel):
    """Counts only — every number here is derived from the risk and review
    items, so nothing on the dashboard exists without a traceable item."""

    case_id: str
    total_risk_items: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    risk_by_issue_type: dict[str, int] = Field(default_factory=dict)
    total_review_items: int = 0
    review_by_type: dict[str, int] = Field(default_factory=dict)
    claims_assessed: int = 0
    claims_with_risk: list[str] = Field(default_factory=list)
    provenance_failures: int = 0
    stages: list[StageStatus] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ReportSummary(BaseModel):
    """A deterministic headline, plus optional model-written prose.

    `narrative` is the only place a model may contribute to this agent's
    output, and it is dropped entirely unless it introduces no ids, no
    quotations and no assertions that are not already in the report. The
    fixed `basis` literal records what this report is: aggregation, not
    research.
    """

    case_id: str
    headline: str = Field(min_length=1)
    narrative: Optional[str] = None
    highest_risk_level: Optional[RiskLevel] = None
    top_risk_ids: list[str] = Field(default_factory=list)
    total_risk_items: int = 0
    total_review_items: int = 0
    basis: Literal["AGGREGATED_FROM_VERIFIED_FINDINGS"] = "AGGREGATED_FROM_VERIFIED_FINDINGS"

    model_config = ConfigDict(extra="forbid")

    @field_validator("headline", "narrative")
    @classmethod
    def _text_is_neutral(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return assert_no_outcome_prediction(v)


class ValidationFailure(BaseModel):
    """Something the report refused to emit, kept for audit.

    `kind` names which invariant was broken; `detail` never repeats
    model-authored content, so a rejected hallucination cannot re-enter the
    report through its own rejection record.
    """

    kind: Literal[
        "untraceable_risk_item",
        "finding_without_provenance",
        "unknown_claim_reference",
        "fabricated_source",
        "new_claim_in_summary",
        "unsafe_summary",
    ]
    detail: str
    dropped_id: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class RiskReviewReportResult(BaseModel):
    """The complete, deterministic output of one agent run."""

    case_id: str
    risk_items: list[RiskItem] = Field(default_factory=list)
    review_items: list[ReviewItem] = Field(default_factory=list)
    dashboard: Dashboard
    summary: ReportSummary
    validation_failures: list[ValidationFailure] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    degraded: bool = False

    model_config = ConfigDict(extra="forbid")
