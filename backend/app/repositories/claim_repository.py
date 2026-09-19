"""Claim, Evidence, Relationship, Conflict MongoDB repositories."""
from __future__ import annotations

from typing import Any
from ..models.claim import Claim
from ..models.evidence import Evidence
from ..models.relationship import Relationship
from ..models.conflict import Conflict
from .base_repository import BaseRepository


class ClaimRepository(BaseRepository[Claim]):
    def __init__(self) -> None:
        super().__init__("claims")

    def get_by_id(self, claim_id: str, case_id: str | None = None) -> Claim | None:
        query: dict[str, Any] = {"$or": [{"claim_id": claim_id}, {"id": claim_id}]}
        if case_id:
            query["case_id"] = case_id
        raw = self.find_one(query)
        return Claim.from_dict(raw) if raw else None

    def list_by_case(self, case_id: str) -> list[Claim]:
        raws = self.find_many({"case_id": case_id})
        return [Claim.from_dict(r) for r in raws]

    def create(self, claim: Claim) -> Claim:
        self.insert(claim.to_dict())
        return claim

    def update(self, claim: Claim) -> Claim:
        self.update_one({"id": claim.id}, claim.to_dict())
        return claim


class EvidenceRepository(BaseRepository[Evidence]):
    def __init__(self) -> None:
        super().__init__("evidence")

    def get_by_id(self, evidence_id: str, case_id: str | None = None) -> Evidence | None:
        query: dict[str, Any] = {"$or": [{"evidence_id": evidence_id}, {"id": evidence_id}]}
        if case_id:
            query["case_id"] = case_id
        raw = self.find_one(query)
        return Evidence.from_dict(raw) if raw else None

    def list_by_case(self, case_id: str) -> list[Evidence]:
        raws = self.find_many({"case_id": case_id})
        return [Evidence.from_dict(r) for r in raws]

    def create(self, ev: Evidence) -> Evidence:
        self.insert(ev.to_dict())
        return ev


class RelationshipRepository(BaseRepository[Relationship]):
    def __init__(self) -> None:
        super().__init__("relationships")

    def list_by_case(self, case_id: str) -> list[Relationship]:
        raws = self.find_many({"case_id": case_id})
        return [Relationship.from_dict(r) for r in raws]

    def list_by_claim(self, case_id: str, claim_id: str) -> list[Relationship]:
        raws = self.find_many({"case_id": case_id, "claim_id": claim_id})
        return [Relationship.from_dict(r) for r in raws]

    def create(self, rel: Relationship) -> Relationship:
        self.insert(rel.to_dict())
        return rel


class ConflictRepository(BaseRepository[Conflict]):
    def __init__(self) -> None:
        super().__init__("conflicts")

    def get_by_id(self, conflict_id: str, case_id: str | None = None) -> Conflict | None:
        query: dict[str, Any] = {"$or": [{"finding_id": conflict_id}, {"id": conflict_id}]}
        if case_id:
            query["case_id"] = case_id
        raw = self.find_one(query)
        return Conflict.from_dict(raw) if raw else None

    def list_by_case(self, case_id: str) -> list[Conflict]:
        raws = self.find_many({"case_id": case_id})
        return [Conflict.from_dict(r) for r in raws]

    def create(self, conf: Conflict) -> Conflict:
        self.insert(conf.to_dict())
        return conf


claim_repository = ClaimRepository()
evidence_repository = EvidenceRepository()
relationship_repository = RelationshipRepository()
conflict_repository = ConflictRepository()
