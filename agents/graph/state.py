"""The one shared state object the five agents pass between them.

Everything is typed. The state holds the *case inputs* the caller supplies
and the *structured result* of each stage — never free text, never a
flattened summary, never a re-typed copy of an earlier stage's finding. A
downstream agent reads the previous stage's result object as it was produced,
so provenance and uncertainty travel with the data instead of having to be
re-asserted at every hop.

`stage_log` is the audit trail of the run itself: which stages executed,
which were skipped for want of input, and which failed. A stage that fails
leaves its result as `None` and says so here. Nothing downstream treats a
`None` as "that stage found nothing".
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..authority_citation.schemas import AuthorityCitationResult, SuppliedAuthority
from ..case_understanding.schemas import CaseUnderstandingResult, SourceDocument
from ..counter_argument.schemas import CounterArgumentResult
from ..evidence_conflict.schemas import EvidenceConflictResult, EvidenceItem
from ..risk_review_report.schemas import AuthorityStatusRecord, RiskReviewReportResult


class StageName(str, Enum):
    """The five stages, in the fixed order the graph runs them."""

    CASE_UNDERSTANDING = "case_understanding"
    EVIDENCE_CONFLICT = "evidence_conflict"
    AUTHORITY_CITATION = "authority_citation"
    COUNTER_ARGUMENT = "counter_argument"
    RISK_REVIEW_REPORT = "risk_review_report"


PIPELINE_ORDER: tuple[StageName, ...] = (
    StageName.CASE_UNDERSTANDING,
    StageName.EVIDENCE_CONFLICT,
    StageName.AUTHORITY_CITATION,
    StageName.COUNTER_ARGUMENT,
    StageName.RISK_REVIEW_REPORT,
)


class StageOutcome(str, Enum):
    """What happened to a stage. SKIPPED and FAILED are both recorded
    explicitly, because neither means the stage looked and found nothing."""

    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"    # the stage had nothing to work on
    FAILED = "FAILED"      # the stage raised; its result is None


class StageRecord(BaseModel):
    stage: StageName
    outcome: StageOutcome
    detail: str = ""

    model_config = ConfigDict(extra="forbid")


class NyayaSahayakState(BaseModel):
    """The graph's single shared state.

    Caller-supplied inputs:
      documents            case material for the CaseUnderstandingAgent
      evidence             already-segmented evidence items, each with its own
                           provenance, for the evidence and counter stages
      authorities          the approved authority corpus
      citations_by_claim   claim_id -> the citations written for it in the case
                           material. Supplied by the caller: extracting
                           citations is not one of the five agents' jobs, and
                           the graph does not add a sixth. A claim with no
                           entry is treated as uncited, which the
                           AuthorityCitationAgent reports as such.
      material_claim_ids   claims the caller considers important. Used by the
                           RiskReviewReportAgent to escalate risk. When empty,
                           the CounterArgumentAgent still analyses every claim
                           — defaulting to "analyse everything" errs toward
                           looking, while risk escalation errs toward only
                           what a human actually declared important.
      authority_statuses   currency records for authorities, from whoever
                           supplied them. Never inferred here.

    Stage outputs are the agents' own result objects, unmodified.
    """

    case_id: str

    documents: list[SourceDocument] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    authorities: list[SuppliedAuthority] = Field(default_factory=list)
    citations_by_claim: dict[str, list[str]] = Field(default_factory=dict)
    material_claim_ids: list[str] = Field(default_factory=list)
    authority_statuses: list[AuthorityStatusRecord] = Field(default_factory=list)

    case_understanding: Optional[CaseUnderstandingResult] = None
    evidence_conflict: Optional[EvidenceConflictResult] = None
    authority_citation: Optional[AuthorityCitationResult] = None
    counter_argument: Optional[CounterArgumentResult] = None
    risk_review_report: Optional[RiskReviewReportResult] = None

    stage_log: list[StageRecord] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    # -- convenience -------------------------------------------------------

    def executed_stages(self) -> list[StageName]:
        return [record.stage for record in self.stage_log]

    def outcome_of(self, stage: StageName) -> Optional[StageOutcome]:
        for record in self.stage_log:
            if record.stage == stage:
                return record.outcome
        return None

    def claims(self) -> list:
        return list(self.case_understanding.claims) if self.case_understanding else []
