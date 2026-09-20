"""Traceability and anti-fabrication checks for the RiskReviewReportAgent.

Two jobs:

1. `TraceIndex` records every id that exists in the input — findings, claims,
   evidence, documents, authorities. Anything the report emits must resolve
   against it. That is what makes `Risk -> Finding -> Claim -> Source` a
   guarantee rather than a convention.

2. The `validate_*` functions are the final gate before a report is returned.
   They re-walk the already-constructed items and drop any that break an
   invariant, recording a `ValidationFailure` for each. Reaching this gate at
   all should be impossible — the agent only builds items from findings it
   just read — so a failure here means a bug, and the report says so instead
   of hiding it.

The narrative check is the model-facing one. It is a heuristic (defence in
depth); the hard guarantee is structural: prose can never add a risk item, a
review item or a finding, because the model is not asked for any of those and
there is no code path that would accept them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..authority_citation.schemas import AuthorityCitationResult
from ..authority_citation.validation import find_ungrounded_references
from ..case_understanding.schemas import CaseUnderstandingResult, VerificationStatus
from ..counter_argument.schemas import CounterArgumentResult, OUTCOME_LANGUAGE
from ..evidence_conflict.schemas import EvidenceConflictResult
from .schemas import FindingKind, RiskItem, SourceRef, ValidationFailure

# Anything shaped like an identifier: "C-1", "AUTH-DEVICE", "RISK-004".
_ID_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9]{0,7}-[A-Za-z0-9][A-Za-z0-9_-]*\b")


# --------------------------------------------------------------------------
# The trace index
# --------------------------------------------------------------------------


@dataclass
class TraceIndex:
    """Every id the report is allowed to mention, grouped by what it is."""

    finding_ids: dict[str, FindingKind] = field(default_factory=dict)
    claim_ids: set[str] = field(default_factory=set)
    evidence_ids: set[str] = field(default_factory=set)
    source_ids: set[str] = field(default_factory=set)  # document_id and authority_id values

    def add_finding(self, finding_id: str, kind: FindingKind) -> None:
        self.finding_ids[finding_id] = kind

    def knows_finding(self, finding_id: str, kind: Optional[FindingKind] = None) -> bool:
        known = self.finding_ids.get(finding_id)
        if known is None:
            return False
        return kind is None or known == kind

    def all_known_ids(self) -> set[str]:
        return set(self.finding_ids) | self.claim_ids | self.evidence_ids | self.source_ids

    @classmethod
    def build(
        cls,
        *,
        case_understanding: Optional[CaseUnderstandingResult],
        evidence_conflict: Optional[EvidenceConflictResult],
        authority_citation: Optional[AuthorityCitationResult],
        counter_argument: Optional[CounterArgumentResult],
    ) -> "TraceIndex":
        index = cls()

        if case_understanding:
            for claim in case_understanding.claims:
                index.claim_ids.add(claim.claim_id)
                # A claim is the traceable record behind claim-level issues.
                index.add_finding(claim.claim_id, FindingKind.CLAIM)
                if claim.source.document_id:
                    index.source_ids.add(claim.source.document_id)
            index.source_ids.update(case_understanding.documents_processed)

        if evidence_conflict:
            for conflict in evidence_conflict.conflicts:
                index.add_finding(conflict.conflict_id, FindingKind.CONFLICT)
                for side in (conflict.side_a, conflict.side_b):
                    if side.source.document_id:
                        index.source_ids.add(side.source.document_id)
            for gap in evidence_conflict.support_gaps:
                index.add_finding(gap.gap_id, FindingKind.SUPPORT_GAP)
                if gap.claim_source.document_id:
                    index.source_ids.add(gap.claim_source.document_id)
            index.evidence_ids.update(evidence_conflict.evidence_processed)
            index.claim_ids.update(evidence_conflict.claims_processed)

        if authority_citation:
            for finding in authority_citation.findings:
                index.add_finding(finding.finding_id, FindingKind.CITATION_FINDING)
                if finding.authority_id:
                    index.source_ids.add(finding.authority_id)
                for source in finding.sources:
                    index.source_ids.add(source.source_id)
            index.claim_ids.update(authority_citation.propositions_processed)

        if counter_argument:
            for finding in counter_argument.findings:
                index.add_finding(finding.finding_id, FindingKind.COUNTER_ANALYSIS)
                if finding.claim_source.document_id:
                    index.source_ids.add(finding.claim_source.document_id)
                for item in (*finding.supporting_evidence, *finding.contrary_evidence):
                    index.evidence_ids.add(item.evidence_id)
                    if item.source.document_id:
                        index.source_ids.add(item.source.document_id)
                for auth in (*finding.supporting_authority, *finding.contrary_authority):
                    index.source_ids.add(auth.authority_id)
            index.claim_ids.update(counter_argument.targets_processed)

        return index


# --------------------------------------------------------------------------
# Structural validation of the report
# --------------------------------------------------------------------------


def validate_risk_items(
    items: Iterable[RiskItem], index: TraceIndex
) -> tuple[list[RiskItem], list[ValidationFailure]]:
    """Keep only risk items that trace all the way back."""
    kept: list[RiskItem] = []
    failures: list[ValidationFailure] = []

    for item in items:
        if not index.knows_finding(item.finding_id, item.finding_kind):
            failures.append(ValidationFailure(
                kind="untraceable_risk_item",
                detail=(
                    f"Risk item {item.risk_id} names finding {item.finding_id!r} of kind "
                    f"{item.finding_kind.value}, which is not among the findings supplied to this "
                    "report. A risk that cannot be traced to a finding is not reported."
                ),
                dropped_id=item.risk_id,
            ))
            continue

        if item.claim_id and item.claim_id not in index.claim_ids:
            failures.append(ValidationFailure(
                kind="unknown_claim_reference",
                detail=(
                    f"Risk item {item.risk_id} references claim {item.claim_id!r}, which no "
                    "upstream stage produced."
                ),
                dropped_id=item.risk_id,
            ))
            continue

        fabricated = [
            ref.source_id for ref in item.source_references
            if ref.source_id and ref.source_id not in index.source_ids
        ]
        if fabricated:
            failures.append(ValidationFailure(
                kind="fabricated_source",
                detail=(
                    f"Risk item {item.risk_id} points at {len(fabricated)} source(s) that no "
                    "upstream stage supplied."
                ),
                dropped_id=item.risk_id,
            ))
            continue

        kept.append(item)

    return kept, failures


def find_findings_without_provenance(
    *,
    case_understanding: Optional[CaseUnderstandingResult],
    authority_citation: Optional[AuthorityCitationResult],
) -> list[ValidationFailure]:
    """Flag findings that assert something as established while carrying no
    pointer to an artifact a human could open.

    The upstream schemas make most of these unconstructable, so this is a
    backstop for results assembled by other means (a replay from storage, a
    hand-built fixture, a future stage). It flags rather than repairs.
    """
    failures: list[ValidationFailure] = []

    if case_understanding:
        for claim in case_understanding.claims:
            if claim.verification_status != VerificationStatus.VERIFIED:
                continue
            if not claim.source.document_id:
                failures.append(ValidationFailure(
                    kind="finding_without_provenance",
                    detail=(
                        f"Claim {claim.claim_id} is marked VERIFIED but its source names no "
                        "document, so it cannot be traced back to a case document."
                    ),
                    dropped_id=claim.claim_id,
                ))

    if authority_citation:
        for finding in authority_citation.findings:
            if finding.relationship.value == "SUPPORTS" and not finding.sources:
                failures.append(ValidationFailure(
                    kind="finding_without_provenance",
                    detail=(
                        f"Citation finding {finding.finding_id} records support but carries no "
                        "source provenance."
                    ),
                    dropped_id=finding.finding_id,
                ))

    return failures


# --------------------------------------------------------------------------
# Narrative checking
# --------------------------------------------------------------------------


def check_narrative(
    narrative: str, *, corpus: str, allowed_ids: set[str]
) -> list[str]:
    """Problems with a model-written summary (empty list = acceptable).

    `allowed_ids` is every identifier that already exists: the upstream ids
    from the `TraceIndex` plus the report's own risk and review ids. An
    identifier outside that set is an invented finding, claim or source.

    Reasons never repeat the offending text, so a rejected narrative cannot
    leak into the report through its own audit record.
    """
    problems: list[str] = []
    if not narrative.strip():
        return ["the narrative was blank"]

    lowered = narrative.lower()
    for phrase in OUTCOME_LANGUAGE:
        if phrase in lowered:
            problems.append(
                "the narrative predicts an outcome or determines guilt, liability or credibility"
            )
            break

    for match in _ID_TOKEN_RE.finditer(narrative):
        token = match.group(0)
        if token not in allowed_ids:
            problems.append(
                "the narrative names an identifier that does not exist in the supplied findings"
            )
            break

    problems.extend(find_ungrounded_references(narrative, corpus, []))
    return list(dict.fromkeys(problems))


def build_narrative_corpus(
    risk_items: Iterable[RiskItem], extra: Iterable[str] = ()
) -> str:
    """Everything the narrative is allowed to draw on: the report's own
    reasons and ids, and nothing else."""
    parts: list[str] = list(extra)
    for item in risk_items:
        parts.extend([item.reason, item.risk_id, item.finding_id, item.issue_type.value])
        if item.claim_id:
            parts.append(item.claim_id)
        for ref in item.source_references:
            if ref.source_id:
                parts.append(ref.source_id)
            if ref.authority is not None:
                parts.extend(x for x in (ref.authority.title, ref.authority.citation,
                                         ref.authority.exact_text) if x)
            if ref.document is not None and ref.document.quote:
                parts.append(ref.document.quote)
    return "\n".join(p for p in parts if p)


def source_refs_are_traceable(refs: Iterable[SourceRef]) -> bool:
    """True if every reference identifies an artifact a human could open."""
    return all(ref.is_traceable_to_an_artifact() for ref in refs)
