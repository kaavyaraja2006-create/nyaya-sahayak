"""Typed I/O contracts for the CaseUnderstandingAgent.

Everything here is a Pydantic model. The agent never returns free-form text
to the rest of the pipeline — only these structures. Field-level validators
enforce the provenance rules described in docs/AGENTS.md and the agent spec:
a claim without at least one concrete pointer back to the source material is
not a valid claim and cannot be constructed.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --------------------------------------------------------------------------
# Input contracts — the case material handed to the agent.
# --------------------------------------------------------------------------


class DocumentKind(str, Enum):
    """What kind of source material this document is.

    This only classifies the *document*; it never implies anything about the
    truth, weight, or legal effect of its contents.
    """

    LEGAL_DRAFT = "LEGAL_DRAFT"
    WITNESS_STATEMENT = "WITNESS_STATEMENT"
    INVESTIGATION_REPORT = "INVESTIGATION_REPORT"
    WRITTEN_SUBMISSION = "WRITTEN_SUBMISSION"
    HEARING_TRANSCRIPT = "HEARING_TRANSCRIPT"
    FACTUAL_DOCUMENT = "FACTUAL_DOCUMENT"
    OTHER = "OTHER"


class Paragraph(BaseModel):
    number: int
    text: str


class Page(BaseModel):
    number: int
    paragraphs: list[Paragraph] = Field(default_factory=list)


class TranscriptUtterance(BaseModel):
    """One located unit of a hearing transcript (a turn, a line, a numbered
    exchange — whatever granularity the transcript actually has)."""

    location: str  # e.g. "Hearing 3, examination-in-chief of PW-3, line 12"
    speaker: Optional[str] = None
    text: str


class SourceDocument(BaseModel):
    """A single uploaded document or transcript, already segmented as far as
    the upstream document-processing step could manage. `raw_text` is always
    populated as a fallback so the agent can still search for a quote even
    when no page/paragraph/utterance structure is available.
    """

    document_id: str
    title: Optional[str] = None
    document_kind: DocumentKind = DocumentKind.OTHER
    is_transcript: bool = False
    pages: list[Page] = Field(default_factory=list)
    utterances: list[TranscriptUtterance] = Field(default_factory=list)
    raw_text: str = ""

    @model_validator(mode="after")
    def _must_have_some_text(self) -> "SourceDocument":
        has_pages = any(p.text.strip() for pg in self.pages for p in pg.paragraphs)
        has_utterances = any(u.text.strip() for u in self.utterances)
        if not (has_pages or has_utterances or self.raw_text.strip()):
            raise ValueError(
                f"SourceDocument {self.document_id!r} has no extractable text; "
                "the CaseUnderstandingAgent cannot ground claims in an empty document."
            )
        return self


class CaseUnderstandingInput(BaseModel):
    case_id: str
    documents: list[SourceDocument] = Field(default_factory=list)

    @field_validator("documents")
    @classmethod
    def _at_least_one_document(cls, v: list[SourceDocument]) -> list[SourceDocument]:
        if not v:
            raise ValueError("CaseUnderstandingAgent requires at least one source document.")
        return v


# --------------------------------------------------------------------------
# Output contracts — what the agent hands to the next stage.
# --------------------------------------------------------------------------


class ClaimType(str, Enum):
    FACTUAL = "FACTUAL"
    LEGAL = "LEGAL"
    PROCEDURAL = "PROCEDURAL"
    UNKNOWN = "UNKNOWN"


class VerificationStatus(str, Enum):
    """Set exclusively by the agent's own provenance check — never trusted
    from the model's self-report. See validation.py."""

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


class SourceReference(BaseModel):
    """Whatever provenance is actually available. Nothing here is invented:
    a field that the source material does not establish is left as None,
    never guessed or defaulted to something plausible-looking.
    """

    document_id: Optional[str] = None
    page: Optional[int] = None
    paragraph: Optional[int] = None
    transcript_location: Optional[str] = None
    quote: Optional[str] = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _require_some_provenance(self) -> "SourceReference":
        if not any(
            [self.document_id, self.page is not None, self.paragraph is not None,
             self.transcript_location, self.quote]
        ):
            raise ValueError(
                "SourceReference has no provenance at all (no document_id, page, "
                "paragraph, transcript_location, or quote). A claim with no way to "
                "trace back to its source is rejected, not accepted with a guess."
            )
        return self


class Claim(BaseModel):
    """One atomic, source-grounded claim."""

    claim_id: str
    claim_text: str = Field(min_length=1)
    claim_type: ClaimType = ClaimType.UNKNOWN
    speaker: Optional[str] = None
    dates: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    source: SourceReference
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    verification_notes: Optional[str] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("claim_text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("claim_text must not be blank.")
        return v


class RejectedClaim(BaseModel):
    """A candidate claim the agent refused to construct, kept for audit
    instead of being silently thrown away."""

    raw: dict
    reason: str


class CaseUnderstandingResult(BaseModel):
    """The complete, deterministic output of one agent run."""

    case_id: str
    claims: list[Claim] = Field(default_factory=list)
    rejected_claims: list[RejectedClaim] = Field(default_factory=list)
    documents_processed: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    degraded: bool = False

    model_config = ConfigDict(extra="forbid")
