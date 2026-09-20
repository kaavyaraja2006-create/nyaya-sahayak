"""RiskReviewReportAgent.

Aggregates the findings the earlier stages produced into a risk and
human-review view. It performs no new legal research, introduces no new
facts, and reaches no conclusion: every item it emits is a restatement of an
upstream finding, levelled by the deterministic rules in `risk_rules.py`.

The pipeline is:

    collect candidates   one per upstream finding that shows a problem, each
                         carrying its finding id, claim id and sources
    level them           BASE table, then R1 / R2 / R3 escalation — no model
    build risk items     ids assigned in collection order
    validate             drop anything that does not trace back; record why
    queue reviews        grouped by claim and review type; status is fixed at
                         REQUIRES_HUMAN_REVIEW and the agent cannot change it
    summarise            deterministic headline; optional model narrative that
                         is discarded whole if it adds anything

The model, if one is supplied at all, is asked for prose and nothing else. No
risk level, no review item and no finding can originate from it.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol

from pydantic import ValidationError

from ..authority_citation.schemas import AuthorityCitationResult, CitationRelationship
from ..case_understanding.schemas import CaseUnderstandingResult, VerificationStatus
from ..counter_argument.schemas import CounterAnalysisStatus, CounterArgumentResult
from ..evidence_conflict.schemas import EvidenceConflictResult, GapType
from .prompts import RISK_REVIEW_REPORT_SYSTEM_PROMPT
from .risk_rules import (
    REVIEW_QUESTIONS,
    RiskCandidate,
    apply_combination_rules,
    assess,
    highest,
    requires_review,
    review_type_for,
)
from .schemas import (
    AuthorityStatus,
    Dashboard,
    FindingKind,
    IssueType,
    ReportSummary,
    ReviewItem,
    ReviewType,
    RiskItem,
    RiskLevel,
    RiskReviewReportInput,
    RiskReviewReportResult,
    SourceRef,
    StageStatus,
    ValidationFailure,
)
from .validation import (
    TraceIndex,
    build_narrative_corpus,
    check_narrative,
    find_findings_without_provenance,
    validate_risk_items,
)

log = logging.getLogger("nyayasahayak.agents.risk_review_report")

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)
_RAW_LOG_LIMIT = 2000

# Citation outcomes that mean the authority is actually being relied on.
_RELIANCE_RELATIONSHIPS = frozenset(
    {CitationRelationship.SUPPORTS, CitationRelationship.PARTIALLY_SUPPORTS}
)


class LLMProvider(Protocol):
    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        ...


@dataclass
class _Collector:
    """Accumulates candidates, refusing duplicates of the same issue."""

    candidates: list[RiskCandidate] = field(default_factory=list)
    _seen: set[tuple] = field(default_factory=set)

    def add(self, candidate: RiskCandidate, dedupe_extra: object = None) -> None:
        key = (
            candidate.issue_type,
            candidate.finding_id,
            candidate.claim_id,
            dedupe_extra,
        )
        if key in self._seen:
            return
        self._seen.add(key)
        self.candidates.append(candidate)


class RiskReviewReportAgent:
    """Usage:
        agent = RiskReviewReportAgent()                 # fully deterministic
        agent = RiskReviewReportAgent(llm=my_provider)  # adds a prose summary

        result = agent.run(RiskReviewReportInput(
            case_id="NS-2026-001",
            case_understanding=cu_result,
            evidence_conflict=ec_result,
            authority_citation=ac_result,
            counter_argument=ca_result,
            material_claim_ids=["C-1"],
            authority_statuses=[AuthorityStatusRecord(authority_id="A-1", status=...)],
        ))

    The `llm` argument is optional on purpose: the report must be identical
    with or without it apart from `summary.narrative`.
    """

    system_prompt: str = RISK_REVIEW_REPORT_SYSTEM_PROMPT

    def __init__(self, llm: Optional[LLMProvider] = None) -> None:
        self._llm = llm

    # -- public API -------------------------------------------------------

    def run(self, input_data: RiskReviewReportInput) -> RiskReviewReportResult:
        index = TraceIndex.build(
            case_understanding=input_data.case_understanding,
            evidence_conflict=input_data.evidence_conflict,
            authority_citation=input_data.authority_citation,
            counter_argument=input_data.counter_argument,
        )
        warnings: list[str] = []
        failures: list[ValidationFailure] = []
        degraded = False

        collector = _Collector()
        self._collect_case_understanding(collector, input_data)
        self._collect_evidence_conflict(collector, input_data)
        self._collect_authority_citation(collector, input_data)
        self._collect_counter_argument(collector, input_data)

        assessed = [(c, assess(c)) for c in collector.candidates]
        assessed = apply_combination_rules(assessed)

        risk_items: list[RiskItem] = []
        for position, (candidate, assessment) in enumerate(assessed, start=1):
            try:
                risk_items.append(RiskItem(
                    risk_id=f"RISK-{position:03d}",
                    risk_level=assessment.level,
                    issue_type=candidate.issue_type,
                    reason=candidate.reason,
                    finding_id=candidate.finding_id,
                    finding_kind=candidate.finding_kind,
                    claim_id=candidate.claim_id,
                    source_references=candidate.source_references,
                    rules_applied=assessment.rules_applied,
                    requires_review=requires_review(assessment.level, candidate.issue_type),
                ))
            except ValidationError as exc:  # pragma: no cover - candidates are built in-house
                log.error("RiskReviewReportAgent: could not construct a risk item: %s", exc)
                degraded = True
                failures.append(ValidationFailure(
                    kind="untraceable_risk_item",
                    detail="A risk item failed its structural checks and was not emitted.",
                    dropped_id=candidate.finding_id,
                ))

        risk_items, trace_failures = validate_risk_items(risk_items, index)
        failures.extend(trace_failures)
        failures.extend(find_findings_without_provenance(
            case_understanding=input_data.case_understanding,
            authority_citation=input_data.authority_citation,
        ))
        if trace_failures:
            degraded = True
            warnings.append(
                f"{len(trace_failures)} risk item(s) could not be traced back to a supplied "
                "finding and were removed from the report."
            )

        review_items = self._build_review_items(risk_items)
        dashboard = self._build_dashboard(input_data, risk_items, review_items, failures)
        summary, summary_failures, summary_warnings = self._build_summary(
            input_data, risk_items, review_items, index
        )
        failures.extend(summary_failures)
        warnings.extend(summary_warnings)
        warnings.extend(self._stage_warnings(input_data))

        return RiskReviewReportResult(
            case_id=input_data.case_id,
            risk_items=risk_items,
            review_items=review_items,
            dashboard=dashboard,
            summary=summary,
            validation_failures=failures,
            warnings=warnings,
            degraded=degraded,
        )

    # -- candidate collection ---------------------------------------------

    @staticmethod
    def _is_material(input_data: RiskReviewReportInput, claim_id: Optional[str]) -> bool:
        return bool(claim_id) and claim_id in set(input_data.material_claim_ids)

    def _collect_case_understanding(
        self, collector: _Collector, input_data: RiskReviewReportInput
    ) -> None:
        result: Optional[CaseUnderstandingResult] = input_data.case_understanding
        if not result:
            return

        for claim in result.claims:
            material = self._is_material(input_data, claim.claim_id)
            sources = [SourceRef.from_document(claim.source)]

            if claim.verification_status == VerificationStatus.VERIFIED:
                if not claim.source.document_id:
                    collector.add(RiskCandidate(
                        issue_type=IssueType.PROVENANCE_FAILURE,
                        reason=(
                            f"Claim {claim.claim_id} is recorded as verified but its source does "
                            "not name a document, so it cannot be traced back to case material."
                        ),
                        finding_id=claim.claim_id,
                        finding_kind=FindingKind.CLAIM,
                        claim_id=claim.claim_id,
                        source_references=sources,
                        is_material=material,
                    ))
                continue

            collector.add(RiskCandidate(
                issue_type=IssueType.UNVERIFIED_CLAIM,
                reason=(
                    f"Claim {claim.claim_id} was not verified against the source document by the "
                    "case-understanding stage, so its wording is not confirmed to match the "
                    "material it is attributed to."
                ),
                finding_id=claim.claim_id,
                finding_kind=FindingKind.CLAIM,
                claim_id=claim.claim_id,
                source_references=sources,
                is_material=material,
            ))

    def _collect_evidence_conflict(
        self, collector: _Collector, input_data: RiskReviewReportInput
    ) -> None:
        result: Optional[EvidenceConflictResult] = input_data.evidence_conflict
        if not result:
            return

        for conflict in result.conflicts:
            claim_id = conflict.side_a.claim_id or conflict.side_b.claim_id
            collector.add(RiskCandidate(
                issue_type=IssueType.EVIDENCE_CONFLICT,
                reason=(
                    f"The evidence stage detected a conflict ({conflict.conflict_type.value}) "
                    f"between two sources in conflict {conflict.conflict_id}. It was detected, "
                    "not resolved."
                ),
                finding_id=conflict.conflict_id,
                finding_kind=FindingKind.CONFLICT,
                claim_id=claim_id,
                source_references=[
                    SourceRef.from_document(conflict.side_a.source),
                    SourceRef.from_document(conflict.side_b.source),
                ],
                is_material=self._is_material(input_data, claim_id),
            ))

        for gap in result.support_gaps:
            material = self._is_material(input_data, gap.claim_id)
            if gap.gap_type == GapType.MISSING_EVIDENCE:
                # An important claim that nothing addresses is an unsupported
                # important claim; the same gap on a peripheral claim is
                # recorded as missing evidence.
                issue = IssueType.UNSUPPORTED_CLAIM if material else IssueType.MISSING_EVIDENCE
                reason = (
                    f"No evidence supplied to this case addresses claim {gap.claim_id} "
                    f"(support gap {gap.gap_id})."
                )
            else:
                issue = IssueType.PARTIALLY_SUPPORTED_CLAIM
                reason = (
                    f"The evidence addressing claim {gap.claim_id} does not establish it "
                    f"(support gap {gap.gap_id}, {len(gap.related_evidence_ids)} related item(s))."
                )
            collector.add(RiskCandidate(
                issue_type=issue,
                reason=reason,
                finding_id=gap.gap_id,
                finding_kind=FindingKind.SUPPORT_GAP,
                claim_id=gap.claim_id,
                source_references=[SourceRef.from_document(gap.claim_source)],
                is_material=material,
            ))

    def _collect_authority_citation(
        self, collector: _Collector, input_data: RiskReviewReportInput
    ) -> None:
        result: Optional[AuthorityCitationResult] = input_data.authority_citation
        if not result:
            return

        statuses = {r.authority_id: r for r in input_data.authority_statuses}

        # Which authorities a claim actually leans on, for the R3 sole-support rule.
        relied_on: dict[str, set[str]] = {}
        for finding in result.findings:
            if finding.relationship in _RELIANCE_RELATIONSHIPS and finding.authority_id:
                relied_on.setdefault(finding.claim_id, set()).add(finding.authority_id)

        for finding in result.findings:
            material = self._is_material(input_data, finding.claim_id)
            sources = [SourceRef.from_authority(s) for s in finding.sources]
            rel = finding.relationship

            issue: Optional[IssueType] = None
            reason = ""
            if rel in (CitationRelationship.CONTRADICTS, CitationRelationship.DOES_NOT_SUPPORT):
                issue = IssueType.CITATION_MISMATCH
                reason = (
                    f"Citation finding {finding.finding_id} records {rel.value} between the cited "
                    f"authority and claim {finding.claim_id}: the authority text relied on does "
                    "not carry the proposition as stated."
                )
            elif rel == CitationRelationship.PARTIALLY_SUPPORTS:
                issue = IssueType.PARTIAL_CITATION_SUPPORT
                reason = (
                    f"Citation finding {finding.finding_id} records that the authority supports "
                    f"only part of claim {finding.claim_id}."
                )
            elif rel == CitationRelationship.SOURCE_NOT_FOUND:
                issue = IssueType.AUTHORITY_NOT_FOUND
                reason = (
                    f"The authority cited for claim {finding.claim_id} could not be found among "
                    f"the sources available to this run (finding {finding.finding_id}), so the "
                    "citation is unverified."
                )
            elif rel == CitationRelationship.REQUIRES_HUMAN_REVIEW:
                if finding.uncited:
                    issue = IssueType.UNCITED_LEGAL_PROPOSITION
                    reason = (
                        f"Claim {finding.claim_id} is a legal proposition with no citation in the "
                        f"supplied material (finding {finding.finding_id})."
                    )
                else:
                    issue = IssueType.AMBIGUOUS_CITATION
                    reason = (
                        f"Citation finding {finding.finding_id} for claim {finding.claim_id} could "
                        "not be resolved automatically and was referred for human review."
                    )
            elif rel == CitationRelationship.SUPPORTS:
                # Clean support, but check the provenance is identifiable.
                thin = [
                    s for s in finding.sources if not (s.title or s.citation)
                ]
                if thin:
                    issue = IssueType.METADATA_ISSUE
                    reason = (
                        f"The authority relied on in finding {finding.finding_id} carries no title "
                        "or citation metadata, so a reader cannot identify it from the record alone."
                    )

            if issue is not None:
                collector.add(RiskCandidate(
                    issue_type=issue,
                    reason=reason,
                    finding_id=finding.finding_id,
                    finding_kind=FindingKind.CITATION_FINDING,
                    claim_id=finding.claim_id,
                    source_references=sources,
                    is_material=material,
                ))

            # Authority currency, from the supplied record only.
            record = statuses.get(finding.authority_id) if finding.authority_id else None
            if record is None:
                continue
            claim_authorities = relied_on.get(finding.claim_id, set())
            sole = claim_authorities == {finding.authority_id}

            if record.status == AuthorityStatus.POTENTIALLY_OUTDATED:
                collector.add(RiskCandidate(
                    issue_type=IssueType.POTENTIALLY_OUTDATED_AUTHORITY,
                    reason=(
                        f"The source record for authority {record.authority_id}, relied on in "
                        f"finding {finding.finding_id}, marks it as potentially outdated. Its "
                        "current status has not been confirmed by this pipeline."
                    ),
                    finding_id=finding.finding_id,
                    finding_kind=FindingKind.CITATION_FINDING,
                    claim_id=finding.claim_id,
                    source_references=sources,
                    is_material=material,
                    is_sole_supporting_authority=sole,
                ), dedupe_extra=record.authority_id)
            elif record.status == AuthorityStatus.UNKNOWN and rel in _RELIANCE_RELATIONSHIPS:
                collector.add(RiskCandidate(
                    issue_type=IssueType.AUTHORITY_STATUS_UNCERTAIN,
                    reason=(
                        f"Authority {record.authority_id} is relied on in finding "
                        f"{finding.finding_id}, but no record of its current status was supplied."
                    ),
                    finding_id=finding.finding_id,
                    finding_kind=FindingKind.CITATION_FINDING,
                    claim_id=finding.claim_id,
                    source_references=sources,
                    is_material=material,
                ), dedupe_extra=record.authority_id)

        # Uncited claims the citation stage judged not to need authority.
        claims_by_id = {}
        if input_data.case_understanding:
            claims_by_id = {c.claim_id: c for c in input_data.case_understanding.claims}
        for claim_id in result.skipped_claim_ids:
            claim = claims_by_id.get(claim_id)
            if claim is None:
                continue  # nothing to trace it to; it is not reported
            collector.add(RiskCandidate(
                issue_type=IssueType.NON_CRITICAL_CITATION_OMISSION,
                reason=(
                    f"Claim {claim_id} carries no citation and was treated as not requiring legal "
                    "authority. Recorded for completeness."
                ),
                finding_id=claim_id,
                finding_kind=FindingKind.CLAIM,
                claim_id=claim_id,
                source_references=[SourceRef.from_document(claim.source)],
                is_material=self._is_material(input_data, claim_id),
            ))

    def _collect_counter_argument(
        self, collector: _Collector, input_data: RiskReviewReportInput
    ) -> None:
        result: Optional[CounterArgumentResult] = input_data.counter_argument
        if not result:
            return

        statuses = {r.authority_id: r for r in input_data.authority_statuses}

        for finding in result.findings:
            material = self._is_material(input_data, finding.claim_id)
            claim_source = SourceRef.from_document(finding.claim_source)

            if finding.status == CounterAnalysisStatus.NOT_ASSESSED:
                collector.add(RiskCandidate(
                    issue_type=IssueType.COUNTER_ANALYSIS_INCOMPLETE,
                    reason=(
                        f"The counter-analysis for claim {finding.claim_id} did not run "
                        f"(finding {finding.finding_id}). No search for contrary material was "
                        "completed, which is not the same as finding none."
                    ),
                    finding_id=finding.finding_id,
                    finding_kind=FindingKind.COUNTER_ANALYSIS,
                    claim_id=finding.claim_id,
                    source_references=[claim_source],
                    is_material=material,
                ))

            if finding.contrary_evidence or finding.counterpoints:
                refs = [claim_source]
                refs.extend(SourceRef.from_document(e.source) for e in finding.contrary_evidence)
                collector.add(RiskCandidate(
                    issue_type=IssueType.UNRESOLVED_COUNTERARGUMENT,
                    reason=(
                        f"The counter-analysis for claim {finding.claim_id} found "
                        f"{len(finding.contrary_evidence)} contrary evidence item(s) and "
                        f"{len(finding.counterpoints)} source-grounded counterpoint(s) "
                        f"(finding {finding.finding_id}), none of which has been addressed."
                    ),
                    finding_id=finding.finding_id,
                    finding_kind=FindingKind.COUNTER_ANALYSIS,
                    claim_id=finding.claim_id,
                    source_references=refs,
                    is_material=material,
                ))

            if finding.contrary_authority:
                collector.add(RiskCandidate(
                    issue_type=IssueType.CONTRARY_AUTHORITY,
                    reason=(
                        f"The counter-analysis for claim {finding.claim_id} found "
                        f"{len(finding.contrary_authority)} authority passage(s) that may cut "
                        f"against the proposition (finding {finding.finding_id})."
                    ),
                    finding_id=finding.finding_id,
                    finding_kind=FindingKind.COUNTER_ANALYSIS,
                    claim_id=finding.claim_id,
                    source_references=[
                        SourceRef.from_authority(a.provenance) for a in finding.contrary_authority
                    ],
                    is_material=material,
                ))

            if finding.unresolved_questions:
                collector.add(RiskCandidate(
                    issue_type=IssueType.UNRESOLVED_QUESTION,
                    reason=(
                        f"The counter-analysis for claim {finding.claim_id} recorded "
                        f"{len(finding.unresolved_questions)} unresolved question(s) "
                        f"(finding {finding.finding_id})."
                    ),
                    finding_id=finding.finding_id,
                    finding_kind=FindingKind.COUNTER_ANALYSIS,
                    claim_id=finding.claim_id,
                    source_references=[claim_source],
                    is_material=material,
                ))

            # Currency of any authority this counter-analysis leans on.
            for auth in (*finding.supporting_authority, *finding.contrary_authority):
                record = statuses.get(auth.authority_id)
                if record is None or record.status != AuthorityStatus.POTENTIALLY_OUTDATED:
                    continue
                collector.add(RiskCandidate(
                    issue_type=IssueType.POTENTIALLY_OUTDATED_AUTHORITY,
                    reason=(
                        f"The source record for authority {record.authority_id}, used in the "
                        f"counter-analysis of claim {finding.claim_id} (finding "
                        f"{finding.finding_id}), marks it as potentially outdated."
                    ),
                    finding_id=finding.finding_id,
                    finding_kind=FindingKind.COUNTER_ANALYSIS,
                    claim_id=finding.claim_id,
                    source_references=[SourceRef.from_authority(auth.provenance)],
                    is_material=material,
                ), dedupe_extra=record.authority_id)

    # -- review queue ------------------------------------------------------

    @staticmethod
    def _build_review_items(risk_items: list[RiskItem]) -> list[ReviewItem]:
        """One review item per (claim, review type), aggregating the risks that
        raised it. Grouping keeps the queue readable; nothing is dropped,
        because every contributing risk id is listed."""
        grouped: dict[tuple[Optional[str], ReviewType], list[RiskItem]] = {}
        order: list[tuple[Optional[str], ReviewType]] = []

        for item in risk_items:
            if not item.requires_review:
                continue
            key = (item.claim_id, review_type_for(item.issue_type))
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(item)

        review_items: list[ReviewItem] = []
        for position, key in enumerate(order, start=1):
            claim_id, review_type = key
            members = grouped[key]
            level = highest([m.risk_level for m in members]) or RiskLevel.LOW
            issue_types = sorted({m.issue_type.value for m in members})
            source_refs = []
            for member in members:
                source_refs.extend(member.source_references)
            review_items.append(ReviewItem(
                review_id=f"REVIEW-{position:03d}",
                review_type=review_type,
                risk_level=level,
                question=REVIEW_QUESTIONS[review_type],
                reason=(
                    f"Raised by {len(members)} risk item(s) of type {', '.join(issue_types)}"
                    + (f" on claim {claim_id}." if claim_id else ".")
                ),
                risk_item_ids=[m.risk_id for m in members],
                finding_ids=list(dict.fromkeys(m.finding_id for m in members)),
                claim_id=claim_id,
                source_references=source_refs,
            ))
        return review_items

    # -- dashboard & summary ----------------------------------------------

    @staticmethod
    def _stages(input_data: RiskReviewReportInput) -> list[StageStatus]:
        def status(name: str, result) -> StageStatus:
            if result is None:
                return StageStatus(stage=name, present=False)
            rejected = 0
            for attribute in (
                "rejected_claims", "rejected_findings", "rejected_model_outputs",
                "rejected_material",
            ):
                rejected += len(getattr(result, attribute, []) or [])
            return StageStatus(
                stage=name,
                present=True,
                degraded=bool(getattr(result, "degraded", False)),
                warnings=len(getattr(result, "warnings", []) or []),
                rejected_items=rejected,
            )

        return [
            status("case_understanding", input_data.case_understanding),
            status("evidence_conflict", input_data.evidence_conflict),
            status("authority_citation", input_data.authority_citation),
            status("counter_argument", input_data.counter_argument),
        ]

    def _stage_warnings(self, input_data: RiskReviewReportInput) -> list[str]:
        warnings: list[str] = []
        for stage in self._stages(input_data):
            if not stage.present:
                warnings.append(
                    f"Stage {stage.stage!r} produced no result for this case. Its issues are "
                    "absent from this report, which is not the same as there being none."
                )
            elif stage.degraded:
                warnings.append(
                    f"Stage {stage.stage!r} reported degraded operation; its findings may be "
                    "incomplete."
                )
        return warnings

    def _build_dashboard(
        self,
        input_data: RiskReviewReportInput,
        risk_items: list[RiskItem],
        review_items: list[ReviewItem],
        failures: list[ValidationFailure],
    ) -> Dashboard:
        by_issue: dict[str, int] = {}
        for item in risk_items:
            by_issue[item.issue_type.value] = by_issue.get(item.issue_type.value, 0) + 1
        by_review: dict[str, int] = {}
        for item in review_items:
            by_review[item.review_type.value] = by_review.get(item.review_type.value, 0) + 1

        claims_assessed = 0
        if input_data.case_understanding:
            claims_assessed = len(input_data.case_understanding.claims)

        return Dashboard(
            case_id=input_data.case_id,
            total_risk_items=len(risk_items),
            high_count=sum(1 for i in risk_items if i.risk_level == RiskLevel.HIGH),
            medium_count=sum(1 for i in risk_items if i.risk_level == RiskLevel.MEDIUM),
            low_count=sum(1 for i in risk_items if i.risk_level == RiskLevel.LOW),
            risk_by_issue_type=by_issue,
            total_review_items=len(review_items),
            review_by_type=by_review,
            claims_assessed=claims_assessed,
            claims_with_risk=list(dict.fromkeys(
                i.claim_id for i in risk_items if i.claim_id
            )),
            provenance_failures=sum(
                1 for i in risk_items
                if i.issue_type in (IssueType.PROVENANCE_FAILURE, IssueType.UNVERIFIED_CLAIM)
            ) + sum(1 for f in failures if f.kind == "finding_without_provenance"),
            stages=self._stages(input_data),
        )

    def _build_summary(
        self,
        input_data: RiskReviewReportInput,
        risk_items: list[RiskItem],
        review_items: list[ReviewItem],
        index: TraceIndex,
    ) -> tuple[ReportSummary, list[ValidationFailure], list[str]]:
        levels = [i.risk_level for i in risk_items]
        top = highest(levels)
        headline = (
            f"{len(risk_items)} risk item(s) aggregated from verified findings: "
            f"{sum(1 for l in levels if l == RiskLevel.HIGH)} HIGH, "
            f"{sum(1 for l in levels if l == RiskLevel.MEDIUM)} MEDIUM, "
            f"{sum(1 for l in levels if l == RiskLevel.LOW)} LOW. "
            f"{len(review_items)} item(s) require human review."
        )
        summary = ReportSummary(
            case_id=input_data.case_id,
            headline=headline,
            highest_risk_level=top,
            top_risk_ids=[i.risk_id for i in risk_items if i.risk_level == RiskLevel.HIGH],
            total_risk_items=len(risk_items),
            total_review_items=len(review_items),
        )

        if self._llm is None:
            return summary, [], []

        narrative, failures, warnings = self._narrative(risk_items, review_items, headline, index)
        if narrative:
            summary = summary.model_copy(update={"narrative": narrative})
        return summary, failures, warnings

    def _narrative(
        self,
        risk_items: list[RiskItem],
        review_items: list[ReviewItem],
        headline: str,
        index: TraceIndex,
    ) -> tuple[Optional[str], list[ValidationFailure], list[str]]:
        prompt = self._build_user_prompt(risk_items, review_items, headline)
        try:
            raw_output = self._llm.generate(system_prompt=self.system_prompt, user_prompt=prompt)
        except Exception as exc:  # noqa: BLE001
            log.warning("RiskReviewReportAgent: narrative model call failed: %s", exc)
            return None, [], [
                f"The optional narrative summary could not be generated ({exc}). The report "
                "itself is unaffected."
            ]

        try:
            payload = self._parse_model_output(raw_output)
            narrative = payload.get("narrative")
            if not isinstance(narrative, str):
                raise ValueError("no narrative string was returned")
        except ValueError as exc:
            return None, [], [
                f"The optional narrative summary was unreadable ({exc}) and was discarded."
            ]

        corpus = build_narrative_corpus(
            risk_items,
            extra=[headline, *(r.question for r in review_items), *(r.reason for r in review_items)],
        )
        allowed_ids = index.all_known_ids()
        allowed_ids.update(i.risk_id for i in risk_items)
        allowed_ids.update(r.review_id for r in review_items)
        problems = check_narrative(narrative, corpus=corpus, allowed_ids=allowed_ids)
        if problems:
            return None, [ValidationFailure(
                kind="new_claim_in_summary" if "identifier" in " ".join(problems)
                else "unsafe_summary",
                detail=(
                    "The narrative summary was discarded because it went beyond the report: "
                    + "; ".join(problems) + "."
                ),
            )], [
                "The optional narrative summary introduced material that is not in the report "
                "and was discarded. The deterministic headline is unaffected."
            ]

        try:
            ReportSummary(case_id="probe", headline=headline, narrative=narrative.strip())
        except ValidationError:
            return None, [ValidationFailure(
                kind="unsafe_summary",
                detail="The narrative summary was discarded because it predicted an outcome.",
            )], ["The optional narrative summary was discarded as unsafe."]

        return narrative.strip(), [], []

    # -- prompt / parsing -------------------------------------------------

    @staticmethod
    def _build_user_prompt(
        risk_items: list[RiskItem], review_items: list[ReviewItem], headline: str
    ) -> str:
        lines = [
            "THE REPORT IS ALREADY COMPLETE. Summarise it; do not extend it.",
            "",
            f"HEADLINE: {headline}",
            "",
            "RISK ITEMS:",
        ]
        if not risk_items:
            lines.append("(none)")
        for item in risk_items:
            lines.append(
                f"- {item.risk_id} | {item.risk_level.value} | {item.issue_type.value} | "
                f"claim={item.claim_id or 'n/a'} | finding={item.finding_id} | {item.reason}"
            )
        lines.extend(["", "ITEMS QUEUED FOR HUMAN REVIEW:"])
        if not review_items:
            lines.append("(none)")
        for item in review_items:
            lines.append(
                f"- {item.review_id} | {item.risk_level.value} | {item.review_type.value} | "
                f"claim={item.claim_id or 'n/a'} | {item.reason}"
            )
        lines.extend([
            "",
            "Return the JSON object described in your instructions. Mention only the identifiers "
            "listed above, do not re-level anything, and do not resolve any review item.",
        ])
        return "\n".join(lines)

    @staticmethod
    def _parse_model_output(raw_output: str) -> dict:
        text = _CODE_FENCE_RE.sub("", raw_output or "").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(str(exc)) from exc
        if not isinstance(parsed, dict):
            raise ValueError("expected a JSON object")
        return parsed
