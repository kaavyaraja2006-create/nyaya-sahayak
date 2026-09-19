"""Pydantic validation schemas for AnalysisRun and AuditEvent."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict


class AnalysisRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    case_id: str
    status: str
    stage_index: int = 0
    progress: int = 0
    message: str | None = None
    summary_json: Any = None
    error: str | None = None
    ai_mode: str | None = None
    started_at: str
    completed_at: str | None = None


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    log_id: str
    case_id: str
    actor: str
    actor_type: str
    action: str
    object_type: str
    object_id: str | None = None
    previous_state: Any = None
    new_state: Any = None
    details: Any = None
    created_at: str
