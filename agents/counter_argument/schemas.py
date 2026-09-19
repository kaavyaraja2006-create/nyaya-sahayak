"""Typed I/O contracts for the CounterArgumentAgent.

The design goal is the same as the other agents': *an invalid finding cannot
be constructed*. Here the rules that keep the agent from manufacturing
opposition are enforced by the types themselves:

* NO_CONTRARY_SOURCE_FOUND carries no contrary material and no counterpoints —
  it is a real, valid, first-class result.
* A `Counterpoint` cannot exist without at least one `CounterpointBasis`
  pointing at supplied evidence or supplied authority text. There is no way to
  express "a counterargument with no source".
* A `RetrievedAuthority` cannot exist without a verbatim quotation
  (`SourceProvenance.exact_text`) taken from the supplied passage. If it
  cannot be quoted, it is not listed.
* The three categories the spec insists on separating are three *different
  types*, so they cannot be confused downstream:
      1. retrieved evidence          -> `RetrievedEvidence`
      2. retrieved legal authority   -> `RetrievedAuthority`
      3. reasoning over those sources-> `Counterpoint` / `UnresolvedQuestion`,
         each stamped `assertion_kind="MODEL_REASONING_FROM_SOURCE"` and each
         carrying the sources it was derived from.

Provenance is only ever copied from the supplied evidence item or supplied
authority. The model never writes provenance.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..authority_citation.schemas import SourceProvenance
from ..case_understanding.schemas import Claim, ClaimType, SourceReference
from ..evidence_conflict.schemas import EvidenceItem, EvidenceType

# --------------------------------------------------------------------------
# Legal-safety guard
# --------------------------------------------------------------------------

# Phrases that would turn "here is material that could cut the other way"
# into a prediction of outcome, guilt, innocence or liability. This is
# defence in depth: the primary control is that none of these models has a
# field in which an outcome could be expressed. This catches a model that
# tries to smuggle one into free text anyway.
OUTCOME_LANGUAGE = (
    "will win", "would win", "will lose", "would lose",
    "is guilty", "is innocent", "is liable", "is not liable",
    "will succeed", "would succeed", "will fail", "would fail",
    "will prevail", "would prevail", "likely to prevail", "unlikely to prevail",
    "should be convicted", "should be acquitted",
    "must be convicted", "must be acquitted",
    "the court will", "the court would", "the judge will", "the judge would",
    "the prosecution will", "the prosecution would",
    "the defence will", "the defence would", "the defense will", "the defense would",
    "beyond reasonable doubt", "beyond a reasonable doubt",
    "proves guilt", "proves innocence", "establishes guilt", "establishes innocence",
    "is credible", "is not credible", "is lying", "is truthful", "is untruthful",
    "is the perpetrator", "is at fault", "is admissible", "is inadmissible",
)


def assert_no_outcome_prediction(value: str) -> str:
    """Shared legal-safety guard. Also used by the RiskReviewReportAgent, so
    that "no outcome prediction" means the same thing in both agents."""
    lowered = value.lower()
    for phrase in OUTCOME_LANGUAGE:
        if phrase in lowered:
            raise ValueError(
                "text must describe source material and its limits, not predict an "
                f"outcome or determine guilt/liability (found disallowed phrase {phrase!r})"
            )
    return value


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class MaterialKind(str, Enum):
    """Which corpus a piece of retrieved material came from."""

    EVIDENCE = "EVIDENCE"
    AUTHORITY = "AUTHORITY"


class CounterAnalysisStatus(str, Enum):
    """The outcome of the counter-analysis for one claim. Exactly three
    values — there is no "balanced-looking" state to aim for."""

    CONTRARY_MATERIAL_FOUND = "CONTRARY_MATERIAL_FOUND"
    NO_CONTRARY_SOURCE_FOUND = "NO_CONTRARY_SOURCE_FOUND"
    NOT_ASSESSED = "NOT_ASSESSED"  # the corpus could not be searched at all


class CounterpointType(str, Enum):
    """What kind of challenge the counterpoint makes. Each type dictates
    which kind of basis it must carry (see `Counterpoint`)."""

    CONTRARY_EVIDENCE = "CONTRARY_EVIDENCE"            # another evidence item cuts against the claim
    EVIDENCE_LIMITATION = "EVIDENCE_LIMITATION"        # supporting evidence does not establish as much as claimed
    CONTRARY_AUTHORITY = "CONTRARY_AUTHORITY"          # supplied authority text cuts against the proposition
    AUTHORITY_QUALIFICATION = "AUTHORITY_QUALIFICATION"  # supplied authority text narrows/conditions the proposition


# A status other than NO_CONTRARY_SOURCE_FOUND always goes to a human, and so
# does any finding carrying an unresolved question. One place, one policy.
AUTO_CLEAR_STATUSES = frozenset({CounterAnalysisStatus.NO_CONTRARY_SOURCE_FOUND})

EVIDENCE_BASED_COUNTERPOINTS = frozenset(
    {CounterpointType.CONTRARY_EVIDENCE, CounterpointType.EVIDENCE_LIMITATION}
)
AUTHORITY_BASED_COUNTERPOINTS = frozenset(
    {CounterpointType.CONTRARY_AUTHORITY, CounterpointType.AUTHORITY_QUALIFICATION}
)


def default_requires_human_review(
    status: CounterAnalysisStatus, unresolved_question_count: int
) -> bool:
    """The single place the review-flag policy is applied."""
    if unresolved_question_count:
        return True
    return status not in AUTO_CLEAR_STATUSES


# --------------------------------------------------------------------------
# Input contracts
# --------------------------------------------------------------------------


class CounterArgumentTarget(BaseModel):
    """One case proposition to be tested against the corpus.

    `is_material` is supplied by the caller (the pipeline or a human). The
    agent never decides for itself which claims matter; it only declines to
    spend analysis on ones it was told are not material.
    """

    claim_id: str
    claim_text: str = Field(min_length=1)
    claim_type: ClaimType = ClaimType.UNKNOWN
    source: SourceReference
    is_material: bool = True

    model_config = ConfigDict(extra="forbid")

    @field_validator("claim_id")
    @classmethod
    def _claim_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("claim_id must not be blank.")
        return v

    @field_validator("claim_text")
    @classmethod
    def _claim_text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("claim_text must not be blank.")
        return v

    @classmethod
    def from_claim(cls, claim: Claim, is_material: bool = True) -> "CounterArgumentTarget":
        """Chain from a CaseUnderstandingAgent claim, keeping its provenance."""
        return cls(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            source=claim.source,
            is_material=is_material,
        )


class CounterArgumentInput(BaseModel):
    """The approved corpus the agent may search, and nothing else.

    `evidence` and `authorities` are the *entire* universe available to this
    run. The agent cannot reach outside them, and the model is only ever
    shown material drawn from them.
    """

    case_id: str
    targets: list[CounterArgumentTarget]  # required: validators do not run on defaults
    evidence: list[EvidenceItem] = Field(default_factory=list)
    authorities: list = Field(default_factory=list)  # list[SuppliedAuthority]; see validator

    model_config = ConfigDict(extra="forbid")

    @field_validator("targets")
    @classmethod
    def _at_least_one_target(cls, v: list[CounterArgumentTarget]) -> list[CounterArgumentTarget]:
        if not v:
            raise ValueError("CounterArgumentAgent requires at least one proposition to analyse.")
        ids = [t.claim_id for t in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Target claim_id values must be unique within a run.")
        return v

    @field_validator("evidence")
    @classmethod
    def _unique_evidence_ids(cls, v: list[EvidenceItem]) -> list[EvidenceItem]:
        ids = [e.evidence_id for e in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Supplied evidence_id values must be unique within a run.")
        return v

    @field_validator("authorities")
    @classmethod
    def _unique_authority_ids(cls, v: list) -> list:
        from ..authority_citation.schemas import SuppliedAuthority

        for item in v:
            if not isinstance(item, SuppliedAuthority):
                raise ValueError("authorities must be SuppliedAuthority instances.")
        ids = [a.authority_id for a in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Supplied authority_id values must be unique within a run.")
        return v


# --------------------------------------------------------------------------
# Output contracts — category 1: retrieved evidence
# --------------------------------------------------------------------------


class RetrievedEvidence(BaseModel):
    """A piece of *evidence* from the approved corpus.

    Every field is copied from the supplied `EvidenceItem`; nothing here is
    authored by a model, and `source` is the item's own SourceReference.
    """

    evidence_id: str
    evidence_type: EvidenceType
    description: str = Field(min_length=1)
    source: SourceReference
    material_kind: Literal["EVIDENCE"] = "EVIDENCE"

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_item(cls, item: EvidenceItem) -> "RetrievedEvidence":
        return cls(
            evidence_id=item.evidence_id,
            evidence_type=item.evidence_type,
            description=item.description,
            source=item.source,
        )


# --------------------------------------------------------------------------
# Output contracts — category 2: retrieved legal authority
# --------------------------------------------------------------------------


class RetrievedAuthority(BaseModel):
    """A passage of *legal authority* from the approved corpus.

    `provenance` is built from the supplied authority's own data and must
    carry a verbatim `exact_text`: if the agent cannot quote the authority,
    it does not list it. That rule is what makes a fabricated holding
    impossible to express here.
    """

    authority_id: str
    passage_id: Optional[str] = None
    provenance: SourceProvenance
    material_kind: Literal["AUTHORITY"] = "AUTHORITY"

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _must_quote_and_match(self) -> "RetrievedAuthority":
        if not self.provenance.exact_text:
            raise ValueError(
                "RetrievedAuthority requires a verbatim exact_text quotation from the supplied "
                "passage. Authority that cannot be quoted is not listed."
            )
        if self.provenance.source_id != self.authority_id:
            raise ValueError(
                f"Provenance source_id {self.provenance.source_id!r} does not belong to "
                f"authority {self.authority_id!r}."
            )
        return self


# --------------------------------------------------------------------------
# Output contracts — category 3: reasoning derived from those sources
# --------------------------------------------------------------------------


class CounterpointBasis(BaseModel):
    """The source a piece of reasoning rests on. Exactly one of `evidence` /
    `authority` is populated, and `kind` must agree with it."""

    kind: MaterialKind
    evidence: Optional[RetrievedEvidence] = None
    authority: Optional[RetrievedAuthority] = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _exactly_one_side(self) -> "CounterpointBasis":
        if (self.evidence is None) == (self.authority is None):
            raise ValueError(
                "A basis must reference exactly one of evidence or authority."
            )
        if self.kind == MaterialKind.EVIDENCE and self.evidence is None:
            raise ValueError("kind=EVIDENCE requires an evidence reference.")
        if self.kind == MaterialKind.AUTHORITY and self.authority is None:
            raise ValueError("kind=AUTHORITY requires an authority reference.")
        return self

    @property
    def source_id(self) -> str:
        return self.evidence.evidence_id if self.evidence else self.authority.authority_id


class Counterpoint(BaseModel):
    """Reasoning that challenges or qualifies a claim.

    `statement` is *model reasoning*, not a source — which is why it is
    stamped `assertion_kind="MODEL_REASONING_FROM_SOURCE"` and why `basis`
    can never be empty. A downstream consumer reading a Counterpoint always
    knows both that a model wrote the sentence and exactly which supplied
    material it was derived from.
    """

    counterpoint_id: str
    claim_id: str
    counterpoint_type: CounterpointType
    statement: str = Field(min_length=1)
    assertion_kind: Literal["MODEL_REASONING_FROM_SOURCE"] = "MODEL_REASONING_FROM_SOURCE"
    basis: list[CounterpointBasis] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("statement")
    @classmethod
    def _statement_is_not_a_prediction(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("statement must not be blank.")
        return assert_no_outcome_prediction(v)

    @model_validator(mode="after")
    def _basis_matches_type(self) -> "Counterpoint":
        kinds = {b.kind for b in self.basis}
        if self.counterpoint_type in EVIDENCE_BASED_COUNTERPOINTS and MaterialKind.EVIDENCE not in kinds:
            raise ValueError(
                f"{self.counterpoint_type.value} must rest on at least one evidence basis."
            )
        if self.counterpoint_type in AUTHORITY_BASED_COUNTERPOINTS and MaterialKind.AUTHORITY not in kinds:
            raise ValueError(
                f"{self.counterpoint_type.value} must rest on at least one authority basis."
            )
        return self


class UnresolvedQuestion(BaseModel):
    """A question the supplied material does not answer.

    A question normally points at the material that raises it. The one
    exception is a question *about material that is absent from the corpus*,
    which by definition has nothing to point at — that must be declared
    explicitly with `about_absent_material=True` rather than dressed up with
    an unrelated source.
    """

    question_id: str
    claim_id: str
    question: str = Field(min_length=1)
    assertion_kind: Literal["MODEL_REASONING_FROM_SOURCE"] = "MODEL_REASONING_FROM_SOURCE"
    basis: list[CounterpointBasis] = Field(default_factory=list)
    about_absent_material: bool = False

    model_config = ConfigDict(extra="forbid")

    @field_validator("question")
    @classmethod
    def _question_is_not_a_prediction(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be blank.")
        return assert_no_outcome_prediction(v)

    @model_validator(mode="after")
    def _needs_basis_or_declared_absence(self) -> "UnresolvedQuestion":
        if not self.basis and not self.about_absent_material:
            raise ValueError(
                "An unresolved question must either cite the material that raises it or be "
                "declared as a question about material absent from the corpus."
            )
        return self


# --------------------------------------------------------------------------
# Output contracts — the finding
# --------------------------------------------------------------------------


class CounterArgumentFinding(BaseModel):
    """The complete counter-analysis for one claim.

    The status invariants below are the whole point of this agent: you cannot
    construct a NO_CONTRARY_SOURCE_FOUND finding that secretly carries a
    counterpoint, and you cannot construct a CONTRARY_MATERIAL_FOUND finding
    that carries nothing.
    """

    finding_id: str
    claim_id: str
    claim_text: str = Field(min_length=1)
    claim_source: SourceReference
    status: CounterAnalysisStatus
    supporting_evidence: list[RetrievedEvidence] = Field(default_factory=list)
    contrary_evidence: list[RetrievedEvidence] = Field(default_factory=list)
    supporting_authority: list[RetrievedAuthority] = Field(default_factory=list)
    contrary_authority: list[RetrievedAuthority] = Field(default_factory=list)
    counterpoints: list[Counterpoint] = Field(default_factory=list)
    unresolved_questions: list[UnresolvedQuestion] = Field(default_factory=list)
    analysis_note: str = Field(min_length=1)
    requires_human_review: bool

    model_config = ConfigDict(extra="forbid")

    @field_validator("analysis_note")
    @classmethod
    def _note_is_not_a_prediction(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("analysis_note must not be blank.")
        return assert_no_outcome_prediction(v)

    def has_contrary_material(self) -> bool:
        return bool(self.contrary_evidence or self.contrary_authority or self.counterpoints)

    @model_validator(mode="after")
    def _enforce_invariants(self) -> "CounterArgumentFinding":
        if self.status == CounterAnalysisStatus.NO_CONTRARY_SOURCE_FOUND and self.has_contrary_material():
            raise ValueError(
                "NO_CONTRARY_SOURCE_FOUND means nothing contrary was found: contrary evidence, "
                "contrary authority and counterpoints must all be empty."
            )
        if self.status == CounterAnalysisStatus.CONTRARY_MATERIAL_FOUND and not self.has_contrary_material():
            raise ValueError(
                "CONTRARY_MATERIAL_FOUND requires at least one item of contrary evidence, "
                "contrary authority, or a source-grounded counterpoint. Use "
                "NO_CONTRARY_SOURCE_FOUND instead — it is a valid result."
            )
        if self.status == CounterAnalysisStatus.NOT_ASSESSED:
            if (
                self.supporting_evidence or self.supporting_authority
                or self.has_contrary_material()
            ):
                raise ValueError(
                    "NOT_ASSESSED means the corpus was never searched for this claim; no "
                    "material may be attached to it."
                )
            if not self.requires_human_review:
                raise ValueError("NOT_ASSESSED findings must have requires_human_review=True.")

        expected_review = default_requires_human_review(self.status, len(self.unresolved_questions))
        if expected_review and not self.requires_human_review:
            raise ValueError(
                "This finding must be flagged for human review "
                "(status is not NO_CONTRARY_SOURCE_FOUND, or it carries unresolved questions)."
            )

        for item in (*self.counterpoints, *self.unresolved_questions):
            if item.claim_id != self.claim_id:
                raise ValueError(
                    f"Item references claim_id {item.claim_id!r} but belongs to a finding for "
                    f"claim {self.claim_id!r}."
                )
        return self


class RejectedCounterMaterial(BaseModel):
    """A model-proposed item the agent refused to accept, kept for audit.

    The finding built in its place never repeats the rejected content, so a
    fabricated authority or an unsupported counterargument cannot leak into
    the output through the rejection record.
    """

    claim_id: str
    kind: Literal[
        "supporting_evidence",
        "contrary_evidence",
        "supporting_authority",
        "contrary_authority",
        "counterpoint",
        "unresolved_question",
        "response",
    ]
    raw: dict
    reasons: list[str]

    model_config = ConfigDict(extra="forbid")


class CounterArgumentResult(BaseModel):
    """The complete, deterministic output of one agent run."""

    case_id: str
    findings: list[CounterArgumentFinding] = Field(default_factory=list)
    rejected_material: list[RejectedCounterMaterial] = Field(default_factory=list)
    targets_processed: list[str] = Field(default_factory=list)
    skipped_claim_ids: list[str] = Field(default_factory=list)  # declared non-material by the caller
    warnings: list[str] = Field(default_factory=list)
    degraded: bool = False

    model_config = ConfigDict(extra="forbid")
