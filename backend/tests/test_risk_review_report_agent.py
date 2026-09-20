"""Unit tests for the RiskReviewReportAgent.

The agent is deterministic: almost every test here runs it with no LLM at all
and asserts on exact risk levels. The only model-facing surface is the
optional narrative summary, tested at the end — including the case where the
model tries to add a finding that does not exist.

Two properties are checked repeatedly because the whole report depends on
them: every risk item traces back to a supplied finding
(`test_traceability_*`), and the agent never introduces a claim, source or
finding of its own (`test_no_new_findings_*`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from agents.authority_citation import (  # noqa: E402
    AuthorityCitationResult,
    AuthorityType,
    CitationFinding,
    CitationRelationship,
    SourceProvenance,
)
from agents.case_understanding.schemas import (  # noqa: E402
    CaseUnderstandingResult,
    Claim,
    ClaimType,
    SourceReference,
    VerificationStatus,
)
from agents.counter_argument import (  # noqa: E402
    CounterAnalysisStatus,
    CounterArgumentFinding,
    CounterArgumentResult,
    Counterpoint,
    CounterpointBasis,
    CounterpointType,
    MaterialKind,
    RetrievedAuthority,
    RetrievedEvidence,
    UnresolvedQuestion,
)
from agents.evidence_conflict import (  # noqa: E402
    Conflict,
    ConflictSide,
    ConflictType,
    EvidenceConflictResult,
    EvidenceItem,
    EvidenceType,
    GapType,
    SupportGap,
)
from agents.risk_review_report import (  # noqa: E402
    BASE_RISK,
    RISK_REVIEW_REPORT_SYSTEM_PROMPT,
    AuthorityStatus,
    AuthorityStatusRecord,
    FindingKind,
    IssueType,
    ReviewItem,
    ReviewType,
    RiskItem,
    RiskLevel,
    RiskReviewReportAgent,
    RiskReviewReportInput,
    SourceRef,
    TraceIndex,
    validate_risk_items,
)

L = RiskLevel
I = IssueType

# --------------------------------------------------------------------------
# Builders for upstream findings
# --------------------------------------------------------------------------

CLAIM_SOURCE = SourceReference(document_id="DOC-1", page=2, paragraph=7, quote="the accused was present")
EVIDENCE_SOURCE = SourceReference(document_id="DOC-CCTV", page=1, quote="no person recorded")


def claim(claim_id="C-1", verified=True, source=CLAIM_SOURCE, claim_type=ClaimType.FACTUAL) -> Claim:
    return Claim(
        claim_id=claim_id,
        claim_text="The accused was physically present at the scene.",
        claim_type=claim_type,
        source=source,
        verification_status=(
            VerificationStatus.VERIFIED if verified else VerificationStatus.UNVERIFIED
        ),
    )


def case_understanding(*claims, case_id="NS-2026-001", degraded=False) -> CaseUnderstandingResult:
    return CaseUnderstandingResult(
        case_id=case_id,
        claims=list(claims) or [claim()],
        documents_processed=["DOC-1", "DOC-CCTV"],
        degraded=degraded,
    )


def support_gap(gap_id="GAP-001", claim_id="C-1", gap_type=GapType.MISSING_EVIDENCE,
                related=()) -> SupportGap:
    return SupportGap(
        gap_id=gap_id,
        claim_id=claim_id,
        claim_source=CLAIM_SOURCE,
        gap_type=gap_type,
        related_evidence_ids=list(related),
        note="No evidence in the supplied material addresses this claim.",
    )


def conflict(conflict_id="CNF-001", claim_id="C-1", evidence_id="E-1") -> Conflict:
    return Conflict(
        conflict_id=conflict_id,
        conflict_type=ConflictType.CLAIM_EVIDENCE_CONTRADICTION,
        description="The claim and the evidence describe the same period differently.",
        side_a=ConflictSide(claim_id=claim_id, source=CLAIM_SOURCE),
        side_b=ConflictSide(evidence_id=evidence_id, source=EVIDENCE_SOURCE),
    )


def evidence_conflict(conflicts=(), gaps=(), claims=("C-1",), evidence=("E-1",),
                      case_id="NS-2026-001") -> EvidenceConflictResult:
    return EvidenceConflictResult(
        case_id=case_id,
        conflicts=list(conflicts),
        support_gaps=list(gaps),
        claims_processed=list(claims),
        evidence_processed=list(evidence),
    )


def provenance(authority_id="AUTH-1", exact_text="a verbatim span", paragraph="7") -> SourceProvenance:
    return SourceProvenance(
        source_id=authority_id,
        source_type=AuthorityType.CASE_LAW,
        title="Rao v State of Testland",
        citation="DEMO-114",
        exact_text=exact_text,
        paragraph=paragraph,
    )


def citation_finding(
    finding_id="CF-001",
    claim_id="C-1",
    relationship=CitationRelationship.CONTRADICTS,
    authority_id="AUTH-1",
    citation_text="Rao v State of Testland, DEMO-114",
    uncited=False,
    sources=None,
) -> CitationFinding:
    if uncited:
        return CitationFinding(
            finding_id=finding_id,
            claim_id=claim_id,
            relationship=CitationRelationship.REQUIRES_HUMAN_REVIEW,
            explanation="This legal proposition has no citation in the supplied material.",
            requires_human_review=True,
            uncited=True,
        )
    if sources is None:
        sources = [provenance(authority_id)]
    return CitationFinding(
        finding_id=finding_id,
        claim_id=claim_id,
        citation_text=citation_text,
        citation_type=AuthorityType.CASE_LAW,
        authority_id=authority_id,
        relationship=relationship,
        explanation="The supplied text was compared against the proposition.",
        sources=sources,
        requires_human_review=relationship != CitationRelationship.SUPPORTS,
    )


def authority_citation(*findings, claims=("C-1",), skipped=(), case_id="NS-2026-001",
                       degraded=False) -> AuthorityCitationResult:
    return AuthorityCitationResult(
        case_id=case_id,
        findings=list(findings),
        propositions_processed=list(claims),
        skipped_claim_ids=list(skipped),
        degraded=degraded,
    )


def retrieved_evidence(evidence_id="E-1") -> RetrievedEvidence:
    return RetrievedEvidence.from_item(EvidenceItem(
        evidence_id=evidence_id,
        evidence_type=EvidenceType.DOCUMENT,
        description="CCTV review records no person matching the description.",
        source=EVIDENCE_SOURCE,
    ))


def counter_finding(
    finding_id="CA-001",
    claim_id="C-1",
    status=CounterAnalysisStatus.CONTRARY_MATERIAL_FOUND,
    contrary_evidence=(),
    contrary_authority=(),
    counterpoints=(),
    questions=(),
) -> CounterArgumentFinding:
    return CounterArgumentFinding(
        finding_id=finding_id,
        claim_id=claim_id,
        claim_text="The accused was physically present at the scene.",
        claim_source=CLAIM_SOURCE,
        status=status,
        contrary_evidence=list(contrary_evidence),
        contrary_authority=list(contrary_authority),
        counterpoints=list(counterpoints),
        unresolved_questions=list(questions),
        analysis_note="The supplied corpus was searched for material bearing on this claim.",
        requires_human_review=True,
    )


def counter_argument(*findings, claims=("C-1",), case_id="NS-2026-001") -> CounterArgumentResult:
    return CounterArgumentResult(
        case_id=case_id, findings=list(findings), targets_processed=list(claims)
    )


def run(**kwargs) -> "object":
    material = kwargs.pop("material_claim_ids", [])
    statuses = kwargs.pop("authority_statuses", [])
    llm = kwargs.pop("llm", None)
    return RiskReviewReportAgent(llm=llm).run(RiskReviewReportInput(
        case_id="NS-2026-001",
        material_claim_ids=material,
        authority_statuses=statuses,
        **kwargs,
    ))


def only_risk(result) -> RiskItem:
    assert len(result.risk_items) == 1, [i.issue_type for i in result.risk_items]
    return result.risk_items[0]


def risks_of(result, issue_type) -> list[RiskItem]:
    return [i for i in result.risk_items if i.issue_type == issue_type]


class ScriptedLLM:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate(self, *, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if self.error:
            raise self.error
        return self.response


def narrating(text: str) -> ScriptedLLM:
    return ScriptedLLM(response=json.dumps({"narrative": text}))


# --------------------------------------------------------------------------
# 0. The rule tables themselves
# --------------------------------------------------------------------------


def test_risk_levels_are_exactly_the_three_specified():
    assert {level.value for level in RiskLevel} == {"HIGH", "MEDIUM", "LOW"}


def test_every_issue_type_has_a_deterministic_base_risk():
    missing = [i for i in IssueType if i not in BASE_RISK]
    assert missing == []


def test_system_prompt_states_the_agent_role():
    assert (
        "You are an aggregation and review-prioritization agent. You do not create new "
        "legal facts. You summarize and prioritize already verified findings."
        in RISK_REVIEW_REPORT_SYSTEM_PROMPT
    )


# --------------------------------------------------------------------------
# 1. High-risk unsupported claim
# --------------------------------------------------------------------------


def test_01_unsupported_material_claim_is_high():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        evidence_conflict=evidence_conflict(gaps=[support_gap()]),
        material_claim_ids=["C-1"],
    )
    item = only_risk(result)

    assert item.risk_level == L.HIGH
    assert item.issue_type == I.UNSUPPORTED_CLAIM
    assert item.finding_id == "GAP-001"
    assert item.finding_kind == FindingKind.SUPPORT_GAP
    assert item.claim_id == "C-1"
    assert item.requires_review is True
    # The level is explainable: base plus the rule that raised it.
    assert item.rules_applied == [
        "BASE:UNSUPPORTED_CLAIM=MEDIUM",
        "R1-MATERIAL:issue on a claim marked material -> HIGH",
    ]
    assert result.review_items[0].review_type == ReviewType.UNSUPPORTED_CLAIM


def test_01b_the_same_gap_on_a_peripheral_claim_is_medium_missing_evidence():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        evidence_conflict=evidence_conflict(gaps=[support_gap()]),
        material_claim_ids=[],                      # not marked material
    )
    item = only_risk(result)
    assert item.risk_level == L.MEDIUM
    assert item.issue_type == I.MISSING_EVIDENCE
    assert item.rules_applied == ["BASE:MISSING_EVIDENCE=MEDIUM"]


# --------------------------------------------------------------------------
# 2. Citation mismatch
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relationship",
    [CitationRelationship.CONTRADICTS, CitationRelationship.DOES_NOT_SUPPORT],
)
def test_02_citation_mismatch_is_high_without_needing_materiality(relationship):
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(citation_finding(relationship=relationship)),
    )
    item = only_risk(result)

    assert item.risk_level == L.HIGH
    assert item.issue_type == I.CITATION_MISMATCH
    assert item.rules_applied == ["BASE:CITATION_MISMATCH=HIGH"]
    assert item.finding_kind == FindingKind.CITATION_FINDING
    # The authority provenance from the citation stage is carried through intact.
    ref = item.source_references[0]
    assert ref.kind == "AUTHORITY"
    assert ref.authority.source_id == "AUTH-1"
    assert ref.authority.exact_text == "a verbatim span"
    assert ref.authority.paragraph == "7"
    assert result.review_items[0].review_type == ReviewType.AMBIGUOUS_CITATION


# --------------------------------------------------------------------------
# 3. Evidence conflict
# --------------------------------------------------------------------------


def test_03_evidence_conflict_on_a_material_claim_is_high():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        evidence_conflict=evidence_conflict(conflicts=[conflict()]),
        material_claim_ids=["C-1"],
    )
    item = only_risk(result)

    assert item.risk_level == L.HIGH
    assert item.issue_type == I.EVIDENCE_CONFLICT
    assert item.finding_id == "CNF-001"
    assert item.finding_kind == FindingKind.CONFLICT
    # Both sides of the conflict keep their own provenance.
    assert [r.source_id for r in item.source_references] == ["DOC-1", "DOC-CCTV"]
    assert result.review_items[0].review_type == ReviewType.CONTRADICTORY_EVIDENCE


def test_03b_evidence_conflict_on_a_peripheral_claim_is_medium():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        evidence_conflict=evidence_conflict(conflicts=[conflict()]),
    )
    assert only_risk(result).risk_level == L.MEDIUM


# --------------------------------------------------------------------------
# 4. Partial citation support
# --------------------------------------------------------------------------


def test_04_partial_citation_support_is_medium():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(
            citation_finding(relationship=CitationRelationship.PARTIALLY_SUPPORTS)
        ),
        material_claim_ids=["C-1"],           # materiality does not escalate this one
    )
    item = only_risk(result)

    assert item.risk_level == L.MEDIUM
    assert item.issue_type == I.PARTIAL_CITATION_SUPPORT
    assert item.rules_applied == ["BASE:PARTIAL_CITATION_SUPPORT=MEDIUM"]
    assert item.requires_review is True


# --------------------------------------------------------------------------
# 5. Missing evidence (nothing in the case material addresses the claim)
# --------------------------------------------------------------------------


def test_05_insufficient_support_is_a_partially_supported_claim():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        evidence_conflict=evidence_conflict(gaps=[support_gap(
            gap_type=GapType.INSUFFICIENT_SUPPORT, related=["E-1"]
        )]),
        material_claim_ids=["C-1"],
    )
    item = only_risk(result)
    assert item.issue_type == I.PARTIALLY_SUPPORTED_CLAIM
    assert item.risk_level == L.MEDIUM          # not in the materiality-escalating set
    assert "E-1" not in item.reason or "1 related" in item.reason


# --------------------------------------------------------------------------
# 6. Uncited legal proposition
# --------------------------------------------------------------------------


def test_06_uncited_legal_proposition_is_medium_and_queued_for_review():
    result = run(
        case_understanding=case_understanding(claim("C-1", claim_type=ClaimType.LEGAL)),
        authority_citation=authority_citation(citation_finding(uncited=True)),
    )
    item = only_risk(result)

    assert item.issue_type == I.UNCITED_LEGAL_PROPOSITION
    assert item.risk_level == L.MEDIUM
    assert item.source_references == []          # an uncited proposition has no source to point at
    assert result.review_items[0].review_type == ReviewType.MISSING_SOURCE


def test_06b_a_non_legal_uncited_claim_is_only_a_low_omission():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(skipped=["C-1"]),
    )
    item = only_risk(result)
    assert item.issue_type == I.NON_CRITICAL_CITATION_OMISSION
    assert item.risk_level == L.LOW
    assert item.requires_review is False
    assert result.review_items == []


def test_06c_a_skipped_claim_that_cannot_be_traced_is_not_reported():
    """No claim record means no finding to hang the risk on, so nothing is
    emitted rather than an untraceable item."""
    result = run(authority_citation=authority_citation(skipped=["C-404"]))
    assert result.risk_items == []


# --------------------------------------------------------------------------
# 7. Potentially outdated authority
# --------------------------------------------------------------------------


def test_07_potentially_outdated_authority_relied_on_alone_is_high():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(
            citation_finding(relationship=CitationRelationship.SUPPORTS)
        ),
        authority_statuses=[AuthorityStatusRecord(
            authority_id="AUTH-1", status=AuthorityStatus.POTENTIALLY_OUTDATED
        )],
    )
    item = only_risk(result)

    assert item.issue_type == I.POTENTIALLY_OUTDATED_AUTHORITY
    assert item.risk_level == L.HIGH
    assert item.rules_applied[-1].startswith("R3-SOLE")
    assert result.review_items[0].review_type == ReviewType.POTENTIALLY_OUTDATED_AUTHORITY


def test_07b_potentially_outdated_authority_with_other_support_stays_medium():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(
            citation_finding(finding_id="CF-001", relationship=CitationRelationship.SUPPORTS),
            citation_finding(
                finding_id="CF-002", relationship=CitationRelationship.SUPPORTS,
                authority_id="AUTH-2", citation_text="Other v Testland",
                sources=[provenance("AUTH-2")],
            ),
        ),
        authority_statuses=[AuthorityStatusRecord(
            authority_id="AUTH-1", status=AuthorityStatus.POTENTIALLY_OUTDATED
        )],
    )
    item = only_risk(result)
    assert item.risk_level == L.MEDIUM
    assert item.rules_applied == ["BASE:POTENTIALLY_OUTDATED_AUTHORITY=MEDIUM"]


def test_07c_unknown_authority_status_is_flagged_only_where_it_is_relied_on():
    supports = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(
            citation_finding(relationship=CitationRelationship.SUPPORTS)
        ),
        authority_statuses=[AuthorityStatusRecord(
            authority_id="AUTH-1", status=AuthorityStatus.UNKNOWN
        )],
    )
    assert only_risk(supports).issue_type == I.AUTHORITY_STATUS_UNCERTAIN
    assert supports.review_items[0].review_type == ReviewType.UNCERTAIN_AUTHORITY_STATUS

    # The same unknown status on an authority that was found not to support
    # anything adds nothing beyond the mismatch already recorded.
    mismatch = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(
            citation_finding(relationship=CitationRelationship.DOES_NOT_SUPPORT)
        ),
        authority_statuses=[AuthorityStatusRecord(
            authority_id="AUTH-1", status=AuthorityStatus.UNKNOWN
        )],
    )
    assert [i.issue_type for i in mismatch.risk_items] == [I.CITATION_MISMATCH]


def test_07d_current_authority_raises_nothing():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(
            citation_finding(relationship=CitationRelationship.SUPPORTS)
        ),
        authority_statuses=[AuthorityStatusRecord(
            authority_id="AUTH-1", status=AuthorityStatus.CURRENT
        )],
    )
    assert result.risk_items == []
    assert result.summary.highest_risk_level is None


# --------------------------------------------------------------------------
# 8. Missing provenance
# --------------------------------------------------------------------------


def test_08_verified_claim_without_a_document_is_a_high_provenance_failure():
    unanchored = claim(source=SourceReference(quote="the accused was present"))
    result = run(case_understanding=case_understanding(unanchored))
    item = only_risk(result)

    assert item.issue_type == I.PROVENANCE_FAILURE
    assert item.risk_level == L.HIGH
    assert item.finding_kind == FindingKind.CLAIM
    assert item.finding_id == "C-1"
    assert result.review_items[0].review_type == ReviewType.PROVENANCE_FAILURE
    # Flagged as well as risked, so the failure is visible in the audit record.
    assert [f.kind for f in result.validation_failures] == ["finding_without_provenance"]
    assert result.dashboard.provenance_failures == 2


def test_08b_an_unverified_claim_is_a_provenance_review_item():
    result = run(case_understanding=case_understanding(claim(verified=False)))
    item = only_risk(result)
    assert item.issue_type == I.UNVERIFIED_CLAIM
    assert item.risk_level == L.MEDIUM
    assert result.review_items[0].review_type == ReviewType.PROVENANCE_FAILURE


def test_08c_a_risk_item_that_does_not_trace_to_a_finding_is_dropped():
    """The validation gate, exercised directly: this is the invariant that
    makes Risk -> Finding -> Claim -> Source total."""
    index = TraceIndex.build(
        case_understanding=case_understanding(claim("C-1")),
        evidence_conflict=None,
        authority_citation=None,
        counter_argument=None,
    )
    orphan = RiskItem(
        risk_id="RISK-001",
        risk_level=L.HIGH,
        issue_type=I.CITATION_MISMATCH,
        reason="An issue with no underlying finding.",
        finding_id="CF-999",
        finding_kind=FindingKind.CITATION_FINDING,
        claim_id="C-1",
        rules_applied=["BASE:CITATION_MISMATCH=HIGH"],
        requires_review=True,
    )
    kept, failures = validate_risk_items([orphan], index)

    assert kept == []
    assert failures[0].kind == "untraceable_risk_item"
    assert failures[0].dropped_id == "RISK-001"


def test_08d_a_risk_item_pointing_at_an_unsupplied_source_is_dropped():
    index = TraceIndex.build(
        case_understanding=case_understanding(claim("C-1")),
        evidence_conflict=None, authority_citation=None, counter_argument=None,
    )
    fabricated = RiskItem(
        risk_id="RISK-001",
        risk_level=L.MEDIUM,
        issue_type=I.AUTHORITY_NOT_FOUND,
        reason="Points at an authority nobody supplied.",
        finding_id="C-1",
        finding_kind=FindingKind.CLAIM,
        claim_id="C-1",
        source_references=[SourceRef.from_authority(provenance("AUTH-INVENTED"))],
        rules_applied=["BASE:AUTHORITY_NOT_FOUND=MEDIUM"],
        requires_review=True,
    )
    kept, failures = validate_risk_items([fabricated], index)
    assert kept == []
    assert failures[0].kind == "fabricated_source"


# --------------------------------------------------------------------------
# 9. Hallucinated new finding in the narrative
# --------------------------------------------------------------------------


def test_09_a_narrative_naming_a_finding_that_does_not_exist_is_discarded():
    llm = narrating(
        "The most serious problem is RISK-001. A further issue, CF-914 on claim C-77, "
        "also needs attention."
    )
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(citation_finding()),
        llm=llm,
    )

    assert result.summary.narrative is None            # discarded whole, not trimmed
    assert result.summary.headline.startswith("1 risk item(s)")
    assert [f.kind for f in result.validation_failures] == ["new_claim_in_summary"]
    assert "C-77" not in result.model_dump_json()
    # The report itself is untouched by the bad narrative.
    assert only_risk(result).risk_level == L.HIGH


def test_09b_a_narrative_predicting_an_outcome_is_discarded():
    llm = narrating("RISK-001 is serious, and on this material the prosecution will fail.")
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(citation_finding()),
        llm=llm,
    )
    assert result.summary.narrative is None
    assert result.validation_failures[0].kind == "unsafe_summary"
    assert "prosecution will fail" not in result.model_dump_json()


def test_09c_a_narrative_quoting_something_not_in_the_report_is_discarded():
    llm = narrating('The file notes that the witness "never attended the premises at all".')
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(citation_finding()),
        llm=llm,
    )
    assert result.summary.narrative is None


def test_09d_a_faithful_narrative_is_kept():
    llm = narrating(
        "This report contains one item, RISK-001, and it is the most serious one. "
        "It should be reviewed before the analysis is relied on."
    )
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(citation_finding()),
        llm=llm,
    )
    assert result.summary.narrative.startswith("This report contains one item")
    assert result.validation_failures == []


def test_09e_a_failing_narrative_model_does_not_degrade_the_report():
    no_llm = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(citation_finding()),
    )
    broken = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(citation_finding()),
        llm=ScriptedLLM(error=TimeoutError("model timed out")),
    )

    assert broken.summary.narrative is None
    assert any("could not be generated" in w for w in broken.warnings)
    assert [i.model_dump() for i in broken.risk_items] == [i.model_dump() for i in no_llm.risk_items]


def test_09f_the_narrative_prompt_hands_the_model_a_finished_report():
    llm = narrating("One item, RISK-001, needs review.")
    run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(citation_finding()),
        llm=llm,
    )
    _, user_prompt = llm.calls[0]
    assert "THE REPORT IS ALREADY COMPLETE" in user_prompt
    assert "RISK-001 | HIGH | CITATION_MISMATCH" in user_prompt
    assert "do not re-level anything" in user_prompt


# --------------------------------------------------------------------------
# 10. Counter-analysis findings
# --------------------------------------------------------------------------


def test_10_unresolved_counterargument_on_a_material_claim_is_high():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        counter_argument=counter_argument(counter_finding(
            contrary_evidence=[retrieved_evidence()],
            counterpoints=[Counterpoint(
                counterpoint_id="CP-001",
                claim_id="C-1",
                counterpoint_type=CounterpointType.CONTRARY_EVIDENCE,
                statement="The CCTV review records no person matching the description.",
                basis=[CounterpointBasis(
                    kind=MaterialKind.EVIDENCE, evidence=retrieved_evidence()
                )],
            )],
        )),
        material_claim_ids=["C-1"],
    )
    item = only_risk(result)

    assert item.issue_type == I.UNRESOLVED_COUNTERARGUMENT
    assert item.risk_level == L.HIGH
    assert item.finding_kind == FindingKind.COUNTER_ANALYSIS
    assert result.review_items[0].review_type == ReviewType.UNRESOLVED_COUNTERARGUMENT
    assert result.review_items[0].status == "REQUIRES_HUMAN_REVIEW"


def test_10b_contrary_authority_is_medium_and_keeps_its_quotation():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        counter_argument=counter_argument(counter_finding(
            contrary_authority=[RetrievedAuthority(
                authority_id="AUTH-1", passage_id="P1", provenance=provenance()
            )],
        )),
    )
    item = only_risk(result)
    assert item.issue_type == I.CONTRARY_AUTHORITY
    assert item.risk_level == L.MEDIUM
    assert item.source_references[0].authority.exact_text == "a verbatim span"


def test_10c_a_counter_analysis_that_never_ran_is_reported_as_incomplete():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        counter_argument=counter_argument(counter_finding(
            status=CounterAnalysisStatus.NOT_ASSESSED
        )),
    )
    item = only_risk(result)
    assert item.issue_type == I.COUNTER_ANALYSIS_INCOMPLETE
    assert "not the same as finding none" in item.reason


def test_10d_a_clean_counter_analysis_produces_no_risk():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        counter_argument=counter_argument(counter_finding(
            status=CounterAnalysisStatus.NO_CONTRARY_SOURCE_FOUND
        )),
    )
    assert result.risk_items == []


def test_10e_unresolved_questions_are_low():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        counter_argument=counter_argument(counter_finding(
            status=CounterAnalysisStatus.NO_CONTRARY_SOURCE_FOUND,
            questions=[UnresolvedQuestion(
                question_id="UQ-001",
                claim_id="C-1",
                question="No material states who was carrying the handset.",
                about_absent_material=True,
            )],
        )),
    )
    item = only_risk(result)
    assert item.issue_type == I.UNRESOLVED_QUESTION
    assert item.risk_level == L.LOW
    assert item.requires_review is False


# --------------------------------------------------------------------------
# 11. Combination rule
# --------------------------------------------------------------------------


def test_11_two_distinct_medium_issues_on_one_claim_escalate_to_high():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        evidence_conflict=evidence_conflict(conflicts=[conflict()]),      # MEDIUM
        authority_citation=authority_citation(                            # MEDIUM
            citation_finding(relationship=CitationRelationship.PARTIALLY_SUPPORTS)
        ),
    )
    assert {i.risk_level for i in result.risk_items} == {L.HIGH}
    for item in result.risk_items:
        assert any(rule.startswith("R2-COMBINED") for rule in item.rules_applied)


def test_11b_two_issues_of_the_same_type_do_not_escalate_each_other():
    result = run(
        case_understanding=case_understanding(claim("C-1")),
        authority_citation=authority_citation(
            citation_finding(finding_id="CF-001",
                             relationship=CitationRelationship.PARTIALLY_SUPPORTS),
            citation_finding(finding_id="CF-002",
                             relationship=CitationRelationship.PARTIALLY_SUPPORTS,
                             citation_text="Other v Testland"),
        ),
    )
    assert [i.risk_level for i in result.risk_items] == [L.MEDIUM, L.MEDIUM]


def test_11c_low_items_are_never_escalated_by_company():
    result = run(
        case_understanding=case_understanding(claim("C-1"), claim("C-2")),
        evidence_conflict=evidence_conflict(conflicts=[conflict()], claims=["C-1", "C-2"]),
        authority_citation=authority_citation(
            citation_finding(relationship=CitationRelationship.PARTIALLY_SUPPORTS),
            skipped=["C-1"],
        ),
    )
    low = risks_of(result, I.NON_CRITICAL_CITATION_OMISSION)
    assert [i.risk_level for i in low] == [L.LOW]


# --------------------------------------------------------------------------
# 12. Traceability, determinism, and adding nothing
# --------------------------------------------------------------------------


def full_case_input() -> dict:
    return dict(
        case_understanding=case_understanding(claim("C-1"), claim("C-2", verified=False)),
        evidence_conflict=evidence_conflict(
            conflicts=[conflict()], gaps=[support_gap(claim_id="C-2")], claims=["C-1", "C-2"]
        ),
        authority_citation=authority_citation(
            citation_finding(relationship=CitationRelationship.CONTRADICTS),
            claims=["C-1", "C-2"],
        ),
        counter_argument=counter_argument(
            counter_finding(contrary_evidence=[retrieved_evidence()]), claims=["C-1"]
        ),
        material_claim_ids=["C-1"],
    )


def test_12_every_risk_traces_to_a_finding_a_claim_and_its_sources():
    result = run(**full_case_input())
    index = TraceIndex.build(
        case_understanding=full_case_input()["case_understanding"],
        evidence_conflict=full_case_input()["evidence_conflict"],
        authority_citation=full_case_input()["authority_citation"],
        counter_argument=full_case_input()["counter_argument"],
    )

    assert result.risk_items
    for item in result.risk_items:
        assert index.knows_finding(item.finding_id, item.finding_kind)
        assert item.claim_id in {"C-1", "C-2"}
        for ref in item.source_references:
            assert ref.source_id in index.source_ids
        assert item.rules_applied                      # always explainable


def test_12b_every_review_item_points_back_at_its_risks_and_findings():
    result = run(**full_case_input())
    risk_ids = {i.risk_id for i in result.risk_items}
    finding_ids = {i.finding_id for i in result.risk_items}

    assert result.review_items
    for review in result.review_items:
        assert set(review.risk_item_ids) <= risk_ids
        assert set(review.finding_ids) <= finding_ids
        assert review.status == "REQUIRES_HUMAN_REVIEW"


def test_12c_the_report_introduces_no_claim_source_or_finding_of_its_own():
    payload = full_case_input()
    result = run(**payload)
    index = TraceIndex.build(
        case_understanding=payload["case_understanding"],
        evidence_conflict=payload["evidence_conflict"],
        authority_citation=payload["authority_citation"],
        counter_argument=payload["counter_argument"],
    )
    known = index.all_known_ids()

    for item in result.risk_items:
        assert item.finding_id in known
        assert item.claim_id in known
    assert result.validation_failures == []


def test_12d_the_report_is_deterministic():
    first = run(**full_case_input())
    second = run(**full_case_input())
    assert first.model_dump() == second.model_dump()


def test_12e_the_dashboard_counts_match_the_items():
    result = run(**full_case_input())
    d = result.dashboard

    assert d.total_risk_items == len(result.risk_items)
    assert d.high_count == sum(1 for i in result.risk_items if i.risk_level == L.HIGH)
    assert d.medium_count == sum(1 for i in result.risk_items if i.risk_level == L.MEDIUM)
    assert d.low_count == sum(1 for i in result.risk_items if i.risk_level == L.LOW)
    assert d.total_review_items == len(result.review_items)
    assert sum(d.risk_by_issue_type.values()) == d.total_risk_items
    assert d.claims_assessed == 2
    assert set(d.claims_with_risk) <= {"C-1", "C-2"}
    assert {s.stage for s in d.stages} == {
        "case_understanding", "evidence_conflict", "authority_citation", "counter_argument"
    }
    assert all(s.present for s in d.stages)
    assert result.summary.highest_risk_level == L.HIGH
    assert result.summary.total_review_items == len(result.review_items)


# --------------------------------------------------------------------------
# 13. Absent and degraded stages
# --------------------------------------------------------------------------


def test_13_a_missing_stage_is_declared_not_assumed_clean():
    result = run(case_understanding=case_understanding(claim("C-1")))

    assert result.risk_items == []
    missing = [s.stage for s in result.dashboard.stages if not s.present]
    assert missing == ["evidence_conflict", "authority_citation", "counter_argument"]
    assert any("not the same as there being none" in w for w in result.warnings)


def test_13b_an_upstream_degraded_stage_is_surfaced():
    result = run(
        case_understanding=case_understanding(claim("C-1"), degraded=True),
        authority_citation=authority_citation(citation_finding(), degraded=True),
    )
    degraded = [s.stage for s in result.dashboard.stages if s.degraded]
    assert degraded == ["case_understanding", "authority_citation"]
    assert any("degraded operation" in w for w in result.warnings)


def test_13c_an_empty_report_says_so_rather_than_inventing_content():
    result = run()
    assert result.risk_items == []
    assert result.review_items == []
    assert result.summary.narrative is None
    assert result.summary.highest_risk_level is None
    assert result.summary.headline.startswith("0 risk item(s)")


# --------------------------------------------------------------------------
# 14. The schemas refuse what the agent must not do
# --------------------------------------------------------------------------


def test_14_a_risk_item_cannot_be_constructed_without_a_finding():
    with pytest.raises(ValidationError):
        RiskItem(
            risk_id="RISK-001",
            risk_level=L.HIGH,
            issue_type=I.CITATION_MISMATCH,
            reason="Something looks wrong.",
            finding_id="",
            finding_kind=FindingKind.CITATION_FINDING,
            rules_applied=["BASE:CITATION_MISMATCH=HIGH"],
            requires_review=True,
        )


def test_14b_a_risk_level_must_be_explainable():
    with pytest.raises(ValidationError):
        RiskItem(
            risk_id="RISK-001",
            risk_level=L.HIGH,
            issue_type=I.CITATION_MISMATCH,
            reason="Something looks wrong.",
            finding_id="CF-001",
            finding_kind=FindingKind.CITATION_FINDING,
            rules_applied=[],
            requires_review=True,
        )


def test_14c_a_review_item_cannot_be_marked_resolved():
    with pytest.raises(ValidationError):
        ReviewItem(
            review_id="REVIEW-001",
            review_type=ReviewType.MISSING_SOURCE,
            risk_level=L.MEDIUM,
            question="Does a source exist?",
            reason="Raised by one risk item.",
            risk_item_ids=["RISK-001"],
            finding_ids=["CF-001"],
            status="RESOLVED",
        )


def test_14d_report_text_cannot_predict_an_outcome():
    with pytest.raises(ValidationError):
        RiskItem(
            risk_id="RISK-001",
            risk_level=L.HIGH,
            issue_type=I.CITATION_MISMATCH,
            reason="This means the defence will fail at trial.",
            finding_id="CF-001",
            finding_kind=FindingKind.CITATION_FINDING,
            rules_applied=["BASE:CITATION_MISMATCH=HIGH"],
            requires_review=True,
        )


def test_14e_a_source_ref_carries_exactly_one_kind_of_provenance():
    with pytest.raises(ValidationError):
        SourceRef(kind="DOCUMENT", document=CLAIM_SOURCE, authority=provenance())
    with pytest.raises(ValidationError):
        SourceRef(kind="AUTHORITY", document=CLAIM_SOURCE)

    ref = SourceRef.from_document(SourceReference(quote="only a quote"))
    assert ref.is_traceable_to_an_artifact() is False
    assert SourceRef.from_document(CLAIM_SOURCE).is_traceable_to_an_artifact() is True
