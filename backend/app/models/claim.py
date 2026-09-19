"""SourceReference embedded provenance and Claim domain models."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def uid() -> str:
    return uuid.uuid4().hex


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SourceReference:
    """Embedded provenance structure — NOT a separate MongoDB collection."""
    source_document_id: str | None = None
    page: int | None = None
    paragraph: int | None = None
    quote: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    timestamp: str | None = None

    def to_dict(self) -> dict:
        return {
            "source_document_id": self.source_document_id,
            "page": self.page,
            "paragraph": self.paragraph,
            "quote": self.quote,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SourceReference:
        return cls(
            source_document_id=data.get("source_document_id"),
            page=data.get("page"),
            paragraph=data.get("paragraph"),
            quote=data.get("quote"),
            line_start=data.get("line_start"),
            line_end=data.get("line_end"),
            timestamp=data.get("timestamp"),
        )


@dataclass
class Claim:
    id: str = field(default_factory=uid)
    claim_id: str = ""  # C-01
    case_id: str = ""
    title: str | None = None
    claim_text: str = ""
    claim_type: str | None = None
    speaker: str | None = None
    source_reference: SourceReference = field(default_factory=SourceReference)
    origin_note: str | None = None
    status: str = "needs_review"
    extraction_confidence: float = 0.0
    signals_json: dict | list | None = None
    created_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "claim_id": self.claim_id or self.id,
            "case_id": self.case_id,
            "title": self.title,
            "claim_text": self.claim_text,
            "claim_type": self.claim_type,
            "speaker": self.speaker,
            "source_reference": self.source_reference.to_dict(),
            "origin_note": self.origin_note,
            "status": self.status,
            "extraction_confidence": self.extraction_confidence,
            "signals_json": self.signals_json,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Claim:
        sr_raw = data.get("source_reference")
        if not sr_raw:
            sr_raw = {
                "source_document_id": data.get("source_document_id"),
                "page": data.get("source_page"),
                "paragraph": data.get("source_paragraph"),
                "quote": data.get("source_quote"),
            }
        sr = SourceReference.from_dict(sr_raw) if isinstance(sr_raw, dict) else sr_raw
        return cls(
            id=data.get("id") or uid(),
            claim_id=data.get("claim_id") or data.get("id") or "",
            case_id=data.get("case_id", ""),
            title=data.get("title"),
            claim_text=data.get("claim_text", ""),
            claim_type=data.get("claim_type"),
            speaker=data.get("speaker"),
            source_reference=sr or SourceReference(),
            origin_note=data.get("origin_note"),
            status=data.get("status", "needs_review"),
            extraction_confidence=data.get("extraction_confidence", 0.0),
            signals_json=data.get("signals_json"),
            created_at=data.get("created_at") or utcnow(),
        )
