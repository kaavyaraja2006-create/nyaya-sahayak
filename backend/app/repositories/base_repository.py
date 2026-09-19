"""Base MongoDB repository with PyMongo access."""
from __future__ import annotations

from typing import Any, Generic, TypeVar
from pymongo.collection import Collection
from ..database import get_collection

T = TypeVar("T")


class BaseRepository(Generic[T]):
    def __init__(self, collection_name: str) -> None:
        self.collection_name = collection_name

    @property
    def collection(self) -> Collection[dict[str, Any]]:
        return get_collection(self.collection_name)

    def _clean_id(self, doc: dict[str, Any] | None) -> dict[str, Any] | None:
        if not doc:
            return None
        doc = dict(doc)
        if "_id" in doc:
            del doc["_id"]
        return doc

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        raw = self.collection.find_one(query)
        return self._clean_id(raw)

    def find_many(
        self, query: dict[str, Any], sort: list[tuple[str, int]] | None = None, limit: int = 0
    ) -> list[dict[str, Any]]:
        cursor = self.collection.find(query)
        if sort:
            cursor = cursor.sort(sort)
        if limit > 0:
            cursor = cursor.limit(limit)
        return [self._clean_id(d) for d in cursor if d]

    def insert(self, data: dict[str, Any]) -> dict[str, Any]:
        cleaned = dict(data)
        if "_id" in cleaned:
            del cleaned["_id"]
        self.collection.insert_one(cleaned)
        return cleaned

    def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> bool:
        res = self.collection.update_one(query, {"$set": update})
        return res.modified_count > 0 or res.matched_count > 0

    def delete_one(self, query: dict[str, Any]) -> bool:
        res = self.collection.delete_one(query)
        return res.deleted_count > 0

    def delete_many(self, query: dict[str, Any]) -> int:
        res = self.collection.delete_many(query)
        return res.deleted_count
