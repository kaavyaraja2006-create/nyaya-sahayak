"""Typed I/O contracts for the AuthorityCitationAgent.

The design goal of this module is that an *invalid finding cannot be
constructed*. The invariants that keep the agent from inventing law are
enforced by the types themselves (see `CitationFinding`), not just by
convention in the agent code:

* SOURCE_NOT_FOUND carries no sources and no authority_id — nothing was
  found, so there is nothing to point at.
* SUPPORTS / PARTIALLY_SUPPORTS / CONTRADICTS must carry at least one
  verbatim `exact_text` from a supplied source.
* Anything other than SUPPORTS must be flagged for human review.
* An uncited proposition can only ever be REQUIRES_HUMAN_REVIEW.

Provenance (`SourceProvenance`) is only ever populated from the supplied
authority data. The model never writes it.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..case_understanding.schemas import Claim, ClaimType, SourceReference

# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class CitationRelationship(str, Enum):
    """Strict verification outcome for one (proposition, citation) pair.

    Exactly these six values — nothing else can be expressed.
    """

    SUPPORTS = "SUPPORTS"                        # supplied text clearly supports the proposition
    PARTIALLY_SUPPORTS = "PARTIALLY_SUPPORTS"    # supports only part of it
    DOES_NOT_SUPPORT = "DOES_NOT_SUPPORT"        # authority retrieved; its text does not support it
    CONTRADICTS = "CONTRADICTS"                  # authority retrieved; its text conflicts with it
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"        # cited authority cannot be verified from available sources
    REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"  # source exists/may exist but info is insufficient or ambiguous


class AuthorityType(str, Enum):
    """Kind of authority. Used both for the *type of a citation as written*
    (identified from its text) and for the *declared type of a supplied
    source*. Classification only — it says nothing about weight or validity."""

    CASE_LAW = "CASE_LAW"
    STATUTE = "STATUTE"
    REGULATION = "REGULATION"
    CONSTITUTIONAL_PROVISION = "CONSTITUTIONAL_PROVISION"
    SECONDARY_SOURCE = "SECONDARY_SOURCE"
    UNKNOWN = "UNKNOWN"


# Relationships the agent may leave un-flagged for review. Everything else
# is always sent to a human: an adverse or incomplete finding must be looked
# at before anyone relies on it, and an LLM-derived adverse finding should
# never silently accuse an advocate of mis-citing. Change this one set to
# change the policy.
AUTO_CLEAR_RELATIONSHIPS = frozenset({CitationRelationship.SUPPORTS})

# Relationships that are only meaningful with a verbatim quote behind them.
QUOTE_REQUIRED_RELATIONSHIPS = frozenset(
    {
        CitationRelationship.SUPPORTS,
        CitationRelationship.PARTIALLY_SUPPORTS,
        CitationRelationship.CONTRADICTS,
    }
)

# Claim types that do not, by themselves, call for legal authority.
NON_AUTHORITY_CLAIM_TYPES = frozenset({ClaimType.FACTUAL, ClaimType.PROCEDURAL})


def _blank_to_none(value):
    if isinstance(value, str) and not value.strip():
        return None
    return value


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


class SourceProvenance(BaseModel):
    """Exactly where a finding's evidence came from.

    Every optional field is populated only if the supplied authority actually
    established it; nothing is defaulted, inferred, or filled in by a model.
    `exact_text` (when present) is a verbatim span of the supplied authority
    text — the agent verifies that before constructing this object.
    """

    source_id: str
    source_type: AuthorityType = AuthorityType.UNKNOWN
    title: Optional[str] = None
    citation: Optional[str] = None
    exact_text: Optional[str] = None
    paragraph: Optional[str] = None
    section: Optional[str] = None
    url: Optional[str] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("source_id")
    @classmethod
    def _source_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("SourceProvenance.source_id must not be blank.")
        return v

    @field_validator("exact_text", mode="after")
    @classmethod
    def _exact_text_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("exact_text, when present, must not be blank.")
        return v


# --------------------------------------------------------------------------
# Input contracts
# --------------------------------------------------------------------------


class CitedAuthority(BaseModel):
    """One citation exactly as it appeared in the case material.

    `authority_id` is optional. Supply it only if a trusted upstream process
    has already resolved the citation to a specific supplied authority; when
    present it is the sole basis for matching. Otherwise the citation text is
    matched against supplied authorities (see citations.py).
    """

    citation_text: str
    authority_id: Optional[str] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("citation_text")
    @classmethod
    def _citation_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("citation_text must not be blank.")
        return v

    @field_validator("authority_id", mode="before")
    @classmethod
    def _blank_id_is_none(cls, v):
        return _blank_to_none(v)


class LegalProposition(BaseModel):
    """A legal claim plus whatever authorities were cited for it.

    `citations` may be given as plain strings; blank strings are dropped, so
    a proposition whose only "citation" is blank is treated as uncited.
    """

    claim_id: str
    claim_text: str
    claim_type: ClaimType = ClaimType.LEGAL
    citations: list[CitedAuthority] = Field(default_factory=list)
    source: Optional[SourceReference] = None  # where in the case material the proposition appears

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

    @field_validator("citations", mode="before")
    @classmethod
    def _coerce_citations(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        if isinstance(v, (list, tuple)):
            out = []
            for item in v:
                if isinstance(item, str):
                    if item.strip():
                        out.append({"citation_text": item})
                else:
                    out.append(item)
            return out
        return v

    @classmethod
    def from_claim(cls, claim: Claim, citations: Optional[list] = None) -> "LegalProposition":
        """Chain from a CaseUnderstandingAgent claim, keeping its provenance."""
        return cls(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            citations=citations or [],
            source=claim.source,
        )


class AuthorityPassage(BaseModel):
    """One located unit of authority text (a paragraph, a section, a clause).

    `paragraph` / `section` are only what the source data says — never
    guessed. Integers are accepted and stored as strings ("12", "12A").
    """

    passage_id: Optional[str] = None
    text: str = ""
    paragraph: Optional[str] = None
    section: Optional[str] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("paragraph", "section", mode="before")
    @classmethod
    def _to_clean_string(cls, v):
        if isinstance(v, bool):
            raise ValueError("paragraph/section must be a string or integer, not a boolean.")
        if isinstance(v, int):
            v = str(v)
        return _blank_to_none(v.strip() if isinstance(v, str) else v)


class SuppliedAuthority(BaseModel):
    """Authority data handed to the agent (by the caller now, by a retriever
    later). The agent treats this — and only this — as legal evidence.

    Text may be given as structured `passages` (preferred: it carries
    paragraph/section locators) or as a single `text` blob. If both are
    given, non-blank `passages` win. An authority with no usable text is
    legal input: it yields REQUIRES_HUMAN_REVIEW, not an exception.
    """

    authority_id: str
    source_type: AuthorityType = AuthorityType.UNKNOWN
    title: Optional[str] = None
    citation: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)  # e.g. parallel citations from the source
    url: Optional[str] = None
    text: str = ""
    passages: list[AuthorityPassage] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("authority_id")
    @classmethod
    def _id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("authority_id must not be blank.")
        return v

    @field_validator("title", "citation", "url", mode="before")
    @classmethod
    def _blank_metadata_is_none(cls, v):
        return _blank_to_none(v)

    @model_validator(mode="after")
    def _assign_unique_passage_ids(self) -> "SuppliedAuthority":
        used = {p.passage_id for p in self.passages if p.passage_id}
        explicit = [p.passage_id for p in self.passages if p.passage_id]
        if len(explicit) != len(set(explicit)):
            raise ValueError(f"Authority {self.authority_id!r} has duplicate passage_id values.")
        counter = 0
        for passage in self.passages:
            if passage.passage_id:
                continue
            counter += 1
            while f"P{counter}" in used:
                counter += 1
            passage.passage_id = f"P{counter}"
            used.add(passage.passage_id)
        return self

    def usable_passages(self) -> list[AuthorityPassage]:
        """The passages the agent may compare against: non-blank structured
        passages if there are any, else the single text blob."""
        structured = [p for p in self.passages if p.text.strip()]
        if structured:
            return structured
        if self.text.strip():
            return [AuthorityPassage(passage_id="P1", text=self.text)]
        return []

    def has_identifying_metadata(self) -> bool:
        """True if a human could tell what this source is (beyond an opaque id)."""
        return bool(self.title or self.citation)

    def provenance(self, passage: Optional[AuthorityPassage] = None,
                   exact_text: Optional[str] = None) -> SourceProvenance:
        """Build provenance strictly from this authority's own data."""
        return SourceProvenance(
            source_id=self.authority_id,
            source_type=self.source_type,
            title=self.title,
            citation=self.citation,
            exact_text=exact_text,
            paragraph=passage.paragraph if passage else None,
            section=passage.section if passage else None,
            url=self.url,
        )


class AuthorityCitationInput(BaseModel):
    case_id: str
    propositions: list[LegalProposition]  # required: validators do not run on defaults
    authorities: list[SuppliedAuthority] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("propositions")
    @classmethod
    def _at_least_one_proposition(cls, v: list[LegalProposition]) -> list[LegalProposition]:
        if not v:
            raise ValueError("AuthorityCitationAgent requires at least one proposition to verify.")
        ids = [p.claim_id for p in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Proposition claim_id values must be unique within a run.")
        return v

    @field_validator("authorities")
    @classmethod
    def _unique_authority_ids(cls, v: list[SuppliedAuthority]) -> list[SuppliedAuthority]:
        ids = [a.authority_id for a in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Supplied authority_id values must be unique within a run.")
        return v


# --------------------------------------------------------------------------
# Output contracts
# --------------------------------------------------------------------------


class CitationFinding(BaseModel):
    """The verification result for one (proposition, citation) pair — or for
    one uncited proposition. Stored by the backend as-is.

    The validator below is the last line of defence: whatever code path built
    this object, a finding that breaks the anti-hallucination rules raises.
    """

    finding_id: str
    claim_id: str
    citation_text: Optional[str] = None      # None only for an uncited proposition
    citation_type: AuthorityType = AuthorityType.UNKNOWN
    authority_id: Optional[str] = None       # id of the supplied authority actually used, if any
    relationship: CitationRelationship
    explanation: str = Field(min_length=1)
    sources: list[SourceProvenance] = Field(default_factory=list)
    requires_human_review: bool
    uncited: bool = False

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _enforce_invariants(self) -> "CitationFinding":
        rel = self.relationship

        if not self.explanation.strip():
            raise ValueError("explanation must not be blank.")

        if self.uncited:
            if rel != CitationRelationship.REQUIRES_HUMAN_REVIEW:
                raise ValueError("An uncited proposition can only be REQUIRES_HUMAN_REVIEW.")
            if self.citation_text is not None or self.authority_id is not None or self.sources:
                raise ValueError(
                    "An uncited proposition has no citation, authority or sources; none may be attached."
                )
        elif not (self.citation_text and self.citation_text.strip()):
            raise ValueError("citation_text is required unless the finding is for an uncited proposition.")

        if rel not in AUTO_CLEAR_RELATIONSHIPS and not self.requires_human_review:
            raise ValueError(f"{rel.value} findings must have requires_human_review=True.")

        if rel == CitationRelationship.SOURCE_NOT_FOUND:
            if self.sources or self.authority_id is not None:
                raise ValueError(
                    "SOURCE_NOT_FOUND means nothing was found: sources must be empty and "
                    "authority_id must be None. Provenance is never invented."
                )

        if rel in QUOTE_REQUIRED_RELATIONSHIPS:
            if not self.authority_id:
                raise ValueError(f"{rel.value} requires the authority_id of the source used.")
            if not any(s.exact_text for s in self.sources):
                raise ValueError(
                    f"{rel.value} requires at least one source carrying verbatim exact_text."
                )

        if rel == CitationRelationship.DOES_NOT_SUPPORT:
            if not self.authority_id or not self.sources:
                raise ValueError("DOES_NOT_SUPPORT requires the authority_id and provenance of the source examined.")

        if self.authority_id is not None:
            for source in self.sources:
                if source.source_id != self.authority_id:
                    raise ValueError(
                        f"Source {source.source_id!r} does not belong to authority {self.authority_id!r}."
                    )
        return self


class RejectedModelOutput(BaseModel):
    """A model assessment the agent refused to trust, kept for audit. The
    finding built in its place never repeats the model's rejected content."""

    claim_id: str
    citation_text: Optional[str] = None
    raw: dict
    reasons: list[str]


class AuthorityCitationResult(BaseModel):
    """The complete, deterministic output of one agent run. Every cited
    authority and every uncited legal proposition yields a finding; nothing
    is silently dropped."""

    case_id: str
    findings: list[CitationFinding] = Field(default_factory=list)
    rejected_model_outputs: list[RejectedModelOutput] = Field(default_factory=list)
    propositions_processed: list[str] = Field(default_factory=list)
    skipped_claim_ids: list[str] = Field(default_factory=list)  # uncited but not legal propositions
    warnings: list[str] = Field(default_factory=list)
    degraded: bool = False

    model_config = ConfigDict(extra="forbid")
