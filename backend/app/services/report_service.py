"""Human review and report generation using MongoDB repositories."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..models.case import Case, User
import uuid

from ..models.review import Review, FindingType


def uuid_or_new() -> str:
    return uuid.uuid4().hex
from ..models.audit import AuditEvent
from ..repositories import (
    case_repository,
    document_repository,
    claim_repository,
    evidence_repository,
    relationship_repository,
    conflict_repository,
    authority_repository,
    citation_repository,
    review_repository,
    audit_repository,
)
from . import case_service
from .case_service import NotFound

DECISION_TO_STATUS = {
    "accept": "ACCEPTED",
    "reject": "REJECTED",
    "needs_verification": "NEEDS_VERIFICATION",
    "modify": "EDITED",
    "ACCEPTED": "ACCEPTED",
    "REJECTED": "REJECTED",
    "NEEDS_VERIFICATION": "NEEDS_VERIFICATION",
    "EDITED": "EDITED",
}

STATUS_LABEL = {
    "open": "Open",
    "ACCEPTED": "Accepted",
    "REJECTED": "Rejected",
    "NEEDS_VERIFICATION": "Needs verification",
    "EDITED": "Edited",
}

DISCLAIMER = (
    "This report is an AI-assisted research and evidence-auditing output. It does not "
    "determine guilt, innocence, liability, witness credibility, admissibility, or judicial "
    "outcome. Human legal review remains required."
)


# ── review ────────────────────────────────────────────────────────────────────

def save_review(
    case: Case,
    user: User,
    finding_id: str,
    decision: str,
    comment: str,
    finding_type: str = "CLAIM",
) -> tuple[Review, AuditEvent]:
    if decision not in DECISION_TO_STATUS and decision.lower() not in DECISION_TO_STATUS:
        raise ValueError(f"Unsupported review decision '{decision}'.")

    new_status = DECISION_TO_STATUS.get(decision, DECISION_TO_STATUS.get(decision.lower(), "NEEDS_VERIFICATION"))
    existing_review = review_repository.get_by_finding(case.id, finding_type, finding_id)
    previous_status = existing_review.new_status if existing_review else "NEEDS_REVIEW"

    # A review item raised by the pipeline already carries the question, the
    # risk level and the finding ids it was raised from. A human decision
    # records who decided what — it must not erase why the item was raised.
    review = Review(
        id=existing_review.id if existing_review else uuid_or_new(),
        review_id=existing_review.review_id if existing_review else "",
        case_id=case.id,
        finding_type=finding_type,
        finding_id=finding_id,
        reviewer_id=user.id,
        reviewer_name=user.full_name,
        decision=new_status,
        comment=comment.strip() if comment else None,
        previous_status=previous_status,
        new_status=new_status,
        run_id=existing_review.run_id if existing_review else None,
        review_type=existing_review.review_type if existing_review else None,
        risk_level=existing_review.risk_level if existing_review else None,
        question=existing_review.question if existing_review else None,
        reason=existing_review.reason if existing_review else None,
        risk_item_ids=list(existing_review.risk_item_ids) if existing_review else [],
        finding_ids=list(existing_review.finding_ids) if existing_review else [finding_id],
        source=existing_review.source if existing_review else "human",
    )
    review_repository.create_or_update(review)

    event = case_service.log_event(
        case.id,
        action="Reviewer recorded finding decision",
        object_type="review",
        object_id=finding_id,
        actor=user.full_name,
        actor_type="reviewer",
        previous_state=previous_status,
        new_state=new_status,
        details=comment.strip() if comment else None,
    )

    return review, event


def list_reviews(case_row_id: str) -> list[Review]:
    return review_repository.list_by_case(case_row_id)
