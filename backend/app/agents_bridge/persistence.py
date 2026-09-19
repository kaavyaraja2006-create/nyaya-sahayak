"""Validated agent output -> backend domain objects -> repositories.

Every object written here came out of a Pydantic model the agents validated.
Nothing is re-interpreted on the way in: an agent's relationship, status or
risk level is stored as the agent set it, and where the backend has no field
for something the payload is kept whole in a *_json column rather than being
dropped or summarised.
"""
from __future__ import annotations

import logging
from typing import Any

from agents.graph import NyayaSahayakState

from ..models.authority import CitationFinding, SourceProvenance
from ..models.claim import Claim, SourceReference
from ..models.conflict import Conflict
from ..models.relationship import Relationship
from ..models.review import CounterArgument, FindingType, Review
from ..models.risk import RiskItem
from ..repositories import (
    citation_repository,
    claim_repository,
    conflict_repository,
    counter_argument_repository,
    relationship_repository,
    review_repository,
    risk_item_repository,
)

log = logging.getLogger("nyayasahayak.agents_bridge.persistence")

# Risk levels that map onto the backend's coarse priority field.
_PRIORITY = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}


def _dump(model: Any) -> Any:
    """JSON-safe dict for a Pydantic model (enums become their values)."""
    if model is None:
        return None
    return model.model_dump(mode="json")


def _source_reference(agent_source: Any) -> SourceReference:
    if agent_source is None:
        return SourceReference()
    return SourceReference(
        source_document_id=getattr(agent_source, "document_id", None),
        page=getattr(agent_source, "page", None),
        paragraph=getattr(agent_source, "paragraph", None),
        quote=getattr(agent_source, "quote", None),
        timestamp=getattr(agent_source, "transcript_location", None),
    )


# ── stage 1: claims ───────────────────────────────────────────────────────────

def _persist_claims(state: NyayaSahayakState, case_row_id: str, run_id: str) -> int:
    result = state.case_understanding
    if result is None:
        return 0
    for claim in result.claims:
        claim_repository.create(
            Claim(
                claim_id=claim.claim_id,
                case_id=case_row_id,
                claim_text=claim.claim_text,
                claim_type=claim.claim_type.value,
                speaker=claim.speaker,
                source_reference=_source_reference(claim.source),
                # The agent's own provenance check sets this; it is never the
                # model's self-report, so it is stored unchanged.
                status=claim.verification_status.value,
                origin_note=claim.verification_notes,
                signals_json={
                    "dates": list(claim.dates),
                    "entities": list(claim.entities),
                    "run_id": run_id,
                },
            )
        )
    return len(result.claims)


# ── stage 2: relationships, conflicts, support gaps ───────────────────────────

def _persist_evidence_conflict(state: NyayaSahayakState, case_row_id: str, run_id: str) -> dict:
    result = state.evidence_conflict
    if result is None:
        return {"relationships": 0, "conflicts": 0, "support_gaps": 0}

    for relationship in result.relationships:
        relationship_repository.create(
            Relationship(
                relationship_id=relationship.relationship_id,
                case_id=case_row_id,
                claim_id=relationship.claim_id,
                evidence_id=relationship.evidence_id,
                relationship=relationship.relationship_type.value,
                reason=relationship.reasoning,
            )
        )

    for conflict in result.conflicts:
        conflict_repository.create(
            Conflict(
                finding_id=conflict.conflict_id,
                case_id=case_row_id,
                kind="conflict",
                category=conflict.conflict_type.value,
                group_name="evidence",
                priority="high",
                claim_id=conflict.side_a.claim_id or conflict.side_b.claim_id,
                title=conflict.description,
                reason=conflict.description,
                conflict_type=conflict.conflict_type.value,
                comparison_json={
                    "side_a": _dump(conflict.side_a),
                    "side_b": _dump(conflict.side_b),
                    "result": conflict.result,
                    "run_id": run_id,
                },
                evidence_ids=[
                    side.evidence_id
                    for side in (conflict.side_a, conflict.side_b)
                    if side.evidence_id
                ],
                status="open",
                requires_human_review=True,
            )
        )

    for gap in result.support_gaps:
        conflict_repository.create(
            Conflict(
                finding_id=gap.gap_id,
                case_id=case_row_id,
                kind="support_gap",
                category=gap.gap_type.value,
                group_name="evidence",
                priority="medium",
                claim_id=gap.claim_id,
                title=gap.note,
                reason=gap.note,
                comparison_json={
                    "claim_source": _dump(gap.claim_source),
                    "result": gap.result,
                    "run_id": run_id,
                },
                evidence_ids=list(gap.related_evidence_ids),
                status="open",
                requires_human_review=True,
            )
        )

    return {
        "relationships": len(result.relationships),
        "conflicts": len(result.conflicts),
        "support_gaps": len(result.support_gaps),
    }


# ── stage 3: citation findings ────────────────────────────────────────────────

def _persist_citations(state: NyayaSahayakState, case_row_id: str, run_id: str) -> int:
    result = state.authority_citation
    if result is None:
        return 0
    for finding in result.findings:
        citation_repository.create(
            CitationFinding(
                finding_id=finding.finding_id,
                case_id=case_row_id,
                run_id=run_id,
                claim_id=finding.claim_id,
                citation_text=finding.citation_text,
                citation_type=finding.citation_type.value,
                authority_id=finding.authority_id,
                # The six-value vocabulary is persisted verbatim: mapping it to
                # a generic relevance scale would destroy the verification
                # meaning the agent exists to produce.
                relationship=finding.relationship.value,
                explanation=finding.explanation,
                sources=[
                    SourceProvenance(
                        source_id=source.source_id,
                        source_type=source.source_type.value,
                        title=source.title,
                        citation=source.citation,
                        exact_text=source.exact_text,
                        paragraph=source.paragraph,
                        section=source.section,
                        url=source.url,
                    )
                    for source in finding.sources
                ],
                requires_human_review=finding.requires_human_review,
                uncited=finding.uncited,
            )
        )
    return len(result.findings)


# ── stage 4: counter-analysis ─────────────────────────────────────────────────

def _persist_counter_arguments(state: NyayaSahayakState, case_row_id: str, run_id: str) -> int:
    result = state.counter_argument
    if result is None:
        return 0
    for finding in result.findings:
        counter_argument_repository.create(
            CounterArgument(
                finding_id=finding.finding_id,
                case_id=case_row_id,
                run_id=run_id,
                claim_id=finding.claim_id,
                claim_text=finding.claim_text,
                status=finding.status.value,
                analysis_note=finding.analysis_note,
                argument_text="\n".join(cp.statement for cp in finding.counterpoints),
                claim_source_json=_dump(finding.claim_source),
                supporting_evidence_ids=[e.evidence_id for e in finding.supporting_evidence],
                contrary_evidence_ids=[e.evidence_id for e in finding.contrary_evidence],
                supporting_authority_ids=[a.authority_id for a in finding.supporting_authority],
                contrary_authority_ids=[a.authority_id for a in finding.contrary_authority],
                counterpoints_json=[_dump(cp) for cp in finding.counterpoints],
                unresolved_questions_json=[_dump(q) for q in finding.unresolved_questions],
                requires_human_review=finding.requires_human_review,
            )
        )
    return len(result.findings)


# ── stage 5: risk items, review items, report summary ─────────────────────────

def _finding_type_for(kind: str) -> str:
    return kind if kind in {member.value for member in FindingType} else FindingType.CLAIM.value


def _persist_risk_review(
    state: NyayaSahayakState, case_row_id: str, run_id: str, actor: str
) -> dict:
    result = state.risk_review_report
    if result is None:
        return {"risk_items": 0, "review_items": 0, "summary": None, "dashboard": None}

    kind_by_finding: dict[str, str] = {}
    for risk in result.risk_items:
        kind_by_finding[risk.finding_id] = risk.finding_kind.value
        risk_item_repository.create(
            RiskItem(
                risk_id=risk.risk_id,
                case_id=case_row_id,
                run_id=run_id,
                risk_level=risk.risk_level.value,
                issue_type=risk.issue_type.value,
                reason=risk.reason,
                finding_id=risk.finding_id,
                finding_kind=risk.finding_kind.value,
                claim_id=risk.claim_id,
                source_references_json=[_dump(ref) for ref in risk.source_references],
                rules_applied=list(risk.rules_applied),
                requires_review=risk.requires_review,
            )
        )

    for item in result.review_items:
        primary_finding = item.finding_ids[0] if item.finding_ids else (item.claim_id or item.review_id)
        review_repository.create_or_update(
            Review(
                review_id=item.review_id,
                case_id=case_row_id,
                run_id=run_id,
                finding_type=_finding_type_for(kind_by_finding.get(primary_finding, "")),
                finding_id=primary_finding,
                reviewer_id="",
                reviewer_name="",
                # Raised by the pipeline, awaiting a human. The agent's own
                # status literal is REQUIRES_HUMAN_REVIEW; nothing here can
                # mark a finding as cleared.
                decision="NEEDS_REVIEW",
                new_status=item.status,
                review_type=item.review_type.value,
                risk_level=item.risk_level.value,
                question=item.question,
                reason=item.reason,
                risk_item_ids=list(item.risk_item_ids),
                finding_ids=list(item.finding_ids),
                source="agent",
                comment=None,
            )
        )

    return {
        "risk_items": len(result.risk_items),
        "review_items": len(result.review_items),
        "summary": _dump(result.summary),
        "dashboard": _dump(result.dashboard),
        "validation_failures": [_dump(f) for f in result.validation_failures],
    }


# ── entry point ───────────────────────────────────────────────────────────────

def persist_pipeline_output(
    state: NyayaSahayakState, *, case_row_id: str, run_id: str, actor: str = "System"
) -> dict:
    """Write one completed pipeline run to MongoDB and return a run summary.

    The summary is what the AnalysisRun stores; it records which stages ran,
    which were skipped or failed, and every warning the agents raised, so a
    degraded run can never be read as a clean one.
    """
    counts = {"claims": _persist_claims(state, case_row_id, run_id)}
    counts.update(_persist_evidence_conflict(state, case_row_id, run_id))
    counts["citations"] = _persist_citations(state, case_row_id, run_id)
    counts["counter_arguments"] = _persist_counter_arguments(state, case_row_id, run_id)

    risk_review = _persist_risk_review(state, case_row_id, run_id, actor)
    counts["risk_items"] = risk_review["risk_items"]
    counts["review_items"] = risk_review["review_items"]

    warnings: list[str] = []
    degraded = False
    for stage_name in (
        "case_understanding",
        "evidence_conflict",
        "authority_citation",
        "counter_argument",
        "risk_review_report",
    ):
        stage_result = getattr(state, stage_name, None)
        if stage_result is None:
            continue
        warnings.extend(f"{stage_name}: {w}" for w in getattr(stage_result, "warnings", []))
        degraded = degraded or bool(getattr(stage_result, "degraded", False))

    return {
        "counts": counts,
        "stages": [
            {"stage": record.stage.value, "outcome": record.outcome.value, "detail": record.detail}
            for record in state.stage_log
        ],
        "errors": list(state.errors),
        "warnings": warnings,
        "degraded": degraded or bool(state.errors),
        "summary": risk_review["summary"],
        "dashboard": risk_review["dashboard"],
        "validation_failures": risk_review.get("validation_failures") or [],
    }
