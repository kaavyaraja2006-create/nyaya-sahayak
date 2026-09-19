"""Deterministic risk calculation.

Risk levels are computed here, by table and by named rule. No model is
consulted, no score is invented, and nothing is probabilistic: the same
findings always produce the same levels, and every level can be explained by
reading back the rule names recorded in `RiskItem.rules_applied`.

The design is a base table plus a small number of escalation rules:

    BASE        every issue type has a fixed base level.
    R1-MATERIAL an issue on a claim the caller marked material escalates
                MEDIUM -> HIGH, for the issue types where materiality is what
                makes the problem serious (an unsupported *important* claim,
                a major evidence conflict, an unresolved counterargument on an
                important claim).
    R2-COMBINED a claim carrying two or more *distinct* MEDIUM issue types has
                compounding problems; those MEDIUM items escalate to HIGH.
    R3-SOLE     a potentially outdated authority that is the only supporting
                authority for its claim escalates MEDIUM -> HIGH.

Rules only ever escalate. Nothing here can lower a level, so no combination of
inputs can talk the report down from HIGH. LOW items are never escalated: a
metadata problem does not become a serious one by keeping company.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .schemas import RISK_ORDER, FindingKind, IssueType, RiskLevel, SourceRef

# --------------------------------------------------------------------------
# The base table
# --------------------------------------------------------------------------

BASE_RISK: dict[IssueType, RiskLevel] = {
    # HIGH: the finding directly contradicts something, or the chain back to a
    # source is broken. Neither can be left to a reader to notice.
    IssueType.CITATION_MISMATCH: RiskLevel.HIGH,
    IssueType.PROVENANCE_FAILURE: RiskLevel.HIGH,
    # MEDIUM: real gaps and tensions that a professional must look at, but
    # which are not by themselves contradictions.
    IssueType.UNSUPPORTED_CLAIM: RiskLevel.MEDIUM,
    IssueType.PARTIALLY_SUPPORTED_CLAIM: RiskLevel.MEDIUM,
    IssueType.UNVERIFIED_CLAIM: RiskLevel.MEDIUM,
    IssueType.MISSING_EVIDENCE: RiskLevel.MEDIUM,
    IssueType.EVIDENCE_CONFLICT: RiskLevel.MEDIUM,
    IssueType.PARTIAL_CITATION_SUPPORT: RiskLevel.MEDIUM,
    IssueType.AMBIGUOUS_CITATION: RiskLevel.MEDIUM,
    IssueType.AUTHORITY_NOT_FOUND: RiskLevel.MEDIUM,
    IssueType.UNCITED_LEGAL_PROPOSITION: RiskLevel.MEDIUM,
    IssueType.AUTHORITY_STATUS_UNCERTAIN: RiskLevel.MEDIUM,
    IssueType.POTENTIALLY_OUTDATED_AUTHORITY: RiskLevel.MEDIUM,
    IssueType.UNRESOLVED_COUNTERARGUMENT: RiskLevel.MEDIUM,
    IssueType.CONTRARY_AUTHORITY: RiskLevel.MEDIUM,
    IssueType.COUNTER_ANALYSIS_INCOMPLETE: RiskLevel.MEDIUM,
    # LOW: hygiene. Worth recording, not worth interrupting anyone for.
    IssueType.UNRESOLVED_QUESTION: RiskLevel.LOW,
    IssueType.METADATA_ISSUE: RiskLevel.LOW,
    IssueType.NON_CRITICAL_CITATION_OMISSION: RiskLevel.LOW,
}

# Issue types where the claim being material is what makes the problem
# serious. (R1)
MATERIAL_ESCALATING: frozenset[IssueType] = frozenset({
    IssueType.UNSUPPORTED_CLAIM,
    IssueType.MISSING_EVIDENCE,
    IssueType.EVIDENCE_CONFLICT,
    IssueType.UNRESOLVED_COUNTERARGUMENT,
})

# LOW issue types that still always go to a human despite their level.
ALWAYS_REVIEW: frozenset[IssueType] = frozenset()


def base_risk(issue_type: IssueType) -> RiskLevel:
    """The table lookup. An unmapped issue type is a programming error, not a
    reason to guess: it fails loudly rather than defaulting to LOW."""
    try:
        return BASE_RISK[issue_type]
    except KeyError as exc:  # pragma: no cover - guarded by test_every_issue_type_has_a_base_risk
        raise KeyError(f"No base risk level is defined for {issue_type!r}.") from exc


def requires_review(level: RiskLevel, issue_type: IssueType) -> bool:
    """HIGH and MEDIUM always go to a human; LOW does not, unless its issue
    type is in ALWAYS_REVIEW."""
    return level in (RiskLevel.HIGH, RiskLevel.MEDIUM) or issue_type in ALWAYS_REVIEW


# --------------------------------------------------------------------------
# Candidates and assessment
# --------------------------------------------------------------------------


@dataclass
class RiskCandidate:
    """An issue detected from an upstream finding, before it is levelled.

    `finding_id` is mandatory at this stage already: a candidate that cannot
    name the finding it came from never gets as far as being a risk item.
    """

    issue_type: IssueType
    reason: str
    finding_id: str
    finding_kind: FindingKind
    claim_id: Optional[str] = None
    source_references: list[SourceRef] = field(default_factory=list)
    is_material: bool = False
    is_sole_supporting_authority: bool = False


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    rules_applied: list[str]


def assess(candidate: RiskCandidate) -> RiskAssessment:
    """Base level plus the per-item escalation rules (R1, R3)."""
    level = base_risk(candidate.issue_type)
    rules = [f"BASE:{candidate.issue_type.value}={level.value}"]

    if (
        level == RiskLevel.MEDIUM
        and candidate.is_material
        and candidate.issue_type in MATERIAL_ESCALATING
    ):
        level = RiskLevel.HIGH
        rules.append("R1-MATERIAL:issue on a claim marked material -> HIGH")

    if (
        level == RiskLevel.MEDIUM
        and candidate.issue_type == IssueType.POTENTIALLY_OUTDATED_AUTHORITY
        and candidate.is_sole_supporting_authority
    ):
        level = RiskLevel.HIGH
        rules.append("R3-SOLE:the only supporting authority for this claim -> HIGH")

    return RiskAssessment(level=level, rules_applied=rules)


def apply_combination_rules(
    assessed: list[tuple[RiskCandidate, RiskAssessment]]
) -> list[tuple[RiskCandidate, RiskAssessment]]:
    """R2: compounding MEDIUM issues on one claim.

    A claim carrying two or more *distinct* MEDIUM issue types is in worse
    shape than the individual items suggest — for example a partially
    supported citation alongside an evidence conflict. Those MEDIUM items
    become HIGH. Distinctness is by issue type, so three findings of the same
    kind do not escalate each other; that is volume, not compounding.

    Order-independent: the escalation set is computed from all items first.
    """
    medium_types_by_claim: dict[str, set[IssueType]] = {}
    for candidate, assessment in assessed:
        if assessment.level != RiskLevel.MEDIUM or not candidate.claim_id:
            continue
        medium_types_by_claim.setdefault(candidate.claim_id, set()).add(candidate.issue_type)

    compounding = {
        claim_id for claim_id, types in medium_types_by_claim.items() if len(types) >= 2
    }
    if not compounding:
        return assessed

    out: list[tuple[RiskCandidate, RiskAssessment]] = []
    for candidate, assessment in assessed:
        if assessment.level == RiskLevel.MEDIUM and candidate.claim_id in compounding:
            count = len(medium_types_by_claim[candidate.claim_id])
            out.append((
                candidate,
                RiskAssessment(
                    level=RiskLevel.HIGH,
                    rules_applied=[
                        *assessment.rules_applied,
                        f"R2-COMBINED:{count} distinct MEDIUM issue types on this claim -> HIGH",
                    ],
                ),
            ))
        else:
            out.append((candidate, assessment))
    return out


def highest(levels: list[RiskLevel]) -> Optional[RiskLevel]:
    """The most severe level in a list, or None for an empty list."""
    if not levels:
        return None
    return max(levels, key=lambda level: RISK_ORDER[level])


# --------------------------------------------------------------------------
# Review routing
# --------------------------------------------------------------------------

from .schemas import ReviewType  # noqa: E402  (kept next to the tables it serves)

# Which human question an issue becomes. Deterministic, one-to-one.
REVIEW_TYPE_FOR_ISSUE: dict[IssueType, ReviewType] = {
    IssueType.UNSUPPORTED_CLAIM: ReviewType.UNSUPPORTED_CLAIM,
    IssueType.PARTIALLY_SUPPORTED_CLAIM: ReviewType.UNSUPPORTED_CLAIM,
    IssueType.UNVERIFIED_CLAIM: ReviewType.PROVENANCE_FAILURE,
    IssueType.MISSING_EVIDENCE: ReviewType.MISSING_SOURCE,
    IssueType.EVIDENCE_CONFLICT: ReviewType.CONTRADICTORY_EVIDENCE,
    IssueType.CITATION_MISMATCH: ReviewType.AMBIGUOUS_CITATION,
    IssueType.PARTIAL_CITATION_SUPPORT: ReviewType.AMBIGUOUS_CITATION,
    IssueType.AMBIGUOUS_CITATION: ReviewType.AMBIGUOUS_CITATION,
    IssueType.AUTHORITY_NOT_FOUND: ReviewType.MISSING_SOURCE,
    IssueType.UNCITED_LEGAL_PROPOSITION: ReviewType.MISSING_SOURCE,
    IssueType.AUTHORITY_STATUS_UNCERTAIN: ReviewType.UNCERTAIN_AUTHORITY_STATUS,
    IssueType.POTENTIALLY_OUTDATED_AUTHORITY: ReviewType.POTENTIALLY_OUTDATED_AUTHORITY,
    IssueType.UNRESOLVED_COUNTERARGUMENT: ReviewType.UNRESOLVED_COUNTERARGUMENT,
    IssueType.CONTRARY_AUTHORITY: ReviewType.UNRESOLVED_COUNTERARGUMENT,
    IssueType.COUNTER_ANALYSIS_INCOMPLETE: ReviewType.OTHER,
    IssueType.UNRESOLVED_QUESTION: ReviewType.OTHER,
    IssueType.PROVENANCE_FAILURE: ReviewType.PROVENANCE_FAILURE,
    IssueType.METADATA_ISSUE: ReviewType.OTHER,
    IssueType.NON_CRITICAL_CITATION_OMISSION: ReviewType.OTHER,
}

# What the reviewer is asked. Phrased as a decision for a human to make; none
# of these can be answered by this agent, which is the point.
REVIEW_QUESTIONS: dict[ReviewType, str] = {
    ReviewType.CONTRADICTORY_EVIDENCE: (
        "Two sources in the case material are inconsistent. Which source governs, and how should "
        "the inconsistency be addressed?"
    ),
    ReviewType.AMBIGUOUS_CITATION: (
        "A citation could not be matched cleanly to the authority relied on. Is the citation "
        "correct, and does the authority support the proposition as stated?"
    ),
    ReviewType.MISSING_SOURCE: (
        "No source in the approved material establishes this point. Does a source exist that was "
        "not supplied, or should the proposition be revised?"
    ),
    ReviewType.UNCERTAIN_AUTHORITY_STATUS: (
        "The currency of this authority is not recorded. Confirm whether it is still good law "
        "before relying on it."
    ),
    ReviewType.UNSUPPORTED_CLAIM: (
        "The supplied material does not establish this claim, or establishes only part of it. "
        "Confirm what support exists and whether the claim should stand as drafted."
    ),
    ReviewType.POTENTIALLY_OUTDATED_AUTHORITY: (
        "This authority is recorded as potentially outdated. Confirm its current status before "
        "relying on it."
    ),
    ReviewType.PROVENANCE_FAILURE: (
        "This finding cannot be traced back to a specific source document. Establish its "
        "provenance or remove it from the analysis."
    ),
    ReviewType.UNRESOLVED_COUNTERARGUMENT: (
        "Source-grounded material was found that could challenge or qualify this proposition. "
        "Decide how it should be addressed."
    ),
    ReviewType.OTHER: (
        "This item was flagged by the pipeline and has not been resolved. Review it before the "
        "analysis is relied on."
    ),
}


def review_type_for(issue_type: IssueType) -> ReviewType:
    return REVIEW_TYPE_FOR_ISSUE.get(issue_type, ReviewType.OTHER)
