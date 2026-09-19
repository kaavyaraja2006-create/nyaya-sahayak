"""A scripted LLM provider for the pipeline tests.

Responses are keyed by the agents' own system-prompt constants, so each agent
gets exactly the output the test wrote for it. The agents, their validators
and the graph are all real; only the model call is replaced.
"""
from __future__ import annotations

import json

from agents.authority_citation.prompts import AUTHORITY_CITATION_SYSTEM_PROMPT
from agents.case_understanding.prompts import CASE_UNDERSTANDING_SYSTEM_PROMPT
from agents.counter_argument.prompts import COUNTER_ARGUMENT_SYSTEM_PROMPT
from agents.evidence_conflict.prompts import EVIDENCE_CONFLICT_SYSTEM_PROMPT
from agents.risk_review_report.prompts import RISK_REVIEW_REPORT_SYSTEM_PROMPT


class ScriptedLLM:
    """Returns a canned response per agent; records every call."""

    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.responses.get(system_prompt, "[]")


class FailingLLM:
    """Every call fails. Used to prove a dead provider yields a degraded run
    with warnings rather than an empty run reported as clean."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        raise RuntimeError("provider unavailable")


def build_script(
    *,
    claim_text: str,
    document_id: str,
    page: int,
    paragraph: int,
    quote: str,
    evidence_id: str,
) -> dict[str, str]:
    """One legal claim quoted verbatim from the document, and one MENTIONS
    relationship to the evidence item derived from that same document."""
    claims = [
        {
            "claim_id": "CU-001",
            "claim_text": claim_text,
            "claim_type": "LEGAL",
            "source": {
                "document_id": document_id,
                "page": page,
                "paragraph": paragraph,
                "quote": quote,
            },
        }
    ]
    evidence_conflict = {
        "relationships": [
            {
                "relationship_id": "R-001",
                "claim_id": "CU-001",
                "evidence_id": evidence_id,
                "relationship_type": "MENTIONS",
                "reasoning": "The evidence item is the document this claim was taken from.",
                "claim_source": {
                    "document_id": document_id,
                    "page": page,
                    "paragraph": paragraph,
                    "quote": quote,
                },
                "evidence_source": {
                    "document_id": document_id,
                    "page": page,
                    "paragraph": paragraph,
                    "quote": quote,
                },
            }
        ],
        "conflicts": [],
        "support_gaps": [],
    }
    return {
        CASE_UNDERSTANDING_SYSTEM_PROMPT: json.dumps(claims),
        EVIDENCE_CONFLICT_SYSTEM_PROMPT: json.dumps(evidence_conflict),
        # No authority text is supplied in the test corpus, so the agent must
        # reach SOURCE_NOT_FOUND on its own; any finding the model tried to
        # assert here would be rejected by its validators.
        AUTHORITY_CITATION_SYSTEM_PROMPT: json.dumps([]),
        COUNTER_ARGUMENT_SYSTEM_PROMPT: json.dumps([]),
        RISK_REVIEW_REPORT_SYSTEM_PROMPT: "Every finding below requires human review.",
    }
