"""Unit tests for the CaseUnderstandingAgent.

No network calls, no database, no FastAPI app — the agent is exercised
directly with a fake LLM provider so these tests are fast and deterministic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from agents.case_understanding import (  # noqa: E402
    CaseUnderstandingAgent,
    CaseUnderstandingInput,
    ClaimType,
    DocumentKind,
    Page,
    Paragraph,
    SourceDocument,
    SourceReference,
    TranscriptUtterance,
    VerificationStatus,
)
from agents.case_understanding.validation import check_claim_provenance  # noqa: E402
from agents.case_understanding.schemas import Claim  # noqa: E402


class ScriptedLLM:
    """Returns a fixed string (or raises) regardless of the prompt."""

    def __init__(self, response: str | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        if self.error:
            raise self.error
        return self.response


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def witness_statement() -> SourceDocument:
    return SourceDocument(
        document_id="DOC-1",
        title="Statement of PW-3",
        document_kind=DocumentKind.WITNESS_STATEMENT,
        pages=[
            Page(
                number=1,
                paragraphs=[
                    Paragraph(
                        number=1,
                        text="I was returning home along Riverside Road at about 10:45 PM on 11 August 2026.",
                    ),
                    Paragraph(
                        number=2,
                        text="I saw a person near the Riverside Road junction at that time.",
                    ),
                ],
            )
        ],
    )


@pytest.fixture
def transcript_document() -> SourceDocument:
    return SourceDocument(
        document_id="TR-1",
        title="Hearing 3 transcript",
        document_kind=DocumentKind.HEARING_TRANSCRIPT,
        is_transcript=True,
        utterances=[
            TranscriptUtterance(
                location="Hearing 3, examination-in-chief, line 12",
                speaker="PW-3",
                text="I confirm I signed the statement on 12 August 2026.",
            )
        ],
    )


def make_input(*docs: SourceDocument) -> CaseUnderstandingInput:
    return CaseUnderstandingInput(case_id="NS-2026-001", documents=list(docs))


def llm_returning(claims: list[dict]) -> ScriptedLLM:
    return ScriptedLLM(response=json.dumps({"claims": claims}))


# --------------------------------------------------------------------------
# Schema-level provenance rules
# --------------------------------------------------------------------------


def test_source_reference_rejects_completely_empty_provenance():
    with pytest.raises(ValidationError):
        SourceReference()


def test_source_reference_accepts_document_id_alone():
    ref = SourceReference(document_id="DOC-1")
    assert ref.document_id == "DOC-1"


def test_claim_rejects_blank_claim_text():
    with pytest.raises(ValidationError):
        Claim(
            claim_id="C-1",
            claim_text="   ",
            source=SourceReference(document_id="DOC-1"),
        )


def test_source_document_rejects_empty_document():
    with pytest.raises(ValidationError):
        SourceDocument(document_id="EMPTY", raw_text="   ", pages=[], utterances=[])


def test_case_understanding_input_requires_a_document():
    with pytest.raises(ValidationError):
        CaseUnderstandingInput(case_id="NS-1", documents=[])


# --------------------------------------------------------------------------
# check_claim_provenance
# --------------------------------------------------------------------------


def test_provenance_verified_when_quote_found_at_specified_location(witness_statement):
    docs = {witness_statement.document_id: witness_statement}
    claim = Claim(
        claim_id="C-1",
        claim_text="The witness was on Riverside Road around 10:45 PM on 11 August 2026.",
        claim_type=ClaimType.FACTUAL,
        source=SourceReference(
            document_id="DOC-1",
            page=1,
            paragraph=1,
            quote="I was returning home along Riverside Road at about 10:45 PM on 11 August 2026.",
        ),
    )
    result = check_claim_provenance(claim, docs)
    assert result.status == VerificationStatus.VERIFIED


def test_provenance_unverified_when_quote_not_in_document(witness_statement):
    docs = {witness_statement.document_id: witness_statement}
    claim = Claim(
        claim_id="C-2",
        claim_text="The witness saw a red car.",
        source=SourceReference(document_id="DOC-1", page=1, paragraph=1, quote="I saw a red car speeding away."),
    )
    result = check_claim_provenance(claim, docs)
    assert result.status == VerificationStatus.UNVERIFIED


def test_provenance_unverified_when_quote_right_but_location_wrong(witness_statement):
    docs = {witness_statement.document_id: witness_statement}
    claim = Claim(
        claim_id="C-3",
        claim_text="A person was seen near the junction.",
        source=SourceReference(
            document_id="DOC-1",
            page=1,
            paragraph=1,  # actually paragraph 2
            quote="I saw a person near the Riverside Road junction at that time.",
        ),
    )
    result = check_claim_provenance(claim, docs)
    assert result.status == VerificationStatus.UNVERIFIED
    assert "not at the specified" in result.notes


def test_provenance_unverified_when_document_unknown(witness_statement):
    docs = {witness_statement.document_id: witness_statement}
    claim = Claim(
        claim_id="C-4",
        claim_text="Some claim.",
        source=SourceReference(document_id="DOC-999", quote="anything"),
    )
    result = check_claim_provenance(claim, docs)
    assert result.status == VerificationStatus.UNVERIFIED
    assert "does not match" in result.notes


def test_provenance_unverified_when_no_quote_supplied(witness_statement):
    docs = {witness_statement.document_id: witness_statement}
    claim = Claim(
        claim_id="C-5",
        claim_text="Some claim with only a page reference.",
        source=SourceReference(document_id="DOC-1", page=1),
    )
    result = check_claim_provenance(claim, docs)
    assert result.status == VerificationStatus.UNVERIFIED


def test_provenance_verified_for_transcript_utterance(transcript_document):
    docs = {transcript_document.document_id: transcript_document}
    claim = Claim(
        claim_id="C-6",
        claim_text="PW-3 confirmed signing the statement on 12 August 2026.",
        speaker="PW-3",
        dates=["12 August 2026"],
        source=SourceReference(
            document_id="TR-1",
            transcript_location="Hearing 3, examination-in-chief, line 12",
            quote="I confirm I signed the statement on 12 August 2026.",
        ),
    )
    result = check_claim_provenance(claim, docs)
    assert result.status == VerificationStatus.VERIFIED


# --------------------------------------------------------------------------
# CaseUnderstandingAgent.run — happy path
# --------------------------------------------------------------------------


def test_agent_extracts_and_independently_verifies_claim(witness_statement):
    llm = llm_returning([
        {
            "claim_text": "The witness was on Riverside Road at about 10:45 PM on 11 August 2026.",
            "claim_type": "FACTUAL",
            "dates": ["11 August 2026"],
            "entities": ["Riverside Road"],
            "source": {
                "document_id": "DOC-1",
                "page": 1,
                "paragraph": 1,
                "quote": "I was returning home along Riverside Road at about 10:45 PM on 11 August 2026.",
            },
        }
    ])
    agent = CaseUnderstandingAgent(llm=llm)
    result = agent.run(make_input(witness_statement))

    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.verification_status == VerificationStatus.VERIFIED
    assert claim.claim_type == ClaimType.FACTUAL
    assert result.rejected_claims == []
    assert not result.degraded


def test_agent_ignores_models_self_reported_verification_status(witness_statement):
    """Even if the model claims VERIFIED, the agent recomputes it and a
    fabricated quote must come back UNVERIFIED."""
    llm = llm_returning([
        {
            "claim_text": "The witness saw a masked man with a weapon.",
            "claim_type": "FACTUAL",
            "verification_status": "VERIFIED",  # the model should not be trusted on this
            "source": {
                "document_id": "DOC-1",
                "page": 1,
                "paragraph": 1,
                "quote": "I saw a masked man holding a weapon.",  # not actually in the document
            },
        }
    ])
    agent = CaseUnderstandingAgent(llm=llm)
    result = agent.run(make_input(witness_statement))

    assert len(result.claims) == 1
    assert result.claims[0].verification_status == VerificationStatus.UNVERIFIED


def test_agent_rejects_claim_with_no_provenance_instead_of_discarding_silently(witness_statement):
    llm = llm_returning([
        {"claim_text": "A vague, unsourced assertion.", "source": {}},
        {
            "claim_text": "The witness was on Riverside Road.",
            "source": {"document_id": "DOC-1", "quote": "I was returning home along Riverside Road"},
        },
    ])
    agent = CaseUnderstandingAgent(llm=llm)
    result = agent.run(make_input(witness_statement))

    assert len(result.claims) == 1
    assert len(result.rejected_claims) == 1
    assert "no provenance" in result.rejected_claims[0].reason.lower() or \
        "provenance" in result.rejected_claims[0].reason.lower()
    assert any("rejected" in w.lower() for w in result.warnings)


def test_agent_flags_claim_referencing_unknown_document(witness_statement):
    llm = llm_returning([
        {
            "claim_text": "Something from a document that was not provided.",
            "source": {"document_id": "DOC-999", "quote": "irrelevant"},
        }
    ])
    agent = CaseUnderstandingAgent(llm=llm)
    result = agent.run(make_input(witness_statement))

    assert len(result.claims) == 1
    assert result.claims[0].verification_status == VerificationStatus.UNVERIFIED
    assert any("DOC-999" in w for w in result.warnings)


def test_agent_deduplicates_repeated_claim_ids(witness_statement):
    llm = llm_returning([
        {
            "claim_id": "SAME",
            "claim_text": "First claim.",
            "source": {"document_id": "DOC-1", "quote": "I was returning home"},
        },
        {
            "claim_id": "SAME",
            "claim_text": "Second claim, different text, same id from the model.",
            "source": {"document_id": "DOC-1", "quote": "near the Riverside Road junction"},
        },
    ])
    agent = CaseUnderstandingAgent(llm=llm)
    result = agent.run(make_input(witness_statement))

    ids = [c.claim_id for c in result.claims]
    assert len(ids) == len(set(ids)), "claim_ids must be unique in the output"
    assert any("duplicate" in w.lower() for w in result.warnings)


def test_agent_never_invents_dates_or_entities_left_out_by_model(witness_statement):
    """The agent must not backfill dates/entities on the model's behalf —
    whatever the model omits stays omitted."""
    llm = llm_returning([
        {
            "claim_text": "A person was seen near the junction.",
            "source": {"document_id": "DOC-1", "page": 1, "paragraph": 2,
                       "quote": "I saw a person near the Riverside Road junction at that time."},
        }
    ])
    agent = CaseUnderstandingAgent(llm=llm)
    result = agent.run(make_input(witness_statement))

    assert result.claims[0].dates == []
    assert result.claims[0].entities == []


# --------------------------------------------------------------------------
# CaseUnderstandingAgent.run — degraded / failure paths
# --------------------------------------------------------------------------


def test_agent_handles_llm_failure_without_raising(witness_statement):
    llm = ScriptedLLM(error=RuntimeError("provider timed out"))
    agent = CaseUnderstandingAgent(llm=llm)
    result = agent.run(make_input(witness_statement))

    assert result.claims == []
    assert result.degraded is True
    assert any("provider timed out" in w for w in result.warnings)


def test_agent_handles_malformed_json_without_raising(witness_statement):
    llm = ScriptedLLM(response="not json at all {{{")
    agent = CaseUnderstandingAgent(llm=llm)
    result = agent.run(make_input(witness_statement))

    assert result.claims == []
    assert result.degraded is True


def test_agent_strips_markdown_code_fences(witness_statement):
    payload = json.dumps({"claims": [
        {
            "claim_text": "The witness was on Riverside Road.",
            "source": {"document_id": "DOC-1", "quote": "I was returning home along Riverside Road"},
        }
    ]})
    llm = ScriptedLLM(response=f"```json\n{payload}\n```")
    agent = CaseUnderstandingAgent(llm=llm)
    result = agent.run(make_input(witness_statement))

    assert len(result.claims) == 1
    assert result.claims[0].verification_status == VerificationStatus.VERIFIED


def test_agent_rejects_non_object_claim_entries(witness_statement):
    llm = ScriptedLLM(response=json.dumps({"claims": ["just a string, not an object"]}))
    agent = CaseUnderstandingAgent(llm=llm)
    result = agent.run(make_input(witness_statement))

    assert result.claims == []
    assert len(result.rejected_claims) == 1


# --------------------------------------------------------------------------
# System prompt sanity checks
# --------------------------------------------------------------------------


def test_system_prompt_contains_required_framing_sentence():
    from agents.case_understanding.prompts import CASE_UNDERSTANDING_SYSTEM_PROMPT

    assert (
        "You are a source-grounded legal case understanding agent. You may only use "
        "information contained in the supplied case material or returned by approved "
        "tools. Your job is to extract and structure claims, not to decide the case."
        in CASE_UNDERSTANDING_SYSTEM_PROMPT
    )


def test_system_prompt_forbids_legal_decision_making():
    from agents.case_understanding.prompts import CASE_UNDERSTANDING_SYSTEM_PROMPT

    lowered = CASE_UNDERSTANDING_SYSTEM_PROMPT.lower()
    for forbidden in ["guilt", "credibility", "liability", "admissibility"]:
        assert forbidden in lowered
