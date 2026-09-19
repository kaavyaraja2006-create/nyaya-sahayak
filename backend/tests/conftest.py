"""Test configuration: environment, import path, and the in-memory database."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TMP = tempfile.mkdtemp(prefix="nyaya-test-")
os.environ.setdefault("DATA_DIR", f"{TMP}/data")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DB_NAME", "nyayasahayak_test")
os.environ.setdefault("AUTHORITY_CORPUS_DIR", f"{TMP}/authorities")
# No API key: nothing in the suite may depend on a real provider.
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("AI_API_KEY", None)

from tests.fake_mongo import install  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    """A clean in-memory database for every test."""
    yield install()
