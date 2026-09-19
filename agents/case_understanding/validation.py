"""Independent provenance verification.

This module never trusts what the model *says* about a claim's verification
status. It re-derives that status itself by checking the claim's quote
against the actual source documents supplied to the agent. This is the only
mechanism in the pipeline that can mark a claim VERIFIED, and it is
deliberately conservative: anything it cannot personally confirm stays
UNVERIFIED.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import Claim, SourceDocument, VerificationStatus


def _normalize(text: str) -> str:
    """Collapse whitespace and lowercase for a tolerant-but-still-verbatim
    substring match (handles line wraps / OCR spacing, not paraphrase)."""
    return re.sub(r"\s+", " ", text).strip().lower()


@dataclass(frozen=True)
class ProvenanceCheck:
    status: VerificationStatus
    notes: str


def _document_full_text(doc: SourceDocument) -> str:
    parts = [doc.raw_text]
    for page in doc.pages:
        for para in page.paragraphs:
            parts.append(para.text)
    for utt in doc.utterances:
        parts.append(utt.text)
    return "\n".join(p for p in parts if p)


def _paragraph_text(doc: SourceDocument, page: int | None, paragraph: int | None) -> str | None:
    if page is None or paragraph is None:
        return None
    for pg in doc.pages:
        if pg.number == page:
            for para in pg.paragraphs:
                if para.number == paragraph:
                    return para.text
    return None


def _page_text(doc: SourceDocument, page: int | None) -> str | None:
    if page is None:
        return None
    for pg in doc.pages:
        if pg.number == page:
            return "\n".join(p.text for p in pg.paragraphs)
    return None


def _transcript_location_text(doc: SourceDocument, location: str | None) -> str | None:
    if not location:
        return None
    for utt in doc.utterances:
        if utt.location == location:
            return utt.text
    return None


def check_claim_provenance(claim: Claim, documents: dict[str, SourceDocument]) -> ProvenanceCheck:
    """Independently verify a single claim's source reference.

    Only ever returns VERIFIED when a verbatim quote is actually found in the
    text of the referenced document, at the referenced location if one was
    given. Every other case — missing document, missing quote, quote not
    found, quote found somewhere else in the document — resolves to
    UNVERIFIED with an explanatory note. Nothing is discarded here; that is
    the caller's decision to make (see agent.py / RejectedClaim).
    """
    ref = claim.source

    if not ref.document_id:
        return ProvenanceCheck(
            VerificationStatus.UNVERIFIED,
            "No document_id supplied; the claim's source document cannot be confirmed.",
        )

    doc = documents.get(ref.document_id)
    if doc is None:
        return ProvenanceCheck(
            VerificationStatus.UNVERIFIED,
            f"document_id {ref.document_id!r} does not match any document supplied to the agent.",
        )

    if not ref.quote:
        located = any([
            ref.page is not None and _page_text(doc, ref.page) is not None,
            ref.transcript_location and _transcript_location_text(doc, ref.transcript_location) is not None,
        ])
        if located:
            return ProvenanceCheck(
                VerificationStatus.UNVERIFIED,
                "A location was given but no verbatim quote was supplied, so the claim's "
                "wording could not be independently confirmed against the source text.",
            )
        return ProvenanceCheck(
            VerificationStatus.UNVERIFIED,
            "No verbatim quote and no confirmable location were supplied for this document.",
        )

    normalized_quote = _normalize(ref.quote)
    if not normalized_quote:
        return ProvenanceCheck(
            VerificationStatus.UNVERIFIED,
            "Quote field was blank after normalization.",
        )

    # Prefer the most specific scope available, falling back to whole-document search.
    location_claimed = any([ref.page is not None, ref.paragraph is not None, ref.transcript_location])
    scoped_text = (
        _paragraph_text(doc, ref.page, ref.paragraph)
        or _page_text(doc, ref.page)
        or _transcript_location_text(doc, ref.transcript_location)
    )

    if scoped_text is not None and normalized_quote in _normalize(scoped_text):
        return ProvenanceCheck(
            VerificationStatus.VERIFIED,
            "Quote located verbatim at the specified page/paragraph/transcript location.",
        )

    whole_doc_text = _normalize(_document_full_text(doc))
    if normalized_quote in whole_doc_text:
        if location_claimed:
            # A specific location was given, but the quote lives elsewhere in
            # the document — the location itself could not be confirmed.
            return ProvenanceCheck(
                VerificationStatus.UNVERIFIED,
                "Quote was found in the referenced document, but not at the specified "
                "page/paragraph/transcript location. The location could not be confirmed.",
            )
        # No specific location was claimed at all, so a whole-document match
        # is the strongest confirmation available — and it succeeded.
        return ProvenanceCheck(
            VerificationStatus.VERIFIED,
            "Quote located verbatim in the referenced document (no specific page/paragraph "
            "was claimed).",
        )

    return ProvenanceCheck(
        VerificationStatus.UNVERIFIED,
        "Quote could not be located verbatim anywhere in the referenced document. "
        "This claim's provenance could not be confirmed and must be treated as unverified.",
    )


def enforce_no_false_verification(claims: list[Claim], documents: dict[str, SourceDocument]) -> list[str]:
    """Final safety net: re-run the check on every VERIFIED claim and return a
    list of violation messages for any claim whose VERIFIED status does not
    actually hold up. Callers should treat any non-empty result as a bug —
    the agent must never proceed as if an unverified claim were verified.
    """
    violations: list[str] = []
    for claim in claims:
        if claim.verification_status != VerificationStatus.VERIFIED:
            continue
        recheck = check_claim_provenance(claim, documents)
        if recheck.status != VerificationStatus.VERIFIED:
            violations.append(
                f"Claim {claim.claim_id} is marked VERIFIED but independent re-check "
                f"disagrees: {recheck.notes}"
            )
    return violations
