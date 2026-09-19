"""Authority and CitationFinding MongoDB repositories."""
from __future__ import annotations

import re
from typing import Any
from ..models.authority import Authority, CitationFinding
from .base_repository import BaseRepository


class AuthorityRepository(BaseRepository[Authority]):
    def __init__(self) -> None:
        super().__init__("authorities")

    def get_by_id(self, authority_id: str) -> Authority | None:
        raw = self.find_one({"$or": [{"authority_id": authority_id}, {"id": authority_id}]})
        return Authority.from_dict(raw) if raw else None

    def list_all(self, limit: int = 100) -> list[Authority]:
        raws = self.find_many({}, limit=limit)
        return [Authority.from_dict(r) for r in raws]

    def search(self, query: str, limit: int = 10) -> list[Authority]:
        regex = re.compile(re.escape(query.strip()), re.IGNORECASE)
        raws = self.find_many(
            {"$or": [{"title": regex}, {"passage": regex}, {"citation": regex}]}, limit=limit
        )
        return [Authority.from_dict(r) for r in raws]

    def create(self, auth: Authority) -> Authority:
        self.insert(auth.to_dict())
        return auth


class CitationRepository(BaseRepository[CitationFinding]):
    def __init__(self) -> None:
        super().__init__("citations")

    def list_by_case(self, case_id: str) -> list[CitationFinding]:
        raws = self.find_many({"case_id": case_id})
        return [CitationFinding.from_dict(r) for r in raws]

    def create(self, cit: CitationFinding) -> CitationFinding:
        self.insert(cit.to_dict())
        return cit


authority_repository = AuthorityRepository()
citation_repository = CitationRepository()
