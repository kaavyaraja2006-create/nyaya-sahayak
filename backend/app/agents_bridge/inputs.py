"""Backend domain models -> the agents' own Pydantic inputs.

Only this module knows both vocabularies. Nothing here invents content: every
field is copied from a stored document, evidence row or authority record, and
anything the backend does not hold is left unset rather than guessed.
"""
from __future__ import annotations

from agents.authority_citation.schemas import (
    AuthorityPassage,
    AuthorityType,
    SuppliedAuthority,
)
from agents.case_understanding.schemas import (
    DocumentKind,
    Page,
    Paragraph,
    SourceDocument,
)
from agents.evidence_conflict.schemas import EvidenceItem, EvidenceType
from agents.case_understanding.schemas import SourceReference as AgentSourceReference
from agents.graph import NyayaSahayakState

from ..models.authority import Authority
from ..models.document import Document
from ..models.evidence import Evidence

# Backend document_type strings -> the agents' DocumentKind. Anything not
# listed stays OTHER; the kind is a classification of the file, never a
# statement about the weight of its contents.
_DOCUMENT_KIND_MAP = {
    "witness statement": DocumentKind.WITNESS_STATEMENT,
    "statement": DocumentKind.WITNESS_STATEMENT,
    "investigation report": DocumentKind.INVESTIGATION_REPORT,
    "police report": DocumentKind.INVESTIGATION_REPORT,
    "fir": DocumentKind.INVESTIGATION_REPORT,
    "legal draft": DocumentKind.LEGAL_DRAFT,
    "petition": DocumentKind.LEGAL_DRAFT,
    "plaint": DocumentKind.LEGAL_DRAFT,
    "written submission": DocumentKind.WRITTEN_SUBMISSION,
    "submission": DocumentKind.WRITTEN_SUBMISSION,
    "hearing transcript": DocumentKind.HEARING_TRANSCRIPT,
    "transcript": DocumentKind.HEARING_TRANSCRIPT,
    "contract": DocumentKind.FACTUAL_DOCUMENT,
    "agreement": DocumentKind.FACTUAL_DOCUMENT,
    "invoice": DocumentKind.FACTUAL_DOCUMENT,
    "medical report": DocumentKind.FACTUAL_DOCUMENT,
}

_EVIDENCE_TYPE_MAP = {
    "document": EvidenceType.DOCUMENT,
    "physical": EvidenceType.PHYSICAL,
    "digital": EvidenceType.DIGITAL,
    "testimony": EvidenceType.TESTIMONY,
    "forensic": EvidenceType.FORENSIC,
}

_AUTHORITY_TYPE_MAP = {
    "case_law": AuthorityType.CASE_LAW,
    "case law": AuthorityType.CASE_LAW,
    "judgment": AuthorityType.CASE_LAW,
    "statute": AuthorityType.STATUTE,
    "act": AuthorityType.STATUTE,
    "regulation": AuthorityType.REGULATION,
    "rules": AuthorityType.REGULATION,
    "constitutional_provision": AuthorityType.CONSTITUTIONAL_PROVISION,
    "constitution": AuthorityType.CONSTITUTIONAL_PROVISION,
    "secondary_source": AuthorityType.SECONDARY_SOURCE,
    "commentary": AuthorityType.SECONDARY_SOURCE,
}


def document_kind(document: Document) -> DocumentKind:
    if document.is_transcript:
        return DocumentKind.HEARING_TRANSCRIPT
    return _DOCUMENT_KIND_MAP.get((document.document_type or "").strip().lower(), DocumentKind.OTHER)


def to_source_document(document: Document) -> SourceDocument:
    """A stored document, page by page, with its paragraph numbering intact.

    `pages_json` is written at upload time as [{page, paragraphs:[{n, text}]}].
    Keeping that structure is what lets a claim cite page 3, paragraph 2 and
    have a human land on the same words.
    """
    pages: list[Page] = []
    for raw_page in document.pages_json or []:
        paragraphs = [
            Paragraph(number=int(p.get("n") or index + 1), text=p.get("text") or "")
            for index, p in enumerate(raw_page.get("paragraphs") or [])
            if (p.get("text") or "").strip()
        ]
        if paragraphs:
            pages.append(Page(number=int(raw_page.get("page") or len(pages) + 1), paragraphs=paragraphs))

    return SourceDocument(
        document_id=document.document_id or document.id,
        title=document.filename or None,
        document_kind=document_kind(document),
        is_transcript=bool(document.is_transcript),
        pages=pages,
        raw_text="" if pages else (document.extracted_text or ""),
    )


def to_evidence_item(evidence: Evidence) -> EvidenceItem:
    reference = evidence.source_reference
    return EvidenceItem(
        evidence_id=evidence.evidence_id or evidence.id,
        evidence_type=_EVIDENCE_TYPE_MAP.get(
            (evidence.evidence_type or "").strip().lower(), EvidenceType.OTHER
        ),
        description=evidence.description or evidence.evidence_id or "Unnamed evidence item",
        source=AgentSourceReference(
            document_id=getattr(reference, "source_document_id", None),
            page=getattr(reference, "page", None),
            paragraph=getattr(reference, "paragraph", None),
            quote=getattr(reference, "quote", None),
        ),
        item_date=evidence.item_date,
    )


def to_supplied_authority(authority: Authority) -> SuppliedAuthority:
    """An approved corpus record, with its passage text carried through.

    The agent verifies propositions against this text and quotes from it
    verbatim, so the passage is passed whole rather than summarised.
    """
    passages: list[AuthorityPassage] = []
    if authority.passage:
        passages.append(
            AuthorityPassage(
                passage_id=f"{authority.authority_id or authority.id}-P",
                text=authority.passage,
                paragraph=str(authority.paragraph) if authority.paragraph else None,
            )
        )

    return SuppliedAuthority(
        authority_id=authority.authority_id or authority.id,
        source_type=_AUTHORITY_TYPE_MAP.get(
            (authority.source_type or "").strip().lower(), AuthorityType.UNKNOWN
        ),
        title=authority.title or authority.label,
        citation=authority.citation,
        aliases=[a for a in (authority.aliases or []) if a],
        url=authority.url,
        text=authority.passage or "",
        passages=passages,
    )


def evidence_from_documents(documents: list[Document]) -> list[Evidence]:
    """Derive one evidence row per stored document.

    Segmenting case material into evidence items is the caller's job — the
    EvidenceConflictAgent compares evidence, it does not create it. One item
    per document is the most conservative segmentation available from what the
    backend actually holds: it never asserts that a passage is a distinct
    exhibit when nobody said so.
    """
    from ..models.claim import SourceReference as BackendSourceReference

    items: list[Evidence] = []
    for index, document in enumerate(documents, start=1):
        first_page = (document.pages_json or [{}])[0]
        first_paragraph = ((first_page.get("paragraphs") or [{}])[0]) if first_page else {}
        items.append(
            Evidence(
                evidence_id=f"E-{index:03d}",
                case_id=document.case_id,
                evidence_type="Testimony" if document.is_transcript else "Document",
                description=f"{document.document_type or 'Document'}: {document.filename}",
                source_reference=BackendSourceReference(
                    source_document_id=document.document_id or document.id,
                    page=int(first_page.get("page") or 1) if first_page else 1,
                    paragraph=int(first_paragraph.get("n") or 1) if first_paragraph else None,
                    quote=(first_paragraph.get("text") or None) if first_paragraph else None,
                ),
            )
        )
    return items


def build_state(
    *,
    case_public_id: str,
    documents: list[Document],
    evidence: list[Evidence],
    authorities: list[Authority],
    material_claim_ids: list[str] | None = None,
) -> NyayaSahayakState:
    """Assemble the one state object the graph runs on.

    `citations_by_claim` is deliberately left empty here: it is keyed by
    claim_id, and claim_ids do not exist until the first agent has run. The
    backend supplies it inside the pipeline through
    `CitationSupplyingAuthorityAgent` (see citations.py).
    """
    return NyayaSahayakState(
        case_id=case_public_id,
        documents=[to_source_document(d) for d in documents],
        evidence=[to_evidence_item(e) for e in evidence],
        authorities=[to_supplied_authority(a) for a in authorities],
        citations_by_claim={},
        material_claim_ids=list(material_claim_ids or []),
        authority_statuses=[],
    )
