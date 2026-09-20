"""Deterministic citation-text helpers.

Nothing in this module knows any law. It only (a) classifies the *shape* of a
citation string and (b) decides whether a citation string and a supplied
authority refer to the same thing by comparing normalised text. Both are
plain string handling, so they cannot hallucinate.

Matching is deliberately strict: normalised *equality* against the
authority's citation, title or declared aliases. There is no fuzzy or
"closest match" step, because a near-miss match is how a fake citation would
get quietly attached to a real authority. Parallel citations (e.g. the same
case reported in two series) must be declared by the source in `aliases`.
"""
from __future__ import annotations

import re
import unicodedata

from .schemas import AuthorityType, CitedAuthority, SuppliedAuthority

# --------------------------------------------------------------------------
# Normalisation & matching
# --------------------------------------------------------------------------

_VERSUS_RE = re.compile(r"(?<![A-Za-z0-9])(?:versus|vs|v)(?![A-Za-z0-9])\.?", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_citation(text: str) -> str:
    """Case-fold, unify 'v' / 'v.' / 'vs' / 'versus', drop punctuation and
    collapse whitespace. "Fake Case v. State, 9999" -> "fake case v state 9999"."""
    t = unicodedata.normalize("NFKC", text or "").casefold()
    t = _VERSUS_RE.sub(" v ", t)
    t = _PUNCT_RE.sub(" ", t)
    return " ".join(t.split())


def authority_matches_citation(cited: CitedAuthority, authority: SuppliedAuthority) -> bool:
    """Does this supplied authority *identify* as the cited authority?

    * If the caller supplied an authority_id, the id is the sole basis.
    * Otherwise the normalised citation text must equal the normalised
      citation, title, or one of the authority's declared aliases.
    """
    if cited.authority_id is not None:
        return cited.authority_id == authority.authority_id
    target = normalize_citation(cited.citation_text)
    if not target:
        return False
    labels = [authority.citation, authority.title, *authority.aliases]
    return any(label and normalize_citation(label) == target for label in labels)


# --------------------------------------------------------------------------
# Type identification
# --------------------------------------------------------------------------

_CASE_VERSUS_RE = re.compile(r"\S\s+(?:v|vs|versus)\.?\s+\S", re.IGNORECASE)
# Law-report abbreviations are matched case-sensitively so ordinary words
# ("air", "scr...") never trigger them.
_REPORTER_RE = re.compile(
    r"(?<![A-Za-z])(?:AIR|SCC|SCR|SCALE|ILR|MLJ|WLR|All\s?ER|Cri\s?LJ|Crl\s?LJ|Cr\.?\s?L\.?J)(?![A-Za-z])"
)
_CONSTITUTION_RE = re.compile(r"\bconstitution\b", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"(?<![A-Za-z])(?:articles?|arts?\.?)\s*\d+", re.IGNORECASE)
_SECTION_RE = re.compile(r"(?<![A-Za-z])(?:sections?|secs?\.?|s\.)\s*\d+", re.IGNORECASE)
_STATUTE_WORD_RE = re.compile(
    r"\b(?:act|acts|code|ordinance|ipc|crpc|cpc|bns|bnss|bsa)\b", re.IGNORECASE
)
_REGULATION_RE = re.compile(
    r"\b(?:rules?|regulations?|notification|bye-?laws?)\b|\border\s+[ivxlc\d]+\b", re.IGNORECASE
)
_SECONDARY_RE = re.compile(
    r"\b(?:law commission|report|treatise|commentary|law review|journal|textbook)\b", re.IGNORECASE
)


def identify_citation_type(citation_text: str) -> AuthorityType:
    """Classify the *shape* of a citation string. UNKNOWN when unsure.

    Purely lexical: 'X v Y' or a law-report abbreviation -> CASE_LAW;
    'Article N' / 'Constitution' -> CONSTITUTIONAL_PROVISION; 'Section N' or
    an Act/Code word -> STATUTE; Rules/Regulations -> REGULATION; report or
    treatise words -> SECONDARY_SOURCE. It never checks that anything exists.
    """
    text = citation_text or ""
    if _CASE_VERSUS_RE.search(text) or _REPORTER_RE.search(text):
        return AuthorityType.CASE_LAW
    has_statute_word = bool(_STATUTE_WORD_RE.search(text))
    if _CONSTITUTION_RE.search(text) or (_ARTICLE_RE.search(text) and not has_statute_word):
        return AuthorityType.CONSTITUTIONAL_PROVISION
    if _SECTION_RE.search(text) or has_statute_word:
        return AuthorityType.STATUTE
    if _REGULATION_RE.search(text):
        return AuthorityType.REGULATION
    if _SECONDARY_RE.search(text):
        return AuthorityType.SECONDARY_SOURCE
    return AuthorityType.UNKNOWN
