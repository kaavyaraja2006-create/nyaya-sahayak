"""Trust boundary between the model and the finding.

The model is asked for a relationship, an explanation, and the passages it
relied on. It is *never* trusted for provenance. Everything it returns is
re-checked here against the authority text the agent actually supplied:

  * `passage_id` must resolve to a supplied passage;
  * `exact_text` must appear verbatim in that passage (whitespace-collapsed
    comparison only — no case-folding, no quote/dash folding, no fuzzy match);
  * any paragraph/section locator the model volunteers must equal the
    passage's own metadata (so an invented "paragraph 99" is caught);
  * the free-text explanation may not introduce quotations, paragraph/section
    numbers, years, or case names that are not in the supplied material.

If any check fails the whole assessment is rejected (fail closed) and the
agent emits REQUIRES_HUMAN_REVIEW instead. Provenance on an accepted finding
is built from the supplied authority data, never from model output.

The explanation checks are heuristics — defence in depth, not a proof. The
hard guarantees are structural: no model call at all for authorities that
were not found, and no provenance that did not come from supplied text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .citations import normalize_citation
from .schemas import (
    QUOTE_REQUIRED_RELATIONSHIPS,
    AUTO_CLEAR_RELATIONSHIPS,
    AuthorityPassage,
    CitationRelationship,
    SourceProvenance,
    SuppliedAuthority,
)

# Relationships a model may propose. SOURCE_NOT_FOUND is excluded on purpose:
# the model is only called once a source was found.
MODEL_ALLOWED_RELATIONSHIPS = frozenset(CitationRelationship) - {CitationRelationship.SOURCE_NOT_FOUND}

_WS_RE = re.compile(r"\s+")


def normalize_whitespace(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def default_requires_human_review(relationship: CitationRelationship) -> bool:
    """The single place the review-flag policy is applied (see schemas)."""
    return relationship not in AUTO_CLEAR_RELATIONSHIPS


# --------------------------------------------------------------------------
# Quote verification
# --------------------------------------------------------------------------


def verify_quote(quote: str, passage_text: str) -> bool:
    """True only if `quote` is a verbatim span of `passage_text`, ignoring
    differences in whitespace (line breaks, double spaces) and nothing else."""
    q = normalize_whitespace(quote)
    return bool(q) and q in normalize_whitespace(passage_text)


# --------------------------------------------------------------------------
# Explanation grounding
# --------------------------------------------------------------------------

_QUOTED_RE = re.compile(r'"([^"]{4,}?)"|\u201c([^\u201d]{4,}?)\u201d')
_YEAR_RE = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)")
_LOCATOR_RE = re.compile(
    r"(?<![A-Za-z])(?P<kind>paragraphs?|paras?\.?|\u00b6|sections?|secs?\.?|articles?|arts?\.?|clauses?|rules?)"
    r"\s*(?P<num>\d+)",
    re.IGNORECASE,
)
_CASE_NAME_RE = re.compile(
    r"(?P<left>[A-Z][\w'.&-]*)\s+(?i:v|vs|versus)\.?\s+(?P<right>[A-Z][\w'.&-]*)"
)
_SECTION_LIKE_KINDS = ("section", "article", "clause", "rule")


def _locator_family(kind: str) -> str:
    k = kind.lower()
    if k.startswith("para") or k == "\u00b6":
        return "para"
    if k.startswith("sec"):
        return "section"
    if k.startswith("art"):
        return "article"
    if k.startswith("clause"):
        return "clause"
    return "rule"


def _locators_in(text: str) -> set[tuple[str, str]]:
    return {(_locator_family(m.group("kind")), m.group("num")) for m in _LOCATOR_RE.finditer(text)}


def build_grounding_corpus(
    claim_text: str, citation_text: str, authority: SuppliedAuthority, passages: list[AuthorityPassage]
) -> str:
    """Everything the explanation is allowed to refer to."""
    parts = [claim_text, citation_text, authority.title or "", authority.citation or "", *authority.aliases]
    for p in passages:
        parts.extend([p.text, p.paragraph or "", p.section or ""])
    return "\n".join(x for x in parts if x)


def find_ungrounded_references(explanation: str, corpus: str, passages: list[AuthorityPassage]) -> list[str]:
    """Return problems found in `explanation` (empty list = grounded).

    Problem strings are generic on purpose: they never repeat the offending
    text, so a rejected hallucination cannot leak into a finding.
    """
    problems: list[str] = []
    corpus_ws = normalize_whitespace(corpus)

    # 1. Quoted spans must be verbatim excerpts of the claim / supplied text.
    for m in _QUOTED_RE.finditer(explanation):
        span = normalize_whitespace(m.group(1) or m.group(2)).strip(" .,;:")
        if span and span not in corpus_ws:
            problems.append("the explanation quotes words that do not appear in the claim or supplied authority text")
            break

    # 2. Paragraph / section / article / clause numbers must exist in the source.
    allowed = _locators_in(corpus)
    for p in passages:
        if p.paragraph:
            allowed.update(("para", n) for n in re.findall(r"\d+", p.paragraph))
        if p.section:
            for n in re.findall(r"\d+", p.section):
                allowed.update((kind, n) for kind in _SECTION_LIKE_KINDS)
    for locator in _locators_in(explanation):
        if locator not in allowed:
            problems.append("the explanation refers to a paragraph, section, article, clause or rule number that is not in the supplied material")
            break

    # 3. Years must occur in the supplied material.
    corpus_years = set(_YEAR_RE.findall(corpus))
    if any(year not in corpus_years for year in _YEAR_RE.findall(explanation)):
        problems.append("the explanation mentions a year that is not in the supplied material")

    # 4. Case names ('X v Y') must be findable in the supplied material.
    corpus_norm = normalize_citation(corpus)
    for m in _CASE_NAME_RE.finditer(explanation):
        pair = normalize_citation(f"{m.group('left')} v {m.group('right')}")
        if pair not in corpus_norm:
            problems.append("the explanation names a case that is not in the supplied material")
            break

    return problems


# --------------------------------------------------------------------------
# Model-assessment verification
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifiedAssessment:
    """A model assessment that survived every check. `sources` was built from
    supplied authority data; `explanation` passed the grounding checks."""

    relationship: CitationRelationship
    explanation: str
    sources: list[SourceProvenance]


def verify_model_assessment(
    payload: object,
    *,
    claim_text: str,
    citation_text: str,
    authority: SuppliedAuthority,
    passages: list[AuthorityPassage],
) -> tuple[Optional[VerifiedAssessment], list[str]]:
    """Check a parsed model response. Returns (assessment, []) if it is
    trustworthy, or (None, reasons) if it must be discarded."""
    if not isinstance(payload, dict):
        return None, ["the model response was not a JSON object"]

    reasons: list[str] = []

    # -- relationship -----------------------------------------------------
    raw_rel = payload.get("relationship")
    try:
        relationship = CitationRelationship(raw_rel)
    except ValueError:
        return None, ["the model returned a relationship outside the allowed set"]
    if relationship not in MODEL_ALLOWED_RELATIONSHIPS:
        return None, [
            "the model returned SOURCE_NOT_FOUND although the authority text was located; "
            "only the pipeline may decide that"
        ]

    # -- explanation ------------------------------------------------------
    explanation = payload.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        reasons.append("the model gave no explanation")
        explanation = ""

    # -- uncertainty ------------------------------------------------------
    uncertain = payload.get("uncertain", False)
    if not isinstance(uncertain, bool):
        reasons.append("the model's 'uncertain' flag was not a boolean")
        uncertain = False
    if uncertain and relationship != CitationRelationship.REQUIRES_HUMAN_REVIEW:
        relationship = CitationRelationship.REQUIRES_HUMAN_REVIEW  # preserve uncertainty

    # -- cited passages ---------------------------------------------------
    by_id = {p.passage_id: p for p in passages}
    raw_cited = payload.get("cited_passages", [])
    if raw_cited is None:
        raw_cited = []
    if not isinstance(raw_cited, list):
        reasons.append("'cited_passages' was not a list")
        raw_cited = []

    quote_sources: list[SourceProvenance] = []
    seen: set[tuple[str, str]] = set()
    for entry in raw_cited:
        if not isinstance(entry, dict):
            reasons.append("a cited passage entry was not an object")
            continue
        passage_id = entry.get("passage_id")
        passage = by_id.get(passage_id) if isinstance(passage_id, str) else None
        if passage is None:
            reasons.append("a cited passage_id does not match any supplied passage")
            continue
        quote = entry.get("exact_text")
        if not isinstance(quote, str) or not quote.strip():
            reasons.append("a cited passage had no exact_text")
            continue
        if not verify_quote(quote, passage.text):
            reasons.append("cited exact_text was not found verbatim in the supplied passage")
            continue
        # Locators the model volunteers must equal the source's own metadata.
        for field_name in ("paragraph", "section"):
            claimed = entry.get(field_name)
            if claimed is None:
                continue
            actual = getattr(passage, field_name)
            if actual is None or str(claimed).strip() != actual:
                reasons.append(f"the model stated a {field_name} that does not match the supplied passage")
        key = (passage.passage_id, normalize_whitespace(quote))
        if key in seen:
            continue
        seen.add(key)
        quote_sources.append(authority.provenance(passage=passage, exact_text=normalize_whitespace(quote)))

    if relationship in QUOTE_REQUIRED_RELATIONSHIPS and not quote_sources:
        reasons.append(f"{relationship.value} was proposed without any verifiable supporting quotation")

    # -- explanation grounding -------------------------------------------
    if explanation:
        corpus = build_grounding_corpus(claim_text, citation_text, authority, passages)
        reasons.extend(find_ungrounded_references(explanation, corpus, passages))

    if reasons:
        return None, list(dict.fromkeys(reasons))

    sources = quote_sources or [authority.provenance()]
    return VerifiedAssessment(relationship=relationship, explanation=explanation.strip(), sources=sources), []
