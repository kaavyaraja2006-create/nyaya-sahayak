"""ORM → API dict conversion.

The frontend contract is camelCase and mirrors src/types/index.ts exactly, so
the React layer needs no adapter code.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..models import (
    AgentRun, AuditEvent, Authority, Case, CaseAuthority, Citation, Claim,
    ClaimEvidence, Document, Evidence, Finding, Report, Review, ToolCall, Transcript,
)


def iso(dt: datetime | None) -> str | None:
    return dt.strftime("%Y-%m-%dT%H:%M:%S") if dt else None


def loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def source_of(document_id, page, paragraph, quote) -> dict | None:
    if not document_id:
        return None
    return {
        "documentId": document_id,
        "page": page or 1,
        "paragraph": paragraph or 1,
        "quote": quote or None,
    }


def case_out(c: Case, counts: dict | None = None) -> dict:
    return {
        "caseId": c.case_id,
        "name": c.name,
        "caseNumber": c.case_number or "",
        "caseType": c.case_type or "",
        "jurisdiction": c.jurisdiction or "",
        "court": c.court or "",
        "description": c.description or "",
        "status": c.status,
        "filedOn": c.filed_on or "",
        "lastAnalyzed": iso(c.last_analyzed) or "",
        "createdAt": iso(c.created_at) or "",
        "updatedAt": iso(c.updated_at) or "",
        "summary": c.description or "",
        "counts": counts or {},
    }


def document_out(d: Document) -> dict:
    return {
        "documentId": d.document_id,
        "name": d.filename,
        "type": d.document_type,
        "category": d.category,
        "date": iso(d.uploaded_at)[:10] if d.uploaded_at else "",
        "pages": d.page_count or 0,
        "status": d.status,
        "source": "Uploaded by reviewer",
        "uploadedAt": iso(d.uploaded_at) or "",
        "sizeBytes": d.size_bytes or 0,
        "isTranscript": bool(d.is_transcript),
        "content": loads(d.pages_json, []),
        "entities": loads(d.entities_json, []),
    }


def document_summary(d: Document) -> dict:
    out = document_out(d)
    out["content"] = []
    return out


def claim_out(c: Claim) -> dict:
    return {
        "claimId": c.claim_id,
        "title": c.title or (c.claim_text or "")[:70],
        "text": c.claim_text,
        "type": c.claim_type or "Statement",
        "speaker": c.speaker,
        "source": source_of(c.source_document_id, c.source_page, c.source_paragraph, c.source_quote),
        "originNote": c.origin_note,
        "status": c.status,
        "extractionConfidence": c.extraction_confidence or 0.0,
        "signals": loads(c.signals_json, {
            "directness": 0, "quality": 0, "sources": 0,
            "consistency": 0, "conflict": 0, "uncertainty": 0,
        }),
        "hearingStatementIds": loads(c.hearing_statement_ids, []),
    }


def evidence_out(e: Evidence) -> dict:
    return {
        "evidenceId": e.evidence_id,
        "type": e.evidence_type,
        "description": e.description,
        "source": source_of(e.source_document_id, e.source_page, e.source_paragraph, e.source_quote)
        or {"documentId": "", "page": 1, "paragraph": 1},
        "date": e.item_date or "",
        "metadata": loads(e.meta_json, {}),
    }


def relationship_out(r: ClaimEvidence) -> dict:
    return {
        "relationshipId": r.relationship_id,
        "claimId": r.claim_id,
        "evidenceId": r.evidence_id,
        "type": r.relationship,
        "reason": r.reason or "",
        "assessment": r.assessment_signal or "",
    }


def finding_out(f: Finding) -> dict:
    return {
        "findingId": f.finding_id,
        "kind": f.kind,
        "category": f.category or "",
        "group": f.group_name,
        "priority": f.priority,
        "claimId": f.claim_id or "",
        "title": f.title,
        "reason": f.reason or "",
        "conflictType": f.conflict_type,
        "comparison": loads(f.comparison_json, None),
        "relationshipIds": loads(f.relationship_ids, []),
        "evidenceIds": loads(f.evidence_ids, []),
        "authorityId": f.authority_id,
        "status": f.status,
        "createdAt": iso(f.created_at) or "",
    }


def authority_out(a: Authority, link: CaseAuthority | None = None) -> dict:
    return {
        "authorityId": a.authority_id,
        "label": a.label or a.title,
        "caseName": a.title,
        "court": a.court or "",
        "year": a.year or 0,
        "citation": a.citation or "",
        "paragraph": a.paragraph or 0,
        "passage": a.passage,
        "corpus": a.corpus or "Curated corpus",
        "claimIds": loads(link.claim_ids, []) if link else [],
        "relevance": link.relevance if link else None,
        "whyRetrieved": (link.why_retrieved if link else "") or "",
        "status": link.status if link else "verification_required",
    }


def citation_out(c: Citation) -> dict:
    return {
        "citationId": c.citation_id,
        "claimId": c.claim_id or "",
        "authorityId": c.authority_id,
        "result": c.result,
        "citedAt": source_of(c.source_document_id, c.source_page, c.source_paragraph, None),
        "note": c.note or "",
        "matchedPassage": c.matched_passage or "",
    }


def review_out(r: Review) -> dict:
    return {
        "reviewId": r.review_id,
        "findingId": r.finding_id,
        "decision": r.decision,
        "comment": r.comment or "",
        "reviewer": r.reviewer_name,
        "timestamp": iso(r.created_at) or "",
    }


def audit_out(a: AuditEvent, case_public_id: str) -> dict:
    return {
        "logId": a.log_id,
        "caseId": case_public_id,
        "timestamp": iso(a.created_at) or "",
        "actor": a.actor,
        "actorType": a.actor_type,
        "action": a.action,
        "objectType": a.object_type,
        "objectId": a.object_id or "",
        "previousState": a.previous_state,
        "newState": a.new_state,
        "details": a.details,
    }


def agent_run_out(r: AgentRun) -> dict:
    return {
        "runId": r.run_id,
        "agent": r.agent_name,
        "status": r.status,
        "inputSummary": r.input_summary or "",
        "outputSummary": r.output_summary or "",
        "warnings": loads(r.warnings, []),
        "latencyMs": r.latency_ms,
        "startedAt": iso(r.started_at),
        "completedAt": iso(r.completed_at),
        "error": r.error,
    }


def tool_call_out(t: ToolCall) -> dict:
    return {
        "tool": t.tool_name,
        "status": t.status,
        "latencyMs": t.latency_ms or 0,
        "timestamp": iso(t.created_at) or "",
        "detail": t.detail or "",
    }


def transcript_out(t: Transcript) -> dict:
    return {
        "hearingId": t.transcript_id,
        "date": t.hearing_date or "",
        "hearingNumber": t.hearing_number or "",
        "court": t.court or "",
        "documentId": t.document_id or "",
        "filename": t.filename or "",
        "speakers": loads(t.speakers_json, []),
        "statements": loads(t.statements_json, []),
        "uploadedAt": iso(t.uploaded_at) or "",
    }


def report_out(r: Report) -> dict:
    return {
        "reportId": r.report_id,
        "caseId": r.case_id,
        "generatedAt": iso(r.created_at) or "",
        "counts": loads(r.counts_json, {}),
    }
