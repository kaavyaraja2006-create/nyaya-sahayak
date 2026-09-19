"""AnalysisRun and AuditEvent domain models."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def uid() -> str:
    return uuid.uuid4().hex


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AnalysisRun:
    id: str = field(default_factory=uid)
    run_id: str = ""
    case_id: str = ""
    status: str = "running"  # running, completed, failed
    stage_index: int = 0
    progress: int = 0
    message: str | None = None
    summary_json: dict | list | None = None
    error: str | None = None
    ai_mode: str | None = None
    started_at: str = field(default_factory=utcnow)
    completed_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": self.run_id or self.id,
            "case_id": self.case_id,
            "status": self.status,
            "stage_index": self.stage_index,
            "progress": self.progress,
            "message": self.message,
            "summary_json": self.summary_json,
            "error": self.error,
            "ai_mode": self.ai_mode,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AnalysisRun:
        return cls(
            id=data.get("id") or uid(),
            run_id=data.get("run_id") or data.get("id") or "",
            case_id=data.get("case_id", ""),
            status=data.get("status", "running"),
            stage_index=data.get("stage_index", 0),
            progress=data.get("progress", 0),
            message=data.get("message"),
            summary_json=data.get("summary_json"),
            error=data.get("error"),
            ai_mode=data.get("ai_mode"),
            started_at=data.get("started_at") or utcnow(),
            completed_at=data.get("completed_at"),
        )


@dataclass
class AuditEvent:
    id: str = field(default_factory=uid)
    log_id: str = ""
    case_id: str = ""
    actor: str = "System"
    actor_type: str = "system"  # AI, USER, SYSTEM
    action: str = ""
    object_type: str = "case"
    object_id: str | None = None
    previous_state: str | dict | None = None
    new_state: str | dict | None = None
    details: str | dict | None = None
    created_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "log_id": self.log_id or self.id,
            "case_id": self.case_id,
            "actor": self.actor,
            "actor_type": self.actor_type,
            "action": self.action,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "details": self.details,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AuditEvent:
        return cls(
            id=data.get("id") or uid(),
            log_id=data.get("log_id") or data.get("id") or "",
            case_id=data.get("case_id", ""),
            actor=data.get("actor", "System"),
            actor_type=data.get("actor_type", "system"),
            action=data.get("action", ""),
            object_type=data.get("object_type", "case"),
            object_id=data.get("object_id"),
            previous_state=data.get("previous_state"),
            new_state=data.get("new_state"),
            details=data.get("details"),
            created_at=data.get("created_at") or utcnow(),
        )
