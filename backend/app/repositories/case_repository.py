"""Case and Document MongoDB repositories."""
from __future__ import annotations

from typing import Any
from ..models.case import Case
from ..models.document import Document
from .base_repository import BaseRepository


class CaseRepository(BaseRepository[Case]):
    def __init__(self) -> None:
        super().__init__("cases")

    def get_by_id(self, case_id: str, user_id: str | None = None) -> Case | None:
        query: dict[str, Any] = {"$or": [{"case_id": case_id}, {"id": case_id}]}
        if user_id:
            query["user_id"] = user_id
        raw = self.find_one(query)
        return Case.from_dict(raw) if raw else None

    def list_by_user(self, user_id: str) -> list[Case]:
        raws = self.find_many({"user_id": user_id}, sort=[("updated_at", -1)])
        return [Case.from_dict(r) for r in raws]

    def create(self, case: Case) -> Case:
        self.insert(case.to_dict())
        return case

    def update(self, case: Case) -> Case:
        self.update_one({"id": case.id}, case.to_dict())
        return case

    def delete(self, case_id: str, user_id: str) -> bool:
        return self.delete_one({"$or": [{"case_id": case_id}, {"id": case_id}], "user_id": user_id})


class DocumentRepository(BaseRepository[Document]):
    def __init__(self) -> None:
        super().__init__("documents")

    def get_by_id(self, doc_id: str, case_id: str | None = None) -> Document | None:
        query: dict[str, Any] = {"$or": [{"document_id": doc_id}, {"id": doc_id}]}
        if case_id:
            query["case_id"] = case_id
        raw = self.find_one(query)
        return Document.from_dict(raw) if raw else None

    def list_by_case(self, case_id: str) -> list[Document]:
        raws = self.find_many({"case_id": case_id}, sort=[("uploaded_at", 1)])
        return [Document.from_dict(r) for r in raws]

    def create(self, doc: Document) -> Document:
        self.insert(doc.to_dict())
        return doc

    def update(self, doc: Document) -> Document:
        self.update_one({"id": doc.id}, doc.to_dict())
        return doc

    def delete(self, doc_id: str, case_id: str) -> bool:
        return self.delete_one({"$or": [{"document_id": doc_id}, {"id": doc_id}], "case_id": case_id})


case_repository = CaseRepository()
document_repository = DocumentRepository()
