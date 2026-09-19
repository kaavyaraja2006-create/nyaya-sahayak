"""The integration test the architecture review asked for:

    document
      -> LangGraph
      -> 5 agents
      -> validated outputs
      -> MongoDB persistence
      -> Review items
      -> AnalysisRun completion

It runs the real graph from `agents.graph` with a scripted model, then checks
what actually landed in the repositories.
"""
from __future__ import annotations

import pytest

from backend.app.agents_bridge import build_state, evidence_from_documents, persist_pipeline_output
from backend.app.agents_bridge.citations import extract_citation_texts
from backend.app.agents_bridge.pipeline import run_graph
from backend.app.models.authority import Authority, CitationRelationship
from backend.app.models.case import Case, User
from backend.app.models.document import Document
from backend.app.repositories import (
    analysis_run_repository,
    authority_repository,
    case_repository,
    citation_repository,
    claim_repository,
    document_repository,
    evidence_repository,
    relationship_repository,
    review_repository,
    risk_item_repository,
    user_repository,
)
from backend.app.services import analysis_service
from tests.fake_llm import FailingLLM, ScriptedLLM, build_script

CLAIM_TEXT = (
    "The limitation period is governed by Section 12 of the Limitation Act, 1963."
)
PARAGRAPH_TEXT = (
    "The plaintiff filed the suit on 3 March 2026. "
    + CLAIM_TEXT
)


@pytest.fixture()
def seeded_case():
    user = User(email="reviewer@example.com", full_name="Test Reviewer")
    user_repository.create(user)

    case = Case(case_id="NS-2026-001", name="Limitation dispute", user_id=user.id)
    case_repository.create(case)

    document = Document(
        document_id="DOC-001",
        case_id=case.id,
        filename="plaint.txt",
        document_type="Legal Draft",
        page_count=1,
        extracted_text=PARAGRAPH_TEXT,
        pages_json=[{"page": 1, "paragraphs": [{"n": 1, "text": PARAGRAPH_TEXT}]}],
        status="ready",
    )
    document_repository.create(document)
    return user, case, document


def _script():
    return build_script(
        claim_text=CLAIM_TEXT,
        document_id="DOC-001",
        page=1,
        paragraph=1,
        quote=CLAIM_TEXT,
        evidence_id="E-001",
    )


def test_document_to_mongodb_via_five_agents(seeded_case):
    user, case, document = seeded_case

    evidence = evidence_from_documents([document])
    for item in evidence:
        evidence_repository.create(item)

    state = build_state(
        case_public_id=case.case_id,
        documents=[document],
        evidence=evidence,
        authorities=[],
    )
    assert state.documents[0].pages[0].paragraphs[0].text == PARAGRAPH_TEXT

    final_state = run_graph(state, llm=ScriptedLLM(_script()))

    # All five stages ran, in order.
    stages = [record.stage.value for record in final_state.stage_log]
    assert stages == [
        "CASE_UNDERSTANDING",
        "EVIDENCE_CONFLICT",
        "AUTHORITY_CITATION",
        "COUNTER_ARGUMENT",
        "RISK_REVIEW_REPORT",
    ]
    assert not final_state.errors

    summary = persist_pipeline_output(
        final_state, case_row_id=case.id, run_id="RUN-1", actor="Test Reviewer"
    )

    # Validated agent output reached MongoDB.
    claims = claim_repository.list_by_case(case.id)
    assert [c.claim_id for c in claims] == ["CU-001"]
    assert claims[0].source_reference.source_document_id == "DOC-001"
    assert claims[0].source_reference.paragraph == 1

    relationships = relationship_repository.list_by_case(case.id)
    assert [r.relationship for r in relationships] == ["MENTIONS"]

    # The citation the backend extracted was verified by the agent, and the
    # verification vocabulary survived persistence intact.
    citations = citation_repository.list_by_case(case.id)
    assert citations, "the legal proposition should have produced a citation finding"
    assert all(
        c.relationship in {r.value for r in CitationRelationship} for c in citations
    )
    assert all(c.requires_human_review for c in citations)
    assert summary["counts"]["citations"] == len(citations)


def test_citation_finding_keeps_source_provenance():
    """A supplied authority's exact text survives the round trip to MongoDB."""
    authority = Authority(
        authority_id="AUTH-001",
        title="Limitation Act, 1963",
        citation="Section 12 of the Limitation Act, 1963",
        source_type="statute",
        passage=(
            "In computing the period of limitation for any suit, the day from "
            "which such period is to be reckoned shall be excluded."
        ),
        paragraph=12,
    )
    authority_repository.create(authority)

    from backend.app.agents_bridge.inputs import to_supplied_authority

    supplied = to_supplied_authority(authority)
    assert supplied.text == authority.passage
    assert supplied.passages[0].paragraph == "12"
    assert supplied.citation == authority.citation


def test_backend_extracts_citations_the_agents_do_not():
    found = extract_citation_texts(CLAIM_TEXT)
    assert any("Section 12" in citation for citation in found)


def test_run_completes_and_raises_review_items(seeded_case):
    """start_run + execute_run leave a completed AnalysisRun behind."""
    user, case, document = seeded_case

    import backend.app.agents_bridge.pipeline as pipeline_module

    scripted = ScriptedLLM(_script())
    original = pipeline_module.build_graph
    pipeline_module.build_graph = lambda llm=None, **kw: original(scripted, **kw)
    try:
        run = analysis_service.start_run(case, user.full_name, {})
        assert run.status == "running"

        analysis_service.execute_run(run.id, case.id, user.full_name)
    finally:
        pipeline_module.build_graph = original

    stored = analysis_run_repository.get_latest_by_case(case.id)
    assert stored is not None
    assert stored.status == "completed"
    assert stored.progress == 100
    assert stored.summary_json["counts"]["claims"] == 1

    # Every review item raised by the pipeline is stored against a generic
    # (finding_type, finding_id) pair and is still awaiting a human.
    reviews = review_repository.list_by_case(case.id)
    for review in reviews:
        assert review.decision == "NEEDS_REVIEW"
        assert review.finding_id
        assert review.source == "agent"

    risks = risk_item_repository.list_by_case(case.id)
    assert len(risks) >= len(reviews)


def test_provider_failure_is_reported_not_hidden(seeded_case):
    """A dead model must not produce a clean-looking completed run."""
    user, case, document = seeded_case

    evidence = evidence_from_documents([document])
    state = build_state(
        case_public_id=case.case_id,
        documents=[document],
        evidence=evidence,
        authorities=[],
    )
    final_state = run_graph(state, llm=FailingLLM())
    summary = persist_pipeline_output(
        final_state, case_row_id=case.id, run_id="RUN-2", actor="Test Reviewer"
    )

    assert summary["degraded"] is True
    assert summary["counts"]["claims"] == 0
    assert summary["warnings"], "a failed provider must leave a warning trail"
