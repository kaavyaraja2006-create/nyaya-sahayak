"""Tests for the five-agent LangGraph pipeline.

No network, no database: one fake LLM provider answers all five stages by
looking at which system prompt it was handed. That routing is itself part of
what is being tested — if the graph ever called an agent out of order, or
called one twice, the recorded call order would say so.

The corpus is fictional ("Testland") on purpose. Nothing here depends on
what a real model happens to remember about real law.

The five required proofs are the tests numbered 1 to 5 below.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from agents.authority_citation import (  # noqa: E402
    AuthorityPassage,
    AuthorityType,
    CitationRelationship,
    SuppliedAuthority,
)
from agents.authority_citation.prompts import AUTHORITY_CITATION_SYSTEM_PROMPT  # noqa: E402
from agents.case_understanding.prompts import CASE_UNDERSTANDING_SYSTEM_PROMPT  # noqa: E402
from agents.case_understanding.schemas import (  # noqa: E402
    DocumentKind,
    Page,
    Paragraph,
    SourceDocument,
    SourceReference,
    VerificationStatus,
)
from agents.counter_argument import CounterAnalysisStatus  # noqa: E402
from agents.counter_argument.prompts import COUNTER_ARGUMENT_SYSTEM_PROMPT  # noqa: E402
from agents.evidence_conflict import EvidenceItem, EvidenceType, GapType  # noqa: E402
from agents.evidence_conflict.prompts import EVIDENCE_CONFLICT_SYSTEM_PROMPT  # noqa: E402
from agents.graph import (  # noqa: E402
    PIPELINE_ORDER,
    NyayaSahayakState,
    StageName,
    StageOutcome,
    build_default_agents,
    build_nyaya_graph,
    run_pipeline,
)
from agents.risk_review_report import RiskLevel  # noqa: E402
from agents.risk_review_report.prompts import RISK_REVIEW_REPORT_SYSTEM_PROMPT  # noqa: E402

# --------------------------------------------------------------------------
# Fixture corpus
# --------------------------------------------------------------------------

STATEMENT_TEXT = (
    "I saw the accused standing at the junction adjoining the premises at about 9:40 PM."
)
SUBMISSION_TEXT = (
    "A witness account of presence must be read together with the independent records."
)
DEVICE_TEXT = (
    "Device location record for handset IMEI-4417 places the device at the junction "
    "adjoining the scene between 21:36 and 21:52."
)
CCTV_TEXT = (
    "CCTV review of the junction covering 21:30 to 22:00 records no person matching the "
    "description given for the accused entering or leaving the premises."
)
AUTH_P1 = (
    "A record showing the location of a device establishes the location of that device. It "
    "does not by itself establish the location of any person."
)

CLAIM_1 = "The accused was physically present at the scene."
CLAIM_2 = "A witness account of presence must be corroborated by an independent record."

CITATION = "Rao v State of Testland, DEMO-114"


@pytest.fixture
def documents() -> list[SourceDocument]:
    return [
        SourceDocument(
            document_id="DOC-1",
            title="Statement of PW-2",
            document_kind=DocumentKind.WITNESS_STATEMENT,
            pages=[Page(number=1, paragraphs=[Paragraph(number=1, text=STATEMENT_TEXT)])],
        ),
        SourceDocument(
            document_id="DOC-2",
            title="Written submission",
            document_kind=DocumentKind.OTHER,
            pages=[Page(number=1, paragraphs=[Paragraph(number=3, text=SUBMISSION_TEXT)])],
        ),
    ]


@pytest.fixture
def evidence() -> list[EvidenceItem]:
    return [
        EvidenceItem(
            evidence_id="E-1",
            evidence_type=EvidenceType.DIGITAL,
            description=DEVICE_TEXT,
            source=SourceReference(
                document_id="DOC-DEVICE-LOG", page=2, paragraph=4, quote=DEVICE_TEXT
            ),
            item_date="2024-03-11",
        ),
        EvidenceItem(
            evidence_id="E-2",
            evidence_type=EvidenceType.DOCUMENT,
            description=CCTV_TEXT,
            source=SourceReference(document_id="DOC-CCTV", page=1, quote=CCTV_TEXT),
            item_date="2024-03-12",
        ),
    ]


@pytest.fixture
def authorities() -> list[SuppliedAuthority]:
    return [
        SuppliedAuthority(
            authority_id="AUTH-DEVICE",
            source_type=AuthorityType.CASE_LAW,
            title="Rao v State of Testland",
            citation="DEMO-114",
            aliases=[CITATION],
            url="https://example.test/authorities/demo-114",
            passages=[AuthorityPassage(text=AUTH_P1, paragraph="7")],
        )
    ]


# --------------------------------------------------------------------------
# One fake model for all five stages
# --------------------------------------------------------------------------

CASE_CLAIMS = [
    {
        # grounded verbatim in DOC-1 -> comes back VERIFIED
        "claim_id": "C-1",
        "claim_text": CLAIM_1,
        "claim_type": "FACTUAL",
        "speaker": "PW-2",
        "source": {
            "document_id": "DOC-1",
            "page": 1,
            "paragraph": 1,
            "quote": STATEMENT_TEXT,
        },
    },
    {
        # the quote is a paraphrase, not the document's words -> UNVERIFIED,
        # and it must stay that way all the way to the report.
        "claim_id": "C-2",
        "claim_text": CLAIM_2,
        "claim_type": "LEGAL",
        "source": {
            "document_id": "DOC-2",
            "page": 1,
            "paragraph": 3,
            "quote": "a witness account always needs corroboration",
        },
    },
]

EVIDENCE_PAYLOAD = {
    "relationships": [
        {
            "claim_id": "C-1",
            "evidence_id": "E-1",
            "relationship_type": "SUPPORTS",
            "reasoning": "The device record places a handset at the junction in the window described.",
        },
        {
            "claim_id": "C-1",
            "evidence_id": "E-2",
            "relationship_type": "CONTRADICTS",
            "reasoning": "The CCTV review records no person matching the description in the same window.",
        },
    ],
    "conflicts": [
        {
            "conflict_type": "CONTRADICTORY_EVIDENCE",
            "description": (
                "The device record and the CCTV review give inconsistent pictures of the "
                "junction during the same window."
            ),
            "side_a": {"evidence_id": "E-1"},
            "side_b": {"evidence_id": "E-2"},
        }
    ],
    "support_gaps": [
        {
            "claim_id": "C-2",
            "gap_type": "MISSING_EVIDENCE",
            "note": "No item in the supplied evidence bears on this proposition.",
        }
    ],
}

AUTHORITY_PAYLOAD = {
    "relationship": "PARTIALLY_SUPPORTS",
    "uncertain": True,
    "explanation": (
        "The supplied passage addresses what a device record establishes, which is narrower "
        "than the proposition as stated."
    ),
    "cited_passages": [
        {
            "exact_text": "It does not by itself establish the location of any person.",
            "paragraph": "7",
        }
    ],
}

COUNTER_PAYLOAD = {
    "no_contrary_source_found": False,
    "analysis_note": "The supplied corpus was searched for material bearing on the claim.",
    "supporting_evidence": [{"evidence_id": "E-1", "note": "places the device at the junction"}],
    "contrary_evidence": [{"evidence_id": "E-2", "note": "no person matching the description"}],
    "supporting_authority": [],
    "contrary_authority": [
        {
            "authority_id": "AUTH-DEVICE",
            "passage_id": "P1",
            "exact_text": "It does not by itself establish the location of any person.",
        }
    ],
    "counterpoints": [
        {
            "counterpoint_type": "EVIDENCE_LIMITATION",
            "statement": (
                "The device location record establishes the location of the device, and the "
                "CCTV review of the same window records no person matching the description "
                "given for the accused."
            ),
            "basis": [{"kind": "EVIDENCE", "evidence_id": "E-2"}],
        }
    ],
    "unresolved_questions": [],
}


class RoutingLLM:
    """One provider for the whole pipeline.

    It dispatches on the system prompt it is given, which is distinct per
    agent, and records the order in which the stages consulted it. Any stage
    may be made to raise by name.
    """

    ROUTES = {
        CASE_UNDERSTANDING_SYSTEM_PROMPT: StageName.CASE_UNDERSTANDING,
        EVIDENCE_CONFLICT_SYSTEM_PROMPT: StageName.EVIDENCE_CONFLICT,
        AUTHORITY_CITATION_SYSTEM_PROMPT: StageName.AUTHORITY_CITATION,
        COUNTER_ARGUMENT_SYSTEM_PROMPT: StageName.COUNTER_ARGUMENT,
        RISK_REVIEW_REPORT_SYSTEM_PROMPT: StageName.RISK_REVIEW_REPORT,
    }

    def __init__(self, *, raise_in: StageName | None = None, overrides: dict | None = None):
        self.raise_in = raise_in
        self.overrides = overrides or {}
        self.calls: list[StageName] = []
        self.prompts: dict[StageName, list[str]] = {}

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        stage = self.ROUTES.get(system_prompt)
        if stage is None:  # pragma: no cover - a new prompt would be a bug
            raise AssertionError("An unrecognised system prompt reached the fake model.")
        self.calls.append(stage)
        self.prompts.setdefault(stage, []).append(user_prompt)
        if self.raise_in is stage:
            raise RuntimeError(f"{stage.value} model call exploded")
        if stage in self.overrides:
            return json.dumps(self.overrides[stage])
        if stage is StageName.CASE_UNDERSTANDING:
            return json.dumps({"claims": CASE_CLAIMS})
        if stage is StageName.EVIDENCE_CONFLICT:
            return json.dumps(EVIDENCE_PAYLOAD)
        if stage is StageName.AUTHORITY_CITATION:
            return json.dumps(AUTHORITY_PAYLOAD)
        if stage is StageName.COUNTER_ARGUMENT:
            return json.dumps(COUNTER_PAYLOAD)
        return json.dumps({"narrative": None})


class ExplodingAgent:
    """Stands in for an agent whose `run` fails outright, rather than one
    whose model call fails."""

    def __init__(self, exc: Exception):
        self.exc = exc

    def run(self, input_data):  # noqa: ANN001
        raise self.exc


def make_state(documents, evidence, authorities, **kwargs) -> NyayaSahayakState:
    defaults = dict(
        case_id="NS-2026-001",
        documents=documents,
        evidence=evidence,
        authorities=authorities,
        citations_by_claim={"C-2": [CITATION]},
        material_claim_ids=["C-1", "C-2"],
    )
    defaults.update(kwargs)
    return NyayaSahayakState(**defaults)


def run_graph(state: NyayaSahayakState, llm: RoutingLLM, **agent_overrides):
    agents = build_default_agents(llm)
    agents.update(agent_overrides)
    return build_nyaya_graph(**agents).run(state)


@pytest.fixture
def llm() -> RoutingLLM:
    return RoutingLLM()


@pytest.fixture
def finished(documents, evidence, authorities, llm) -> NyayaSahayakState:
    return run_graph(make_state(documents, evidence, authorities), llm)


# ==========================================================================
# 1. All five agents execute, in order
# ==========================================================================


def test_1_all_five_stages_execute_in_the_specified_order(finished, llm):
    assert finished.executed_stages() == list(PIPELINE_ORDER)
    assert [r.outcome for r in finished.stage_log] == [StageOutcome.COMPLETED] * 5

    # And the agents really ran in that order, as witnessed by the model.
    first_call_order = []
    for stage in llm.calls:
        if stage not in first_call_order:
            first_call_order.append(stage)
    assert first_call_order == list(PIPELINE_ORDER)


def test_1b_the_graph_has_exactly_five_nodes_and_no_supervisor(llm):
    graph = build_nyaya_graph(**build_default_agents(llm))
    nodes = set(graph.compiled.get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {stage.value for stage in PIPELINE_ORDER}


def test_1c_every_stage_runs_at_most_once(finished):
    stages = finished.executed_stages()
    assert len(stages) == len(set(stages))


# ==========================================================================
# 2. Structured outputs flow between the agents
# ==========================================================================


def test_2_each_stage_consumes_the_previous_stages_structured_output(finished):
    claim_ids = [c.claim_id for c in finished.case_understanding.claims]
    assert claim_ids == ["C-1", "C-2"]

    # stage 1 -> stage 2: the claim objects themselves
    assert {r.claim_id for r in finished.evidence_conflict.relationships} == {"C-1"}
    assert [g.claim_id for g in finished.evidence_conflict.support_gaps] == ["C-2"]

    # stage 1 -> stage 3: one proposition per claim, carrying the caller's citations
    assert {f.claim_id for f in finished.authority_citation.findings} >= {"C-2"}

    # stage 1 -> stage 4: one target per claim
    assert [f.claim_id for f in finished.counter_argument.findings] == claim_ids

    # stages 1-4 -> stage 5: risk items trace back to those same claims
    reported = {i.claim_id for i in finished.risk_review_report.risk_items}
    # an evidence-vs-evidence conflict belongs to no single claim, hence None
    assert reported - {None} <= set(claim_ids)
    assert finished.risk_review_report.risk_items, "the report saw the upstream findings"


def test_2b_only_the_needed_structure_reaches_each_agent(finished, llm):
    """The counter-analysis stage is handed claims and corpus — not the
    earlier stages' conclusions about them."""
    counter_prompts = "\n".join(llm.prompts[StageName.COUNTER_ARGUMENT])
    assert CLAIM_1 in counter_prompts
    assert DEVICE_TEXT in counter_prompts
    # no conflict or citation verdicts leak in
    assert "CONTRADICTORY_EVIDENCE" not in counter_prompts
    assert "PARTIALLY_SUPPORTS" not in counter_prompts


def test_2c_caller_supplied_citations_reach_the_authority_stage(finished):
    finding = next(f for f in finished.authority_citation.findings if f.claim_id == "C-2")
    assert finding.relationship in {
        CitationRelationship.PARTIALLY_SUPPORTS,
        CitationRelationship.REQUIRES_HUMAN_REVIEW,
    }


def test_2d_report_declares_every_stage_it_was_given(finished):
    stages = {s.stage: s for s in finished.risk_review_report.dashboard.stages}
    assert all(s.present for s in stages.values()), stages


# ==========================================================================
# 3. Provenance is preserved end to end
# ==========================================================================


def test_3_claim_provenance_is_the_same_object_at_every_stage(finished):
    claim = finished.case_understanding.claims[0]
    assert claim.source.document_id == "DOC-1"
    assert claim.source.page == 1
    assert claim.source.paragraph == 1
    assert claim.source.quote == STATEMENT_TEXT

    rel = next(r for r in finished.evidence_conflict.relationships if r.claim_id == "C-1")
    assert rel.claim_source.model_dump() == claim.source.model_dump()

    counter = next(f for f in finished.counter_argument.findings if f.claim_id == "C-1")
    assert counter.claim_source.model_dump() == claim.source.model_dump()


def test_3b_evidence_provenance_survives_into_the_counter_analysis(finished):
    counter = next(f for f in finished.counter_argument.findings if f.claim_id == "C-1")
    contrary = counter.contrary_evidence[0]
    assert contrary.evidence_id == "E-2"
    assert contrary.source.document_id == "DOC-CCTV"
    assert contrary.source.quote == CCTV_TEXT


def test_3c_authority_provenance_is_verbatim_and_locator_bound(finished):
    counter = next(f for f in finished.counter_argument.findings if f.claim_id == "C-1")
    assert counter.contrary_authority, "the supplied authority passage was retrieved"
    provenance = counter.contrary_authority[0].provenance
    assert provenance.source_id == "AUTH-DEVICE"
    assert provenance.exact_text in AUTH_P1
    assert provenance.paragraph == "7"


def test_3d_every_risk_item_traces_risk_to_finding_to_claim_to_source(finished):
    report = finished.risk_review_report
    claim_ids = {c.claim_id for c in finished.case_understanding.claims}
    assert report.risk_items
    for item in report.risk_items:
        assert item.finding_id.strip()                    # Risk -> Finding
        if item.claim_id is not None:
            assert item.claim_id in claim_ids             # Finding -> Claim
        for ref in item.source_references:                # Claim -> Source
            assert ref.source_id is not None
    assert report.validation_failures == []


# ==========================================================================
# 4. Failures never become successful findings
# ==========================================================================


def test_4_a_failing_agent_leaves_no_result_and_is_recorded(documents, evidence, authorities):
    llm = RoutingLLM()
    state = run_graph(
        make_state(documents, evidence, authorities),
        llm,
        evidence_conflict_agent=ExplodingAgent(RuntimeError("evidence store unreachable")),
    )

    assert state.outcome_of(StageName.EVIDENCE_CONFLICT) is StageOutcome.FAILED
    assert state.evidence_conflict is None, "a failed stage is never an empty success"
    assert any("evidence store unreachable" in e for e in state.errors)

    # the pipeline still finishes, and the report says the stage is missing
    assert state.executed_stages() == list(PIPELINE_ORDER)
    stages = {s.stage: s for s in state.risk_review_report.dashboard.stages}
    missing = [name for name, s in stages.items() if not s.present]
    assert missing, "the report must declare the stage it never received"
    assert state.risk_review_report.degraded or state.risk_review_report.warnings


def test_4b_a_failing_model_call_degrades_that_stage_rather_than_inventing(
    documents, evidence, authorities
):
    llm = RoutingLLM(raise_in=StageName.COUNTER_ARGUMENT)
    state = run_graph(make_state(documents, evidence, authorities), llm)

    assert state.outcome_of(StageName.COUNTER_ARGUMENT) is StageOutcome.COMPLETED
    statuses = {f.status for f in state.counter_argument.findings}
    assert statuses == {CounterAnalysisStatus.NOT_ASSESSED}
    assert state.counter_argument.degraded
    for finding in state.counter_argument.findings:
        assert finding.counterpoints == []
        assert finding.requires_human_review is True


def test_4c_a_missing_input_is_skipped_not_faked(evidence, authorities, llm):
    state = run_graph(make_state([], evidence, authorities), llm)

    assert state.outcome_of(StageName.CASE_UNDERSTANDING) is StageOutcome.SKIPPED
    assert state.case_understanding is None
    # nothing downstream invents claims to work on
    for stage in (
        StageName.EVIDENCE_CONFLICT,
        StageName.AUTHORITY_CITATION,
        StageName.COUNTER_ARGUMENT,
    ):
        assert state.outcome_of(stage) is StageOutcome.SKIPPED
    # no model was consulted for any of the four research stages
    assert set(llm.calls) <= {StageName.RISK_REVIEW_REPORT}
    assert state.risk_review_report is not None  # but the report still speaks
    assert state.risk_review_report.risk_items == []


def test_4d_the_report_stage_runs_even_when_everything_before_it_failed(
    documents, evidence, authorities
):
    llm = RoutingLLM()
    agents = {
        name: ExplodingAgent(RuntimeError(f"{name} down"))
        for name in (
            "case_understanding_agent",
            "evidence_conflict_agent",
            "authority_citation_agent",
            "counter_argument_agent",
        )
    }
    state = run_graph(make_state(documents, evidence, authorities), llm, **agents)

    # stage 1 failed; the three stages that needed its claims had nothing to
    # work on and said so, rather than proceeding on invented input.
    assert state.outcome_of(StageName.CASE_UNDERSTANDING) is StageOutcome.FAILED
    assert state.errors == ["case_understanding: RuntimeError: case_understanding_agent down"]
    for stage in (
        StageName.EVIDENCE_CONFLICT,
        StageName.AUTHORITY_CITATION,
        StageName.COUNTER_ARGUMENT,
    ):
        assert state.outcome_of(stage) is StageOutcome.SKIPPED
    assert state.outcome_of(StageName.RISK_REVIEW_REPORT) is StageOutcome.COMPLETED
    assert all(not s.present for s in state.risk_review_report.dashboard.stages)
    # an empty report is not a clean one: it says what it never received
    assert state.risk_review_report.risk_items == []
    absent = [w for w in state.risk_review_report.warnings
              if "not the same as there being none" in w]
    assert len(absent) == 4


def test_4e_an_unverified_claim_is_never_reported_as_verified(finished):
    c2 = next(c for c in finished.case_understanding.claims if c.claim_id == "C-2")
    assert c2.verification_status is VerificationStatus.UNVERIFIED
    # and nothing downstream quietly upgraded it
    assert any(
        i.claim_id == "C-2" for i in finished.risk_review_report.risk_items
    ), "an unverified claim must surface as a risk"


# ==========================================================================
# 5. Human-review-required findings stay review-required
# ==========================================================================


def test_5_review_requirements_survive_to_the_report(finished):
    counter = next(f for f in finished.counter_argument.findings if f.claim_id == "C-1")
    assert counter.status is CounterAnalysisStatus.CONTRARY_MATERIAL_FOUND
    assert counter.requires_human_review is True

    report = finished.risk_review_report
    assert report.review_items, "the report must queue the upstream uncertainty"
    for item in report.review_items:
        assert item.status == "REQUIRES_HUMAN_REVIEW"
        assert item.risk_item_ids and item.finding_ids


def test_5b_the_report_offers_no_way_to_resolve_a_review_item(finished):
    item = finished.risk_review_report.review_items[0]
    fields = type(item).model_fields
    assert "resolution" not in fields
    assert "resolved" not in fields
    with pytest.raises(Exception):
        item.__class__(**{**item.model_dump(), "status": "RESOLVED"})


def test_5c_an_uncorroborated_claim_reaches_high_risk_when_declared_material(finished):
    report = finished.risk_review_report
    levels = {i.risk_level for i in report.risk_items}
    assert RiskLevel.HIGH in levels
    high = [i for i in report.risk_items if i.risk_level is RiskLevel.HIGH]
    assert all(i.requires_review for i in high)
    assert all(i.rules_applied for i in high)


def test_5d_uncertain_citation_relationships_are_preserved_not_resolved(finished):
    finding = next(f for f in finished.authority_citation.findings if f.claim_id == "C-2")
    assert finding.requires_human_review is True
    assert finding.relationship is not CitationRelationship.SUPPORTS


def test_5e_a_support_gap_survives_as_a_review_item(finished):
    gap = finished.evidence_conflict.support_gaps[0]
    assert gap.gap_type is GapType.MISSING_EVIDENCE
    assert any(i.claim_id == "C-2" for i in finished.risk_review_report.risk_items)


# ==========================================================================
# Wiring details
# ==========================================================================


def test_state_round_trips_through_the_graph_as_a_typed_object(finished):
    assert isinstance(finished, NyayaSahayakState)
    assert finished.case_id == "NS-2026-001"
    # inputs are not consumed or mutated by the run
    assert [d.document_id for d in finished.documents] == ["DOC-1", "DOC-2"]
    assert [e.evidence_id for e in finished.evidence] == ["E-1", "E-2"]


def test_run_pipeline_convenience_builds_the_same_graph(documents, evidence, authorities):
    state = run_pipeline(make_state(documents, evidence, authorities), llm=RoutingLLM())
    assert state.executed_stages() == list(PIPELINE_ORDER)


def test_materiality_defaults_to_analysing_every_claim(documents, evidence, authorities, llm):
    state = run_graph(
        make_state(documents, evidence, authorities, material_claim_ids=[]), llm
    )
    assert [f.claim_id for f in state.counter_argument.findings] == ["C-1", "C-2"]
    assert all(f.status is not CounterAnalysisStatus.NOT_ASSESSED
               for f in state.counter_argument.findings)


def test_a_non_material_claim_is_not_analysed_for_counterpoints(
    documents, evidence, authorities, llm
):
    state = run_graph(
        make_state(documents, evidence, authorities, material_claim_ids=["C-1"]), llm
    )
    assert state.counter_argument.skipped_claim_ids == ["C-2"]
    assert [f.claim_id for f in state.counter_argument.findings] == ["C-1"]
    # and a claim that was never analysed produces no counterpoint at all
    assert all(f.claim_id != "C-2" for f in state.counter_argument.findings)


def test_the_run_is_deterministic_for_the_same_inputs(documents, evidence, authorities):
    first = run_graph(make_state(documents, evidence, authorities), RoutingLLM())
    second = run_graph(make_state(documents, evidence, authorities), RoutingLLM())
    assert first.risk_review_report.model_dump() == second.risk_review_report.model_dump()
