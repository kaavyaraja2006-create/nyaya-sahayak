"""Document and DocumentChunk domain models."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def uid() -> str:
    return uuid.uuid4().hex


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DocumentChunk:
    chunk_index: int = 0
    page_number: int = 1
    paragraph_number: int | None = None
    text: str = ""

    def to_dict(self) -> dict:
        return {
            "chunk_index": self.chunk_index,
            "page_number": self.page_number,
            "paragraph_number": self.paragraph_number,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DocumentChunk:
        return cls(
            chunk_index=data.get("chunk_index", 0),
            page_number=data.get("page_number", 1),
            paragraph_number=data.get("paragraph_number"),
            text=data.get("text", ""),
        )


@dataclass
class Document:
    id: str = field(default_factory=uid)
    document_id: str = ""  # DOC-001
    case_id: str = ""
    filename: str = ""
    document_type: str = "Other"
    category: str = "Reports"
    storage_path: str = ""
    mime_type: str | None = None
    size_bytes: int = 0
    page_count: int = 0
    extracted_text: str | None = None
    pages_json: list | None = None
    entities_json: list | None = None
    chunks: list[DocumentChunk] = field(default_factory=list)
    status: str = "processing"
    is_transcript: bool = False
    uploaded_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id or self.id,
            "case_id": self.case_id,
            "filename": self.filename,
            "document_type": self.document_type,
            "category": self.category,
            "storage_path": self.storage_path,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "page_count": self.page_count,
            "extracted_text": self.extracted_text,
            "pages_json": self.pages_json,
            "entities_json": self.entities_json,
            "chunks": [c.to_dict() for c in self.chunks],
            "status": self.status,
            "is_transcript": self.is_transcript,
            "uploaded_at": self.uploaded_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Document:
        chunks_raw = data.get("chunks") or []
        chunks = [DocumentChunk.from_dict(c) if isinstance(c, dict) else c for c in chunks_raw]
        return cls(
            id=data.get("id") or uid(),
            document_id=data.get("document_id") or data.get("id") or "",
            case_id=data.get("case_id", ""),
            filename=data.get("filename", ""),
            document_type=data.get("document_type", "Other"),
            category=data.get("category", "Reports"),
            storage_path=data.get("storage_path", ""),
            mime_type=data.get("mime_type"),
            size_bytes=data.get("size_bytes", 0),
            page_count=data.get("page_count", 0),
            extracted_text=data.get("extracted_text"),
            pages_json=data.get("pages_json"),
            entities_json=data.get("entities_json"),
            chunks=chunks,
            status=data.get("status", "processing"),
            is_transcript=data.get("is_transcript", False),
            uploaded_at=data.get("uploaded_at") or utcnow(),
        )
