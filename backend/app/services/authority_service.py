"""Authority service using AuthorityRepository."""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from pathlib import Path

from ..models.authority import Authority
from ..repositories.authority_repository import authority_repository, AuthorityRepository

log = logging.getLogger("nyayasahayak.authorities")

STOPWORDS = set(
    """a an the and or of to in on at by for with from as is are was were be been being that this
    it its his her their our your not no if then than so such which who what when where how any
    all some each other into over under about after before during between within without upon""".split()
)


def terms(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower()) if w not in STOPWORDS]


class AuthorityService:
    """Interface. Scores are retrieval/ranking signals — never legal correctness."""

    def size(self) -> int:
        raise NotImplementedError

    def search(self, query: str, limit: int = 5) -> list[dict]:
        raise NotImplementedError

    def excerpt(self, authority_id: str) -> dict | None:
        raise NotImplementedError


class CorpusAuthorityService(AuthorityService):
    def __init__(self, repo: AuthorityRepository = authority_repository) -> None:
        self.repo = repo
        self._rows: list[Authority] = self.repo.list_all(limit=1000)
        self._index: list[tuple[Authority, Counter, int]] = [
            (row, Counter(terms(f"{row.title} {row.citation or ''} {row.passage}")), 0)
            for row in self._rows
        ]
        self._df: Counter = Counter()
        for _row, counts, _n in self._index:
            self._df.update(counts.keys())
        self._n = max(len(self._index), 1)

    def size(self) -> int:
        return len(self._rows)

    def search(self, query: str, limit: int = 5) -> list[dict]:
        q = terms(query)
        if not q or not self._index:
            return []
        q_counts = Counter(q)
        results = []
        for row, counts, _ in self._index:
            total = sum(counts.values()) or 1
            score = 0.0
            for term, qn in q_counts.items():
                if term not in counts:
                    continue
                tf = counts[term] / total
                idf = math.log((1 + self._n) / (1 + self._df[term])) + 1.0
                score += tf * idf * math.log(1 + qn)
            if score <= 0:
                continue
            results.append(
                {
                    "authority_id": row.authority_id,
                    "title": row.title,
                    "citation": row.citation or "",
                    "court": row.court or "",
                    "year": row.year or 0,
                    "paragraph": row.paragraph or 0,
                    "passage": row.passage,
                    "score": round(min(score * 6, 1.0), 3),
                }
            )
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def excerpt(self, authority_id: str) -> dict | None:
        row = self.repo.get_by_id(authority_id)
        if row is None:
            return None
        return {
            "authority_id": row.authority_id,
            "citation": row.citation or "",
            "title": row.title,
            "excerpt": row.passage,
            "court": row.court or "",
            "year": row.year or 0,
            "paragraph": row.paragraph or 0,
            "source": "authority_corpus",
        }


def load_corpus(corpus_dir: Path, repo: AuthorityRepository = authority_repository) -> int:
    """Load/refresh authorities from disk into MongoDB repository."""
    if not corpus_dir.exists():
        return 0
    loaded = 0
    for path in sorted(corpus_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping authority file %s: %s", path.name, exc)
            continue
        if not isinstance(payload, list):
            log.warning("Skipping authority file %s: expected a JSON array.", path.name)
            continue
        for record in payload:
            if not isinstance(record, dict):
                continue
            authority_id = str(record.get("authority_id") or "").strip()
            title = str(record.get("title") or "").strip()
            passage = str(record.get("passage") or "").strip()
            if not (authority_id and title and passage):
                continue
            existing = repo.get_by_id(authority_id)
            auth = existing or Authority(authority_id=authority_id)
            auth.title = title
            auth.passage = passage
            auth.label = str(record.get("label") or title)[:120]
            auth.citation = record.get("citation")
            auth.court = record.get("court")
            auth.jurisdiction = record.get("jurisdiction")
            auth.source_type = record.get("source_type")
            auth.source_file = record.get("source_file") or path.name
            auth.corpus = record.get("corpus") or path.stem
            try:
                auth.year = int(record.get("year")) if record.get("year") else None
                auth.paragraph = int(record.get("paragraph")) if record.get("paragraph") else None
            except (TypeError, ValueError):
                auth.year, auth.paragraph = None, None
            if existing:
                repo.update_one({"id": auth.id}, auth.to_dict())
            else:
                repo.create(auth)
            loaded += 1
    log.info("Authority corpus loaded: %s record(s) from %s", loaded, corpus_dir)
    return loaded
