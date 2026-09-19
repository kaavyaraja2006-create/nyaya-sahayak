"""MongoDB Atlas database connection manager using PyMongo."""
from __future__ import annotations

import logging
from typing import Any
from pymongo import MongoClient, ASCENDING
from pymongo.database import Database
from pymongo.collection import Collection

from .config import settings

log = logging.getLogger("nyayasahayak.database")

_client: MongoClient[dict[str, Any]] | None = None
_db: Database[dict[str, Any]] | None = None


def get_client() -> MongoClient[dict[str, Any]]:
    global _client
    if _client is None:
        _client = MongoClient(settings.mongodb_uri)
    return _client


def get_db() -> Database[dict[str, Any]]:
    global _db
    if _db is None:
        client = get_client()
        _db = client[settings.mongodb_db_name]
    return _db


def get_collection(name: str) -> Collection[dict[str, Any]]:
    return get_db()[name]


def init_db_indexes() -> None:
    """Create essential MongoDB indexes for multi-tenant isolation and fast querying."""
    try:
        db = get_db()
        db.users.create_index([("email", ASCENDING)], unique=True)
        db.cases.create_index([("id", ASCENDING)], unique=True)
        db.cases.create_index([("user_id", ASCENDING)])
        db.documents.create_index([("case_id", ASCENDING)])
        db.claims.create_index([("case_id", ASCENDING)])
        db.claims.create_index([("id", ASCENDING)])
        db.evidence.create_index([("case_id", ASCENDING)])
        db.relationships.create_index([("case_id", ASCENDING)])
        db.conflicts.create_index([("case_id", ASCENDING)])
        db.authorities.create_index([("id", ASCENDING)])
        db.reviews.create_index([("case_id", ASCENDING)])
        db.reviews.create_index([("finding_type", ASCENDING), ("finding_id", ASCENDING)])
        db.citations.create_index([("case_id", ASCENDING)])
        db.citations.create_index([("case_id", ASCENDING), ("claim_id", ASCENDING)])
        db.counter_arguments.create_index([("case_id", ASCENDING)])
        db.risk_items.create_index([("case_id", ASCENDING)])
        db.analysis_runs.create_index([("case_id", ASCENDING)])
        db.audit_events.create_index([("case_id", ASCENDING)])
        log.info("MongoDB indexes initialized successfully.")
    except Exception as e:
        log.warning("Could not initialize MongoDB indexes: %s", e)


def close_db_connection() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None
