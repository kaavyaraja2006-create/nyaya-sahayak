"""A tiny in-memory stand-in for the PyMongo collections the repositories use.

Only the operators the repository layer actually issues are implemented:
equality matching, `$or`, compiled-regex values, sort and limit. It exists so
the pipeline tests can run against the real repository code without a MongoDB
server; it is not a general-purpose Mongo emulator.
"""
from __future__ import annotations

import re
from typing import Any


def _matches(document: dict, query: dict) -> bool:
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, clause) for clause in expected):
                return False
            continue
        actual = document.get(key)
        if isinstance(expected, re.Pattern):
            if not isinstance(actual, str) or not expected.search(actual):
                return False
        elif actual != expected:
            return False
    return True


class FakeCursor:
    def __init__(self, documents: list[dict]) -> None:
        self._documents = documents

    def sort(self, spec):
        for key, direction in reversed(list(spec)):
            self._documents.sort(key=lambda d: (d.get(key) is None, d.get(key)), reverse=direction < 0)
        return self

    def limit(self, count: int):
        if count > 0:
            self._documents = self._documents[:count]
        return self

    def __iter__(self):
        return iter(self._documents)


class FakeCollection:
    def __init__(self, name: str) -> None:
        self.name = name
        self.documents: list[dict] = []

    def find_one(self, query: dict) -> dict | None:
        for document in self.documents:
            if _matches(document, query):
                return dict(document)
        return None

    def find(self, query: dict) -> FakeCursor:
        return FakeCursor([dict(d) for d in self.documents if _matches(d, query)])

    def insert_one(self, document: dict):
        self.documents.append(dict(document))
        return type("InsertResult", (), {"inserted_id": len(self.documents)})()

    def update_one(self, query: dict, update: dict):
        changes = update.get("$set", update)
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                merged = {**document, **changes}
                self.documents[index] = merged
                return type("UpdateResult", (), {"modified_count": 1, "matched_count": 1})()
        return type("UpdateResult", (), {"modified_count": 0, "matched_count": 0})()

    def delete_one(self, query: dict):
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                del self.documents[index]
                return type("DeleteResult", (), {"deleted_count": 1})()
        return type("DeleteResult", (), {"deleted_count": 0})()

    def delete_many(self, query: dict):
        before = len(self.documents)
        self.documents = [d for d in self.documents if not _matches(d, query)]
        return type("DeleteResult", (), {"deleted_count": before - len(self.documents)})()

    def create_index(self, *args: Any, **kwargs: Any) -> str:
        return "index"


class FakeDatabase:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection(name))

    def __getattr__(self, name: str) -> FakeCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def command(self, *args: Any, **kwargs: Any) -> dict:
        return {"ok": 1}

    def reset(self) -> None:
        self._collections.clear()


fake_db = FakeDatabase()


def install(monkeypatch=None) -> FakeDatabase:
    """Point app.database at the fake. Call before importing app.main."""
    from backend.app import database

    fake_db.reset()
    database._db = fake_db  # type: ignore[attr-defined]
    database.get_db = lambda: fake_db  # type: ignore[assignment]
    database.get_collection = lambda name: fake_db[name]  # type: ignore[assignment]

    # Repositories resolve get_collection through their own module import.
    from backend.app.repositories import base_repository

    base_repository.get_collection = lambda name: fake_db[name]  # type: ignore[assignment]
    return fake_db
