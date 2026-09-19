"""Trust boundary between the model and the counter-analysis finding.

The model is asked which supplied material bears on a claim and what the
limits of that material are. It is *never* trusted for provenance and never
trusted for the existence of a source. Everything it returns is re-checked
here against the corpus the agent actually supplied:

  * every `evidence_id` must resolve to a supplied EvidenceItem;
  * every `authority_id` + `passage_id` must resolve to a supplied passage;
  * every `exact_text` must appear verbatim in that passage (whitespace-
    collapsed comparison only — no case folding, no fuzzy matching);
  * every counterpoint must carry at least one basis that survived the above;
  * free text may not introduce quotations, case names, years, or
    paragraph/section numbers that are not in the supplied material;
  * free text may not predict an outcome or determine guilt or liability.

Rejection is per item, not per response: one fabricated authority does not
discard a genuine counterpoint found alongside it. But an item that fails any
check is dropped completely, and if every proposed item is dropped the agent
reports NO_CONTRARY_SOURCE_FOUND rather than keeping a weakened version of
the model's answer. Nothing is repaired, softened, or partially believed.

The quote and grounding primitives are shared with the AuthorityCitationAgent
so that "verbatim" means exactly the same thing in both agents.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pydantic import ValidationError

from ..authority_citation.schemas import AuthorityPassage, SuppliedAuthority
from ..authority_citation.validation import (
    find_ungrounded_references,
    normalize_whitespace,
    verify_quote,
)
from ..evidence_conflict.schemas import EvidenceItem
from .schemas import (
    CounterArgumentTarget,
    Counterpoint,
    CounterpointBasis,
    CounterpointType,
    MaterialKind,
    RetrievedAuthority,
    RetrievedEvidence,
    UnresolvedQuestion,
)

# --------------------------------------------------------------------------
# The corpus index
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CorpusIndex:
    """Everything this run is allowed to point at, indexed for lookup.

    Built once from the agent's input. If an id is not in here, it does not
    exist as far as the agent is concerned — there is no fallback lookup and
    no fuzzy match.
    """

    evidence_by_id: dict[str, EvidenceItem]
    authorities_by_id: dict[str, SuppliedAuthority]
    passages_by_key: dict[tuple[str, str], AuthorityPassage]

    @classmethod
    def build(
        cls, evidence: list[EvidenceItem], authorities: list[SuppliedAuthority]
    ) -> "CorpusIndex":
        passages: dict[tuple[str, str], AuthorityPassage] = {}
        for authority in authorities:
            for passage in authority.usable_passages():
                passages[(authority.authority_id, passage.passage_id)] = passage
        return cls(
            evidence_by_id={e.evidence_id: e for e in evidence},
            authorities_by_id={a.authority_id: a for a in authorities},
            passages_by_key=passages,
        )

    @property
    def is_empty(self) -> bool:
        return not self.evidence_by_id and not self.authorities_by_id

    def all_passages(self) -> list[AuthorityPassage]:
        return list(self.passages_by_key.values())


def build_grounding_corpus(target: CounterArgumentTarget, index: CorpusIndex) -> str:
    """Every word the model's prose is allowed to draw on."""
    parts: list[str] = [target.claim_text]
    if target.source.quote:
        parts.append(target.source.quote)
    for item in index.evidence_by_id.values():
        parts.append(item.description)
        if item.source.quote:
            parts.append(item.source.quote)
        if item.item_date:
            parts.append(item.item_date)
        parts.extend(item.entities)
    for authority in index.authorities_by_id.values():
        parts.extend(
            x for x in (authority.title, authority.citation, *authority.aliases) if x
        )
    for passage in index.all_passages():
        parts.extend(x for x in (passage.text, passage.paragraph, passage.section) if x)
    return "\n".join(p for p in parts if p)


# --------------------------------------------------------------------------
# Per-item resolution
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Resolution:
    """Outcome of checking one model-proposed item."""

    ok: bool
    reasons: list[str] = field(default_factory=list)


def resolve_evidence_reference(
    raw: object, index: CorpusIndex
) -> tuple[Optional[RetrievedEvidence], Resolution]:
    """Turn a model-proposed evidence reference into retrieved evidence."""
    if not isinstance(raw, dict):
        return None, Resolution(False, ["the entry was not a JSON object"])

    evidence_id = raw.get("evidence_id")
    if not isinstance(evidence_id, str) or not evidence_id.strip():
        return None, Resolution(False, ["no evidence_id was given"])

    item = index.evidence_by_id.get(evidence_id)
    if item is None:
        return None, Resolution(
            False, ["the evidence_id does not match any evidence supplied to this run"]
        )
    # Provenance is copied from the supplied item; the model's own words about
    # it are not carried into the finding.
    return RetrievedEvidence.from_item(item), Resolution(True)


def resolve_authority_reference(
    raw: object, index: CorpusIndex
) -> tuple[Optional[RetrievedAuthority], Resolution]:
    """Turn a model-proposed authority reference into retrieved authority.

    Requires a passage that exists and a quotation that is verbatim. This is
    where a fabricated authority dies.
    """
    if not isinstance(raw, dict):
        return None, Resolution(False, ["the entry was not a JSON object"])

    authority_id = raw.get("authority_id")
    if not isinstance(authority_id, str) or not authority_id.strip():
        return None, Resolution(False, ["no authority_id was given"])

    authority = index.authorities_by_id.get(authority_id)
    if authority is None:
        return None, Resolution(
            False, ["the authority_id does not match any authority supplied to this run"]
        )

    passage_id = raw.get("passage_id")
    if not isinstance(passage_id, str) or not passage_id.strip():
        return None, Resolution(False, ["no passage_id was given for the authority"])

    passage = index.passages_by_key.get((authority_id, passage_id))
    if passage is None:
        return None, Resolution(
            False, ["the passage_id does not match any passage of that authority"]
        )

    quote = raw.get("exact_text")
    if not isinstance(quote, str) or not quote.strip():
        return None, Resolution(False, ["no exact_text quotation was given"])
    if not verify_quote(quote, passage.text):
        return None, Resolution(
            False, ["the quotation was not found verbatim in the supplied passage"]
        )

    reasons: list[str] = []
    # Any locator the model volunteers must equal the passage's own metadata.
    for field_name in ("paragraph", "section"):
        claimed = raw.get(field_name)
        if claimed is None:
            continue
        actual = getattr(passage, field_name)
        if actual is None or str(claimed).strip() != actual:
            reasons.append(
                f"the model stated a {field_name} that does not match the supplied passage"
            )
    if reasons:
        return None, Resolution(False, reasons)

    try:
        retrieved = RetrievedAuthority(
            authority_id=authority.authority_id,
            passage_id=passage.passage_id,
            provenance=authority.provenance(
                passage=passage, exact_text=normalize_whitespace(quote)
            ),
        )
    except ValidationError as exc:  # pragma: no cover - construction is already guarded
        return None, Resolution(False, [_describe(exc)])
    return retrieved, Resolution(True)


def resolve_basis(
    raw: object, index: CorpusIndex
) -> tuple[Optional[CounterpointBasis], Resolution]:
    """Resolve one basis entry of a counterpoint or unresolved question."""
    if not isinstance(raw, dict):
        return None, Resolution(False, ["a basis entry was not a JSON object"])

    kind_raw = raw.get("kind")
    if kind_raw is None:
        # Infer from the id that is present rather than rejecting on a
        # missing label — the id is what actually has to resolve.
        kind_raw = "EVIDENCE" if raw.get("evidence_id") else "AUTHORITY"
    try:
        kind = MaterialKind(kind_raw)
    except ValueError:
        return None, Resolution(False, ["a basis entry named an unknown kind"])

    if kind == MaterialKind.EVIDENCE:
        evidence, res = resolve_evidence_reference(raw, index)
        if not res.ok:
            return None, res
        return CounterpointBasis(kind=kind, evidence=evidence), Resolution(True)

    authority, res = resolve_authority_reference(raw, index)
    if not res.ok:
        return None, res
    return CounterpointBasis(kind=kind, authority=authority), Resolution(True)


# --------------------------------------------------------------------------
# Prose grounding
# --------------------------------------------------------------------------


def check_prose(text: str, corpus: str, index: CorpusIndex) -> list[str]:
    """Problems found in a model-written sentence (empty list = grounded).

    Problem strings never repeat the offending text, so a rejected
    hallucination cannot leak into the result through the audit record.
    """
    if not text.strip():
        return ["the text was blank"]
    return find_ungrounded_references(text, corpus, index.all_passages())


# --------------------------------------------------------------------------
# Whole-response verification
# --------------------------------------------------------------------------


@dataclass
class RejectedItem:
    kind: str
    raw: dict
    reasons: list[str]


@dataclass
class VerifiedCounterAnalysis:
    """Everything from one model response that survived every check."""

    supporting_evidence: list[RetrievedEvidence] = field(default_factory=list)
    contrary_evidence: list[RetrievedEvidence] = field(default_factory=list)
    supporting_authority: list[RetrievedAuthority] = field(default_factory=list)
    contrary_authority: list[RetrievedAuthority] = field(default_factory=list)
    counterpoints: list[Counterpoint] = field(default_factory=list)
    unresolved_questions: list[UnresolvedQuestion] = field(default_factory=list)
    rejected: list[RejectedItem] = field(default_factory=list)

    def has_contrary_material(self) -> bool:
        return bool(self.contrary_evidence or self.contrary_authority or self.counterpoints)


def _describe(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        loc = ".".join(str(p) for p in error["loc"]) or "<root>"
        parts.append(f"{loc}: {error['msg']}")
    return "; ".join(parts) or str(exc)


def _dedupe_reasons(reasons: list[str]) -> list[str]:
    return list(dict.fromkeys(reasons))


def _as_dict(raw: object) -> dict:
    return raw if isinstance(raw, dict) else {"value": repr(raw)[:500]}


def verify_counter_analysis(
    payload: dict,
    *,
    target: CounterArgumentTarget,
    index: CorpusIndex,
) -> VerifiedCounterAnalysis:
    """Re-check a parsed model response against the supplied corpus."""
    verified = VerifiedCounterAnalysis()
    corpus = build_grounding_corpus(target, index)

    def _list(key: str) -> list:
        value = payload.get(key)
        if value is None:
            return []
        if not isinstance(value, list):
            verified.rejected.append(
                RejectedItem(kind="response", raw={"field": key}, reasons=[f"{key!r} was not a list"])
            )
            return []
        return value

    # -- retrieved material (categories 1 and 2) --------------------------
    for key, bucket in (
        ("supporting_evidence", verified.supporting_evidence),
        ("contrary_evidence", verified.contrary_evidence),
    ):
        seen: set[str] = set()
        for raw in _list(key):
            evidence, res = resolve_evidence_reference(raw, index)
            if not res.ok:
                verified.rejected.append(RejectedItem(key, _as_dict(raw), res.reasons))
                continue
            if evidence.evidence_id in seen:
                continue
            seen.add(evidence.evidence_id)
            bucket.append(evidence)

    for key, bucket in (
        ("supporting_authority", verified.supporting_authority),
        ("contrary_authority", verified.contrary_authority),
    ):
        seen_keys: set[tuple[str, str]] = set()
        for raw in _list(key):
            authority, res = resolve_authority_reference(raw, index)
            if not res.ok:
                verified.rejected.append(RejectedItem(key, _as_dict(raw), res.reasons))
                continue
            dedupe_key = (authority.authority_id, authority.provenance.exact_text or "")
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            bucket.append(authority)

    # -- reasoning (category 3) -------------------------------------------
    for position, raw in enumerate(_list("counterpoints"), start=1):
        counterpoint, reasons = _build_counterpoint(position, raw, target, index, corpus)
        if counterpoint is None:
            verified.rejected.append(RejectedItem("counterpoint", _as_dict(raw), reasons))
            continue
        verified.counterpoints.append(counterpoint)

    for position, raw in enumerate(_list("unresolved_questions"), start=1):
        question, reasons = _build_question(position, raw, target, index, corpus)
        if question is None:
            verified.rejected.append(RejectedItem("unresolved_question", _as_dict(raw), reasons))
            continue
        verified.unresolved_questions.append(question)

    return verified


def _build_counterpoint(
    position: int,
    raw: object,
    target: CounterArgumentTarget,
    index: CorpusIndex,
    corpus: str,
) -> tuple[Optional[Counterpoint], list[str]]:
    if not isinstance(raw, dict):
        return None, ["the entry was not a JSON object"]

    reasons: list[str] = []

    try:
        counterpoint_type = CounterpointType(raw.get("counterpoint_type"))
    except ValueError:
        return None, ["the counterpoint type was outside the allowed set"]

    statement = raw.get("statement")
    if not isinstance(statement, str) or not statement.strip():
        return None, ["the counterpoint had no statement"]
    reasons.extend(check_prose(statement, corpus, index))

    raw_basis = raw.get("basis")
    if raw_basis is None:
        raw_basis = []
    if not isinstance(raw_basis, list):
        return None, ["'basis' was not a list"]

    basis: list[CounterpointBasis] = []
    seen: set[tuple[str, str]] = set()
    for entry in raw_basis:
        resolved, res = resolve_basis(entry, index)
        if not res.ok:
            reasons.extend(res.reasons)
            continue
        key = (resolved.kind.value, resolved.source_id)
        if key in seen:
            continue
        seen.add(key)
        basis.append(resolved)

    if not basis:
        # This is the unsupported-counterargument case: a point with nothing
        # behind it is discarded, never kept "for balance".
        reasons.append(
            "the counterpoint cited no supplied evidence or authority that could be resolved"
        )
        return None, _dedupe_reasons(reasons)

    if reasons:
        return None, _dedupe_reasons(reasons)

    try:
        return (
            Counterpoint(
                counterpoint_id=f"CP-{position:03d}",
                claim_id=target.claim_id,
                counterpoint_type=counterpoint_type,
                statement=statement.strip(),
                basis=basis,
            ),
            [],
        )
    except ValidationError as exc:
        return None, [_describe(exc)]


def _build_question(
    position: int,
    raw: object,
    target: CounterArgumentTarget,
    index: CorpusIndex,
    corpus: str,
) -> tuple[Optional[UnresolvedQuestion], list[str]]:
    if not isinstance(raw, dict):
        return None, ["the entry was not a JSON object"]

    question = raw.get("question")
    if not isinstance(question, str) or not question.strip():
        return None, ["the entry had no question text"]

    reasons = check_prose(question, corpus, index)

    about_absent = raw.get("about_absent_material", False)
    if not isinstance(about_absent, bool):
        reasons.append("'about_absent_material' was not a boolean")
        about_absent = False

    raw_basis = raw.get("basis") or []
    if not isinstance(raw_basis, list):
        return None, ["'basis' was not a list"]

    basis: list[CounterpointBasis] = []
    for entry in raw_basis:
        resolved, res = resolve_basis(entry, index)
        if not res.ok:
            reasons.extend(res.reasons)
            continue
        basis.append(resolved)

    if reasons:
        return None, _dedupe_reasons(reasons)

    try:
        return (
            UnresolvedQuestion(
                question_id=f"UQ-{position:03d}",
                claim_id=target.claim_id,
                question=question.strip(),
                basis=basis,
                about_absent_material=about_absent,
            ),
            [],
        )
    except ValidationError as exc:
        return None, [_describe(exc)]
