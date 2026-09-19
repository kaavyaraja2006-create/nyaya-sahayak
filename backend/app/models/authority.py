"""Authority, SourceProvenance and CitationFinding domain models.

The CitationFinding here mirrors the AuthorityCitationAgent's own contract
(agents/authority_citation/schemas.py) field for field. Nothing is mapped
into a generic relevance vocabulary: the six CitationRelationship values and
the full SourceProvenance list are persisted exactly as the agent produced
them, because the verification meaning is the point of the finding.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def uid() -> str:
    return uuid.uuid4().hex


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class CitationRelationship(str, Enum):
    """Exactly the agent's six values. Nothing else may be stored."""

    SUPPORTS = "SUPPORTS"
    PARTIALLY_SUPPORTS = "PARTIALLY_SUPPORTS"
    DOES_NOT_SUPPORT = "DOES_NOT_SUPPORT"
    CONTRADICTS = "CONTRADICTS"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"


class AuthorityType(str, Enum):
    CASE_LAW = "CASE_LAW"
    STATUTE = "STATUTE"
    REGULATION = "REGULATION"
    CONSTITUTIONAL_PROVISION = "CONSTITUTIONAL_PROVISION"
    SECONDARY_SOURCE = "SECONDARY_SOURCE"
    UNKNOWN = "UNKNOWN"


def _coerce_relationship(value: str | None) -> str:
    """Unknown values are never quietly downgraded to something reassuring."""
    if value in {r.value for r in CitationRelationship}:
        return str(value)
    return CitationRelationship.REQUIRES_HUMAN_REVIEW.value


def _coerce_authority_type(value: str | None) -> str:
    if value in {t.value for t in AuthorityType}:
        return str(value)
    return AuthorityType.UNKNOWN.value


@dataclass
class Authority:
    id: str = field(default_factory=uid)
    authority_id: str = ""
    label: str | None = None
    title: str = ""
    court: str | None = None
    year: int | None = None
    citation: str | None = None
    jurisdiction: str | None = None
    paragraph: int | None = None
    passage: str = ""
    source_type: str | None = None
    source_file: str | None = None
    corpus: str | None = None
    aliases: list[str] = field(default_factory=list)
    url: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "authority_id": self.authority_id or self.id,
            "label": self.label,
            "title": self.title,
            "court": self.court,
            "year": self.year,
            "citation": self.citation,
            "jurisdiction": self.jurisdiction,
            "paragraph": self.paragraph,
            "passage": self.passage,
            "source_type": self.source_type,
            "source_file": self.source_file,
            "corpus": self.corpus,
            "aliases": list(self.aliases),
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Authority:
        return cls(
            id=data.get("id") or uid(),
            authority_id=data.get("authority_id") or data.get("id") or "",
            label=data.get("label"),
            title=data.get("title", ""),
            court=data.get("court"),
            year=data.get("year"),
            citation=data.get("citation"),
            jurisdiction=data.get("jurisdiction"),
            paragraph=data.get("paragraph"),
            passage=data.get("passage", ""),
            source_type=data.get("source_type"),
            source_file=data.get("source_file"),
            corpus=data.get("corpus"),
            aliases=list(data.get("aliases") or []),
            url=data.get("url"),
        )


@dataclass
class SourceProvenance:
    """Where a finding's evidence came from — stored whole, never flattened.

    `exact_text` is the verbatim span of the supplied authority that the agent
    verified. Losing it would leave a verification result no human can check,
    which defeats the purpose of the finding.
    """

    source_id: str = ""
    source_type: str = AuthorityType.UNKNOWN.value
    title: str | None = None
    citation: str | None = None
    exact_text: str | None = None
    paragraph: str | None = None
    section: str | None = None
    url: str | None = None

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "title": self.title,
            "citation": self.citation,
            "exact_text": self.exact_text,
            "paragraph": self.paragraph,
            "section": self.section,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SourceProvenance:
        return cls(
            source_id=data.get("source_id", ""),
            source_type=_coerce_authority_type(data.get("source_type")),
            title=data.get("title"),
            citation=data.get("citation"),
            exact_text=data.get("exact_text"),
            paragraph=data.get("paragraph"),
            section=data.get("section"),
            url=data.get("url"),
        )


@dataclass
class CitationFinding:
    """One (proposition, citation) verification result, or one uncited
    proposition. Field-for-field the agent's CitationFinding, plus the
    persistence keys (`id`, `case_id`, `run_id`, `created_at`).
    """

    id: str = field(default_factory=uid)
    finding_id: str = ""            # CF-001, from the agent
    case_id: str = ""
    run_id: str | None = None
    claim_id: str = ""
    citation_text: str | None = None
    citation_type: str = AuthorityType.UNKNOWN.value
    authority_id: str | None = None
    relationship: str = CitationRelationship.REQUIRES_HUMAN_REVIEW.value
    explanation: str = ""
    sources: list[SourceProvenance] = field(default_factory=list)
    requires_human_review: bool = True
    uncited: bool = False
    created_at: str = field(default_factory=utcnow)

    @property
    def citation_id(self) -> str:
        """Back-compat alias for callers that used the old key."""
        return self.finding_id or self.id

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "finding_id": self.finding_id or self.id,
            "case_id": self.case_id,
            "run_id": self.run_id,
            "claim_id": self.claim_id,
            "citation_text": self.citation_text,
            "citation_type": self.citation_type,
            "authority_id": self.authority_id,
            "relationship": self.relationship,
            "explanation": self.explanation,
            "sources": [s.to_dict() for s in self.sources],
            "requires_human_review": self.requires_human_review,
            "uncited": self.uncited,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CitationFinding:
        sources_raw = data.get("sources") or []
        return cls(
            id=data.get("id") or uid(),
            finding_id=data.get("finding_id") or data.get("id") or "",
            case_id=data.get("case_id", ""),
            run_id=data.get("run_id"),
            claim_id=data.get("claim_id", ""),
            citation_text=data.get("citation_text"),
            citation_type=_coerce_authority_type(data.get("citation_type")),
            authority_id=data.get("authority_id"),
            relationship=_coerce_relationship(data.get("relationship")),
            explanation=data.get("explanation", ""),
            sources=[
                s if isinstance(s, SourceProvenance) else SourceProvenance.from_dict(s)
                for s in sources_raw
            ],
            requires_human_review=bool(data.get("requires_human_review", True)),
            uncited=bool(data.get("uncited", False)),
            created_at=data.get("created_at") or utcnow(),
        )
