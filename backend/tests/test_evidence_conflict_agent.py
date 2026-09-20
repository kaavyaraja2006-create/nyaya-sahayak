"""Unit tests for the EvidenceConflictAgent.

No network calls, no database — the agent is exercised directly with a fake
LLM provider so these tests are fast and deterministic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from agents.case_understanding.schemas import Claim, ClaimType, SourceReference  # noqa: E402
from agents.evidence_conflict import (  # noqa: E402
    Conflict,
    ConflictSide,
    EvidenceConflictAgent,
    EvidenceConflictInput,
    EvidenceItem,
    EvidenceType,
    GapType,
    RelationshipType,
    SupportGap,
)


class ScriptedLLM:
    def __init__(self, response: str | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        if self.error:
            raise self.error
        return self.response


def llm_returning(payload: dict) -> ScriptedLLM:
    return ScriptedLLM(response=json.dumps(payload))


# --------------------------------------------------------------------------
# Fixtures: two witness claims (a genuine location inconsistency) plus
# supporting/unrelated evidence.
# --------------------------------------------------------------------------


@pytest.fixture
def claim_a() -> Claim:
    return Claim(
        claim_id="C-1",
        claim_text="The accused was at the Riverside Road junction at 10:45 PM.",
        claim_type=ClaimType.FACTUAL,
        speaker="Witness A",
        source=SourceReference(document_id="DOC-1", page=1, paragraph=1, quote="saw the accused at the junction"),
    )


@pytest.fixture
def claim_b() -> Claim:
    return Claim(
        claim_id="C-2",
        claim_text="The accused was at the railway station at 10:45 PM.",
        claim_type=ClaimType.FACTUAL,
        speaker="Witness B",
        source=SourceReference(document_id="DOC-2", page=1, paragraph=1, quote="saw the accused at the station"),
    )


@pytest.fixture
def claim_c() -> Claim:
    return Claim(
        claim_id="C-3",
        claim_text="The accused was wearing a blue jacket.",
        claim_type=ClaimType.FACTUAL,
        source=SourceReference(document_id="DOC-1", page=1, paragraph=2, quote="wearing a blue jacket"),
    )


@pytest.fixture
def cctv_evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="E-1",
        evidence_type=EvidenceType.DIGITAL,
        description="CCTV footage timestamped 10:45 PM shows a figure at the Riverside Road junction.",
        source=SourceReference(document_id="DOC-3", page=1, quote="10:45 PM, Riverside Road junction, single figure visible"),
        item_date="2026-08-11",
    )


def make_input(claims: list[Claim], evidence: list[EvidenceItem]) -> EvidenceConflictInput:
    return EvidenceConflictInput(case_id="NS-2026-001", claims=claims, evidence=evidence)


# --------------------------------------------------------------------------
# 1. Supporting evidence
# --------------------------------------------------------------------------


def test_supporting_evidence_relationship(claim_a, cctv_evidence):
    llm = llm_returning({
        "relationships": [
            {"claim_id": "C-1", "evidence_id": "E-1", "relationship_type": "SUPPORTS",
             "reasoning": "CCTV places a figure at the junction at the same time the claim describes."}
        ],
        "conflicts": [],
        "support_gaps": [],
    })
    agent = EvidenceConflictAgent(llm=llm)
    result = agent.run(make_input([claim_a], [cctv_evidence]))

    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.relationship_type == RelationshipType.SUPPORTS
    assert rel.claim_source.document_id == "DOC-1"
    assert rel.evidence_source.document_id == "DOC-3"
    assert result.rejected_findings == []
    assert not result.degraded


# --------------------------------------------------------------------------
# 2. Conflicting witness statements
# --------------------------------------------------------------------------


def test_conflicting_witness_statements_are_detected_not_resolved(claim_a, claim_b):
    llm = llm_returning({
        "relationships": [],
        "conflicts": [
            {
                "conflict_type": "INCONSISTENT_STATEMENTS",
                "description": "Witness A and Witness B provide inconsistent accounts regarding the accused's location at 10:45 PM.",
                "side_a": {"claim_id": "C-1"},
                "side_b": {"claim_id": "C-2"},
            }
        ],
        "support_gaps": [],
    })
    agent = EvidenceConflictAgent(llm=llm)
    result = agent.run(make_input([claim_a, claim_b], []))

    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.result == "CONFLICT_DETECTED"
    assert conflict.side_a.claim_id == "C-1"
    assert conflict.side_b.claim_id == "C-2"
    # both original sources are preserved
    assert conflict.side_a.source.document_id == "DOC-1"
    assert conflict.side_b.source.document_id == "DOC-2"
    # never a resolution verdict
    assert "lying" not in conflict.description.lower()


def test_conflict_cannot_be_phrased_as_a_credibility_verdict(claim_a, claim_b):
    """The schema itself refuses to construct a conflict with verdict language."""
    with pytest.raises(ValidationError):
        Conflict(
            conflict_id="CNF-1",
            conflict_type="INCONSISTENT_STATEMENTS",
            description="Witness A is lying about the accused's location.",
            side_a=ConflictSide(claim_id="C-1", source=claim_a.source),
            side_b=ConflictSide(claim_id="C-2", source=claim_b.source),
        )


# --------------------------------------------------------------------------
# 3. Missing evidence
# --------------------------------------------------------------------------


def test_missing_evidence_is_reported_as_insufficient_evidence(claim_c):
    llm = llm_returning({
        "relationships": [],
        "conflicts": [],
        "support_gaps": [
            {
                "claim_id": "C-3",
                "gap_type": "MISSING_EVIDENCE",
                "related_evidence_ids": [],
                "note": "No evidence in the supplied material addresses the accused's clothing.",
            }
        ],
    })
    agent = EvidenceConflictAgent(llm=llm)
    result = agent.run(make_input([claim_c], []))

    assert len(result.support_gaps) == 1
    gap = result.support_gaps[0]
    assert gap.result == "INSUFFICIENT_EVIDENCE"
    assert gap.gap_type == GapType.MISSING_EVIDENCE
    assert gap.related_evidence_ids == []
    assert gap.claim_source.document_id == "DOC-1"


# --------------------------------------------------------------------------
# 4. Insufficient support
# --------------------------------------------------------------------------


def test_insufficient_support_lists_the_partial_evidence(claim_a, cctv_evidence):
    llm = llm_returning({
        "relationships": [],
        "conflicts": [],
        "support_gaps": [
            {
                "claim_id": "C-1",
                "gap_type": "INSUFFICIENT_SUPPORT",
                "related_evidence_ids": ["E-1"],
                "note": "CCTV shows a figure at the junction but does not identify the accused specifically.",
            }
        ],
    })
    agent = EvidenceConflictAgent(llm=llm)
    result = agent.run(make_input([claim_a], [cctv_evidence]))

    assert len(result.support_gaps) == 1
    gap = result.support_gaps[0]
    assert gap.result == "INSUFFICIENT_EVIDENCE"
    assert gap.gap_type == GapType.INSUFFICIENT_SUPPORT
    assert gap.related_evidence_ids == ["E-1"]


def test_missing_evidence_gap_rejects_nonempty_related_ids():
    with pytest.raises(ValidationError):
        SupportGap(
            gap_id="GAP-1",
            claim_id="C-1",
            claim_source=SourceReference(document_id="DOC-1"),
            gap_type=GapType.MISSING_EVIDENCE,
            related_evidence_ids=["E-1"],
            note="Should not be allowed.",
        )


# --------------------------------------------------------------------------
# 5. Hallucinated evidence
# --------------------------------------------------------------------------


def test_relationship_referencing_unknown_evidence_is_rejected_not_fabricated(claim_a, cctv_evidence):
    llm = llm_returning({
        "relationships": [
            {"claim_id": "C-1", "evidence_id": "E-999-DOES-NOT-EXIST", "relationship_type": "SUPPORTS",
             "reasoning": "Fabricated reference."}
        ],
        "conflicts": [],
        "support_gaps": [],
    })
    agent = EvidenceConflictAgent(llm=llm)
    result = agent.run(make_input([claim_a], [cctv_evidence]))

    assert result.relationships == []
    assert len(result.rejected_findings) == 1
    rejected = result.rejected_findings[0]
    assert rejected.kind == "relationship"
    assert "E-999-DOES-NOT-EXIST" in rejected.reason
    assert any("rejected" in w.lower() for w in result.warnings)


def test_conflict_referencing_unknown_claim_is_rejected(claim_a):
    llm = llm_returning({
        "relationships": [],
        "conflicts": [
            {
                "conflict_type": "INCONSISTENT_STATEMENTS",
                "description": "A fabricated conflict.",
                "side_a": {"claim_id": "C-1"},
                "side_b": {"claim_id": "C-DOES-NOT-EXIST"},
            }
        ],
        "support_gaps": [],
    })
    agent = EvidenceConflictAgent(llm=llm)
    result = agent.run(make_input([claim_a], []))

    assert result.conflicts == []
    assert len(result.rejected_findings) == 1
    assert result.rejected_findings[0].kind == "conflict"


def test_support_gap_referencing_unknown_evidence_is_rejected(claim_a):
    llm = llm_returning({
        "relationships": [],
        "conflicts": [],
        "support_gaps": [
            {
                "claim_id": "C-1",
                "gap_type": "INSUFFICIENT_SUPPORT",
                "related_evidence_ids": ["E-GHOST"],
                "note": "References evidence that was never supplied.",
            }
        ],
    })
    agent = EvidenceConflictAgent(llm=llm)
    result = agent.run(make_input([claim_a], []))

    assert result.support_gaps == []
    assert len(result.rejected_findings) == 1
    assert "E-GHOST" in result.rejected_findings[0].reason


# --------------------------------------------------------------------------
# 6. Provenance failure (structurally invalid / missing required references)
# --------------------------------------------------------------------------


def test_conflict_with_only_one_side_is_rejected(claim_a):
    llm = llm_returning({
        "relationships": [],
        "conflicts": [
            {
                "conflict_type": "INCONSISTENT_STATEMENTS",
                "description": "Only one side supplied.",
                "side_a": {"claim_id": "C-1"},
                # side_b deliberately omitted
            }
        ],
        "support_gaps": [],
    })
    agent = EvidenceConflictAgent(llm=llm)
    result = agent.run(make_input([claim_a], []))

    assert result.conflicts == []
    assert len(result.rejected_findings) == 1
    assert result.rejected_findings[0].kind == "conflict"


def test_conflict_with_identical_sides_is_rejected():
    with pytest.raises(ValidationError):
        Conflict(
            conflict_id="CNF-1",
            conflict_type="INCONSISTENT_STATEMENTS",
            description="Same source cited on both sides.",
            side_a=ConflictSide(claim_id="C-1", source=SourceReference(document_id="DOC-1")),
            side_b=ConflictSide(claim_id="C-1", source=SourceReference(document_id="DOC-1")),
        )


def test_conflict_side_with_no_id_at_all_is_rejected():
    with pytest.raises(ValidationError):
        ConflictSide(source=SourceReference(document_id="DOC-1"))


def test_relationship_with_missing_reasoning_is_rejected(claim_a, cctv_evidence):
    llm = llm_returning({
        "relationships": [
            {"claim_id": "C-1", "evidence_id": "E-1", "relationship_type": "SUPPORTS", "reasoning": ""}
        ],
        "conflicts": [],
        "support_gaps": [],
    })
    agent = EvidenceConflictAgent(llm=llm)
    result = agent.run(make_input([claim_a], [cctv_evidence]))

    assert result.relationships == []
    assert len(result.rejected_findings) == 1
    assert result.rejected_findings[0].kind == "relationship"


def test_evidence_item_requires_a_source():
    with pytest.raises(ValidationError):
        EvidenceItem(evidence_id="E-1", description="Some evidence with no provenance at all.", source=None)


# --------------------------------------------------------------------------
# Additional behaviour: input validation, degraded paths, neutrality guard
# --------------------------------------------------------------------------


def test_input_requires_at_least_one_claim():
    with pytest.raises(ValidationError):
        EvidenceConflictInput(case_id="NS-1", claims=[], evidence=[])


def test_agent_handles_llm_failure_without_raising(claim_a):
    llm = ScriptedLLM(error=RuntimeError("provider timed out"))
    agent = EvidenceConflictAgent(llm=llm)
    result = agent.run(make_input([claim_a], []))

    assert result.relationships == result.conflicts == result.support_gaps == []
    assert result.degraded is True
    assert any("provider timed out" in w for w in result.warnings)


def test_agent_handles_malformed_json_without_raising(claim_a):
    llm = ScriptedLLM(response="not json {{{")
    agent = EvidenceConflictAgent(llm=llm)
    result = agent.run(make_input([claim_a], []))

    assert result.degraded is True
    assert result.relationships == []


def test_agent_strips_markdown_code_fences(claim_a, cctv_evidence):
    payload = json.dumps({
        "relationships": [
            {"claim_id": "C-1", "evidence_id": "E-1", "relationship_type": "SUPPORTS", "reasoning": "Times align."}
        ],
        "conflicts": [], "support_gaps": [],
    })
    llm = ScriptedLLM(response=f"```json\n{payload}\n```")
    agent = EvidenceConflictAgent(llm=llm)
    result = agent.run(make_input([claim_a], [cctv_evidence]))

    assert len(result.relationships) == 1


def test_relationship_reasoning_cannot_smuggle_a_credibility_verdict(claim_a, cctv_evidence):
    llm = llm_returning({
        "relationships": [
            {"claim_id": "C-1", "evidence_id": "E-1", "relationship_type": "CONTRADICTS",
             "reasoning": "This shows Witness A is lying."}
        ],
        "conflicts": [], "support_gaps": [],
    })
    agent = EvidenceConflictAgent(llm=llm)
    result = agent.run(make_input([claim_a], [cctv_evidence]))

    assert result.relationships == []
    assert len(result.rejected_findings) == 1


# --------------------------------------------------------------------------
# System prompt sanity checks
# --------------------------------------------------------------------------


def test_system_prompt_contains_required_framing_sentence():
    from agents.evidence_conflict.prompts import EVIDENCE_CONFLICT_SYSTEM_PROMPT

    assert (
        "You are identifying relationships and inconsistencies between sources, "
        "not deciding which source is true." in EVIDENCE_CONFLICT_SYSTEM_PROMPT
    )


def test_system_prompt_contains_witness_example_and_forbids_verdicts():
    from agents.evidence_conflict.prompts import EVIDENCE_CONFLICT_SYSTEM_PROMPT

    assert "Witness A is lying" in EVIDENCE_CONFLICT_SYSTEM_PROMPT
    assert "inconsistent accounts" in EVIDENCE_CONFLICT_SYSTEM_PROMPT
    lowered = EVIDENCE_CONFLICT_SYSTEM_PROMPT.lower()
    for forbidden in ["guilt", "credibility", "liability", "admissibility"]:
        assert forbidden in lowered
