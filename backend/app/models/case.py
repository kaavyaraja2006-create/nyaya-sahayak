"""User and Case domain models."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def uid() -> str:
    return uuid.uuid4().hex


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class User:
    id: str = field(default_factory=uid)
    full_name: str = ""
    email: str = ""
    phone: str | None = None
    password_hash: str = ""
    role: str = "OTHER"
    organization: str | None = None
    registration_number: str | None = None
    experience_years: int | None = None
    specialization: str | None = None
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "password_hash": self.password_hash,
            "role": self.role,
            "organization": self.organization,
            "registration_number": self.registration_number,
            "experience_years": self.experience_years,
            "specialization": self.specialization,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> User:
        return cls(
            id=data.get("id") or uid(),
            full_name=data.get("full_name", ""),
            email=data.get("email", ""),
            phone=data.get("phone"),
            password_hash=data.get("password_hash", ""),
            role=data.get("role", "OTHER"),
            organization=data.get("organization"),
            registration_number=data.get("registration_number"),
            experience_years=data.get("experience_years"),
            specialization=data.get("specialization"),
            created_at=data.get("created_at") or utcnow(),
            updated_at=data.get("updated_at") or utcnow(),
        )


@dataclass
class Case:
    id: str = field(default_factory=uid)
    case_id: str = ""  # NS-2026-001
    user_id: str = ""
    name: str = ""
    case_number: str | None = None
    case_type: str | None = None
    jurisdiction: str | None = None
    court: str | None = None
    description: str | None = None
    status: str = "DRAFT"
    filed_on: str | None = None
    last_analyzed: str | None = None
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "case_id": self.case_id or self.id,
            "user_id": self.user_id,
            "name": self.name,
            "case_number": self.case_number,
            "case_type": self.case_type,
            "jurisdiction": self.jurisdiction,
            "court": self.court,
            "description": self.description,
            "status": self.status,
            "filed_on": self.filed_on,
            "last_analyzed": self.last_analyzed,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Case:
        return cls(
            id=data.get("id") or uid(),
            case_id=data.get("case_id") or data.get("id") or "",
            user_id=data.get("user_id", ""),
            name=data.get("name", ""),
            case_number=data.get("case_number"),
            case_type=data.get("case_type"),
            jurisdiction=data.get("jurisdiction"),
            court=data.get("court"),
            description=data.get("description"),
            status=data.get("status", "DRAFT"),
            filed_on=data.get("filed_on"),
            last_analyzed=data.get("last_analyzed"),
            created_at=data.get("created_at") or utcnow(),
            updated_at=data.get("updated_at") or utcnow(),
        )
