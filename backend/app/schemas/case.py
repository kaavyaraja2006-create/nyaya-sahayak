"""Pydantic validation schemas for Cases and Documents."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class CaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    case_number: str | None = None
    case_type: str | None = None
    jurisdiction: str | None = None
    court: str | None = None
    description: str | None = None
    filed_on: str | None = None


class CaseUpdate(BaseModel):
    name: str | None = None
    case_number: str | None = None
    case_type: str | None = None
    jurisdiction: str | None = None
    court: str | None = None
    description: str | None = None
    status: str | None = None


class CaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    user_id: str
    name: str
    case_number: str | None = None
    case_type: str | None = None
    jurisdiction: str | None = None
    court: str | None = None
    description: str | None = None
    status: str
    filed_on: str | None = None
    last_analyzed: str | None = None
    created_at: str
    updated_at: str


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    case_id: str
    filename: str
    document_type: str
    category: str
    storage_path: str
    mime_type: str | None = None
    size_bytes: int = 0
    page_count: int = 0
    status: str
    is_transcript: bool = False
    uploaded_at: str
