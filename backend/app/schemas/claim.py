"""Pydantic validation schemas for Claims and SourceReference provenance."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class SourceReferenceSchema(BaseModel):
    source_document_id: str | None = None
    page: int | None = None
    paragraph: int | None = None
    quote: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    timestamp: str | None = None


class ClaimCreate(BaseModel):
    claim_text: str = Field(..., min_length=1)
    claim_type: str | None = None
    speaker: str | None = None
    source_reference: SourceReferenceSchema | None = None
    origin_note: str | None = None


class ClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    claim_id: str
    case_id: str
    title: str | None = None
    claim_text: str
    claim_type: str | None = None
    speaker: str | None = None
    source_reference: SourceReferenceSchema
    origin_note: str | None = None
    status: str
    extraction_confidence: float = 0.0
    signals_json: Any = None
    created_at: str
