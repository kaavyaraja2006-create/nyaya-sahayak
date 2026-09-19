"""Deterministic citation extraction — the caller's job, not an agent's.

The five agents never extract citations from case material; the graph's
`citations_by_claim` is supplied by whoever runs it, and a claim with no entry
is reported as uncited. That mapping is keyed by claim_id, and claim_ids only
exist once the CaseUnderstandingAgent has run, so the backend supplies it at
the one point where both are available: just before the AuthorityCitationAgent
is called, through `CitationSupplyingAuthorityAgent` below.

The wrapper adds no reasoning and no model call. It runs regexes over the
claim text the agent already produced, attaches whatever citation strings it
literally finds, and hands the real agent its normal input. The agent's own
identity check and provenance rules then apply unchanged — the wrapper can
never make an unverifiable citation look verified.
"""
from __future__ import annotations

import re

from agents.authority_citation.agent import AuthorityCitationAgent
from agents.authority_citation.schemas import (
    AuthorityCitationInput,
    AuthorityCitationResult,
    CitedAuthority,
    LegalProposition,
)

# Reserved words that must never be swallowed into a party name — reporter
# abbreviations and the section/article/rule keywords other patterns own.
_RESERVED = (
    r"(?:AIR|ILR|SCR|SCC|SCALE|BomLR|CriLJ|Section|Sections|Sec|Secs"
    r"|Article|Articles|Art|Arts|Rule|Rules|Regulation|Regulations|Reg|Regs)"
)
_NAME_WORD = rf"(?!{_RESERVED}\b)[A-Z][\w.&'’\-]*"
# A party name: a capitalised word, optionally followed by more capitalised
# words or short lowercase connectors ("of", "the", "and", ...), stopping
# before it would swallow a reporter/section/article/rule token.
_NAME = rf"{_NAME_WORD}(?:\s+(?:{_NAME_WORD}|of|the|and|&|de|van|der))*"

# Case name with an optional inline reporter citation: "Kesavananda Bharati
# v. State of Kerala (1973) 4 SCC 225".
_CASE_NAME_RE = re.compile(
    rf"\b({_NAME})\s+(?:v\.?|vs\.?|versus)\s+({_NAME})"
    r"(\s*[\(\[]?\d{4}[\)\]]?\s+\d+\s+[A-Z][A-Za-z.]*\s+\d+)?",
)

# Reporter citation standing on its own: "AIR 1973 SC 1461", "(1973) 4 SCC 225".
# Two distinct shapes (year-first for AIR/ILR-style, volume-first for
# SCC-style) — each fully bounded so the match can never run on into
# unrelated following text.
_REPORTER_RE = re.compile(
    r"\b(?:AIR|ILR|SCR|SCC|SCALE|BomLR|CriLJ)\b\s+\d{4}\s+[A-Z]{1,6}\s+\d+"
    r"|[\(\[]\d{4}[\)\]]\s+\d+\s+[A-Z][A-Za-z.]{1,10}\s+\d+",
)

# "Section 12 of the Limitation Act, 1963" / "s. 12 of the CPC".
_SECTION_RE = re.compile(
    r"\b(?:Sections?|Secs?\.?|S\.)\s*\d+[A-Za-z]?"
    r"(?:\s*(?:\(\d+\)|\([a-z]\)))*"
    r"(?:\s+of\s+the\s+[A-Z][\w.,'’\- ]{2,60}?(?:Act|Code|Ordinance|Rules)"
    r"(?:,\s*\d{4})?)?",
)

# "Article 21 of the Constitution of India".
_ARTICLE_RE = re.compile(
    r"\b(?:Articles?|Arts?\.)\s*\d+[A-Za-z]?"
    r"(?:\s+of\s+the\s+Constitution(?:\s+of\s+[A-Z][\w]+)?)?",
)

# "Rule 7 of the ... Rules, 2016" / "Regulation 4".
_RULE_RE = re.compile(
    r"\b(?:Rules?|Regulations?|Regs?\.)\s*\d+[A-Za-z]?"
    r"(?:\s+of\s+the\s+[A-Z][\w.,'’\- ]{2,60}?(?:Rules|Regulations)(?:,\s*\d{4})?)?",
)

_PATTERNS = (_CASE_NAME_RE, _REPORTER_RE, _SECTION_RE, _ARTICLE_RE, _RULE_RE)

_MAX_CITATIONS_PER_CLAIM = 12

# Words a match can start with but that are never part of the citation
# itself — "As held in Kesavananda..." should extract the case name, not
# "In Kesavananda...".
_LEADING_STOPWORDS = {"in", "as", "see", "held", "the", "this", "whereas", "also", "per", "vide"}


def _strip_leading_stopwords(value: str) -> str:
    words = value.split()
    while words and words[0].lower() in _LEADING_STOPWORDS:
        words.pop(0)
    return " ".join(words)


def extract_citation_texts(text: str) -> list[str]:
    """Return citation strings that literally appear in `text`, in order.

    Overlapping matches are collapsed to the longest span so that a case name
    and its reporter citation are reported once, not twice.
    """
    if not text or not text.strip():
        return []

    spans: list[tuple[int, int]] = []
    for pattern in _PATTERNS:
        for match in pattern.finditer(text):
            if match.group(0).strip():
                spans.append((match.start(), match.end()))

    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept: list[tuple[int, int]] = []
    for start, end in spans:
        if kept and start < kept[-1][1]:
            # Overlaps the previous span: keep whichever is longer.
            if (end - start) > (kept[-1][1] - kept[-1][0]):
                kept[-1] = (start, end)
            continue
        kept.append((start, end))

    out: list[str] = []
    seen: set[str] = set()
    for start, end in kept:
        value = _strip_leading_stopwords(text[start:end].strip(" .,;:"))
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
        if len(out) >= _MAX_CITATIONS_PER_CLAIM:
            break
    return out


def citations_for_claims(claims) -> dict[str, list[str]]:
    """claim_id -> citation strings found in that claim's own text."""
    mapping: dict[str, list[str]] = {}
    for claim in claims:
        found = extract_citation_texts(getattr(claim, "claim_text", "") or "")
        if found:
            mapping[claim.claim_id] = found
    return mapping


class CitationSupplyingAuthorityAgent:
    """Wraps the real AuthorityCitationAgent, filling in `citations` for any
    proposition the caller left uncited.

    It satisfies the same interface the graph node uses (`run(input) ->
    AuthorityCitationResult`), so `build_nyaya_graph` wires it in place of the
    bare agent without the graph or the agents package changing at all.
    """

    def __init__(self, inner: AuthorityCitationAgent) -> None:
        self._inner = inner
        self.last_extracted: dict[str, list[str]] = {}

    def run(self, input_data: AuthorityCitationInput) -> AuthorityCitationResult:
        propositions: list[LegalProposition] = []
        extracted: dict[str, list[str]] = {}

        for proposition in input_data.propositions:
            if proposition.citations:
                propositions.append(proposition)
                continue
            found = extract_citation_texts(proposition.claim_text)
            if not found:
                propositions.append(proposition)
                continue
            extracted[proposition.claim_id] = found
            propositions.append(
                proposition.model_copy(
                    update={"citations": [CitedAuthority(citation_text=c) for c in found]}
                )
            )

        self.last_extracted = extracted
        return self._inner.run(
            AuthorityCitationInput(
                case_id=input_data.case_id,
                propositions=propositions,
                authorities=list(input_data.authorities),
            )
        )
