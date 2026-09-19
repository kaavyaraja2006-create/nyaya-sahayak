"""Evidence domain model."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from .claim import SourceReference


def uid() -> str:
    return uuid.uuid4().hex


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Evidence:
    id: str = field(default_factory=uid)
    evidence_id: str = ""  # E-01
    case_id: str = ""
    evidence_type: str = "Document"
    description: str = ""
    source_reference: SourceReference = field(default_factory=SourceReference)
    item_date: str | None = None
    meta_json: dict | list | None = None
    created_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "evidence_id": self.evidence_id or self.id,
            "case_id": self.case_id,
            "evidence_type": self.evidence_type,
            "description": self.description,
            "source_reference": self.source_reference.to_dict(),
            "item_date": self.item_date,
            "meta_json": self.meta_json,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Evidence:
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
            evidence_id=data.get("evidence_id") or data.get("id") or "",
            case_id=data.get("case_id", ""),
            evidence_type=data.get("evidence_type", "Document"),
            description=data.get("description", ""),
            source_reference=sr or SourceReference(),
            item_date=data.get("item_date"),
            meta_json=data.get("meta_json"),
            created_at=data.get("created_at") or utcnow(),
        )
