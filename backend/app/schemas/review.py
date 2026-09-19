"""Pydantic validation schemas for Reviews using finding_type + finding_id."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ReviewCreate(BaseModel):
    finding_type: Literal["CLAIM", "CONFLICT", "CITATION_FINDING", "COUNTER_ARGUMENT", "EVIDENCE"] = Field(
        ..., description="Valid reviewable finding type"
    )
    finding_id: str = Field(..., min_length=1)
    decision: Literal["ACCEPTED", "REJECTED", "EDITED", "NEEDS_VERIFICATION"] = Field(...)
    comment: str | None = None
    new_status: str | None = None


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    review_id: str
    case_id: str
    finding_type: str
    finding_id: str
    reviewer_id: str
    reviewer_name: str
    decision: str
    comment: str | None = None
    previous_status: str | None = None
    new_status: str | None = None
    created_at: str
