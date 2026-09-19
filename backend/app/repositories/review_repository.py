"""Review MongoDB repository using finding_type + finding_id."""
from __future__ import annotations

from typing import Any
from ..models.review import CounterArgument, Review
from .base_repository import BaseRepository


class ReviewRepository(BaseRepository[Review]):
    def __init__(self) -> None:
        super().__init__("reviews")

    def get_by_finding(
        self, case_id: str, finding_type: str, finding_id: str
    ) -> Review | None:
        raw = self.find_one({
            "case_id": case_id,
            "finding_type": finding_type,
            "finding_id": finding_id,
        })
        return Review.from_dict(raw) if raw else None

    def list_by_case(self, case_id: str) -> list[Review]:
        raws = self.find_many({"case_id": case_id}, sort=[("created_at", -1)])
        return [Review.from_dict(r) for r in raws]

    def create_or_update(self, review: Review) -> Review:
        existing = self.find_one({
            "case_id": review.case_id,
            "finding_type": review.finding_type,
            "finding_id": review.finding_id,
        })
        if existing:
            self.update_one({"id": existing["id"]}, review.to_dict())
        else:
            self.insert(review.to_dict())
        return review


class CounterArgumentRepository(BaseRepository[CounterArgument]):
    def __init__(self) -> None:
        super().__init__("counter_arguments")

    def list_by_case(self, case_id: str) -> list[CounterArgument]:
        raws = self.find_many({"case_id": case_id}, sort=[("created_at", 1)])
        return [CounterArgument.from_dict(r) for r in raws]

    def list_by_claim(self, case_id: str, claim_id: str) -> list[CounterArgument]:
        raws = self.find_many({"case_id": case_id, "claim_id": claim_id})
        return [CounterArgument.from_dict(r) for r in raws]

    def create(self, item: CounterArgument) -> CounterArgument:
        self.insert(item.to_dict())
        return item


review_repository = ReviewRepository()
counter_argument_repository = CounterArgumentRepository()
