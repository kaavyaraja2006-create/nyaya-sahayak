"""Pydantic validation schemas for Evidence, Relationship, and Conflicts."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict
from .claim import SourceReferenceSchema


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    evidence_id: str
    case_id: str
    evidence_type: str
    description: str
    source_reference: SourceReferenceSchema
    item_date: str | None = None
    meta_json: Any = None
    created_at: str


class RelationshipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    relationship_id: str
    case_id: str
    claim_id: str
    evidence_id: str
    relationship: str
    reason: str | None = None
    assessment_signal: str | None = None
    created_at: str


class ConflictResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    finding_id: str
    case_id: str
    kind: str
    category: str | None = None
    group_name: str
    priority: str
    claim_id: str | None = None
    title: str
    reason: str | None = None
    conflict_type: str | None = None
    comparison_json: Any = None
    relationship_ids: list[str] = []
    evidence_ids: list[str] = []
    authority_id: str | None = None
    status: str
    requires_human_review: bool = True
    created_at: str
