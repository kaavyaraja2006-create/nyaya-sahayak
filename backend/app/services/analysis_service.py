"""Analysis service.

`POST /api/cases/{id}/analyze` creates an AnalysisRun and executes the
orchestrator in the background. The frontend polls `/analysis` and renders the
real agent-run records — progress is never faked.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from agents import CaseContext, Orchestrator
from agents.orchestrator import PIPELINE_STAGES
from agents.providers import build_provider
from ai_engine.analysis import conflict_strength, support_strength

from ..config import settings
from ..database import session_scope
from ..models import (
    AgentRun, AnalysisRun, Case, CaseAuthority, Citation, Claim, ClaimEvidence,
    Document, Evidence, Finding, Transcript, uid, utcnow,
)
from ..utils.ids import next_index, seq_id
from ..utils.serialize import dumps, loads
from . import case_service
from .authority_service import CorpusAuthorityService

log = logging.getLogger("nyayasahayak.analysis")

RUNNING_STATES = ("running",)


class AnalysisBusy(Exception):
    pass


def current_run(db: Session, case_row_id: str) -> AnalysisRun | None:
    return db.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.case_id == case_row_id)
        .order_by(AnalysisRun.started_at.desc())
    )


def build_context(db: Session, case: Case, ui_settings: dict | None = None) -> CaseContext:
    documents = case_service.list_documents(db, case.id)
    transcripts = case_service.list_transcripts(db, case.id)
    transcript_docs = {t.document_id: t for t in transcripts}

    doc_payload, transcript_payload = [], []
    for doc in documents:
        pages = loads(doc.pages_json, [])
        entry = {
            "document_id": doc.document_id,
            "document_type": doc.document_type,
            "filename": doc.filename,
            "pages": pages,
            "text": doc.extracted_text or "",
            "is_transcript": bool(doc.is_transcript),
        }
        if doc.is_transcript and doc.document_id in transcript_docs:
            tr = transcript_docs[doc.document_id]
            transcript_payload.append(
                {**entry, "transcript_id": tr.transcript_id, "hearing_date": tr.hearing_date,
                 "hearing_number": tr.hearing_number}
            )
        else:
            doc_payload.append(entry)

    return CaseContext(
        case_id=case.case_id,
        case_row_id=case.id,
        user_id=case.user_id,
        case_name=case.name,
        case_type=case.case_type or "",
        jurisdiction=case.jurisdiction or "",
        description=case.description or "",
        documents=doc_payload,
        transcripts=transcript_payload,
        settings=ui_settings or {},
    )


def start_run(db: Session, case: Case, actor: str, ui_settings: dict | None = None) -> AnalysisRun:
    existing = current_run(db, case.id)
    if existing and existing.status in RUNNING_STATES:
        raise AnalysisBusy("An analysis is already running for this case.")

    docs = case_service.list_documents(db, case.id)
    if not docs:
        raise ValueError("Upload at least one document or transcript before running an analysis.")

    run = AnalysisRun(
        case_id=case.id,
        status="running",
        stage_index=0,
        progress=0,
        message="Starting analysis",
        ai_mode="gemini" if settings.ai_configured else "deterministic",
    )
    db.add(run)
    db.query(AgentRun).filter(AgentRun.case_id == case.id).delete()
    case_service.set_status(db, case, "ANALYZING", actor=actor)
    case_service.log_event(
        db, case.id, action="Analysis started", object_type="case", object_id=case.case_id,
        actor=actor, actor_type="reviewer",
        details=f"Provider: {run.ai_mode}", commit=False,
    )
    db.commit()
    db.refresh(run)
    return run


async def execute_run(run_id: str, ui_settings: dict | None = None) -> None:
    """Background execution. Owns its own session so the request can return."""
    db = session_scope()
    try:
        run = db.get(AnalysisRun, run_id)
        if run is None:
            return
        case = db.get(Case, run.case_id)
        if case is None:
            return

        context = build_context(db, case, ui_settings)
        authority_service = CorpusAuthorityService(db)
        provider = build_provider(settings)
        orchestrator = Orchestrator(provider, authority_service)

        _clear_previous_analysis(db, case.id)
        total = len(PIPELINE_STAGES)
        warnings_all: list[str] = []

        for index, (key, label) in enumerate(PIPELINE_STAGES):
            run.stage_index = index
            run.progress = int(index / total * 100)
            run.message = label
            agent_row = AgentRun(
                run_id=f"AR-{str(index + 1).zfill(2)}",
                case_id=case.id,
                agent_name=key,
                status="running",
                started_at=utcnow(),
            )
            db.add(agent_row)
            db.commit()

            input_data = {"counts": case_service.case_counts(db, case.id)} if key == "report_agent" else {}
            result, latency = await orchestrator.run_stage(key, context, input_data)

            agent_row.status = result.status
            agent_row.latency_ms = latency
            agent_row.completed_at = utcnow()
            agent_row.warnings = dumps(result.warnings)
            agent_row.output_summary = _summarise(key, result.data)
            if result.status == "failed":
                agent_row.error = "; ".join(result.warnings)[:500]
            warnings_all.extend(result.warnings)

            _persist_stage(db, case, context, key, result.data)
            db.commit()

        summary = case_service.case_counts(db, case.id)
        summary["completedAt"] = utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        summary["warnings"] = warnings_all[:20]
        summary["aiMode"] = run.ai_mode

        run.status = "completed"
        run.stage_index = total
        run.progress = 100
        run.message = "Analysis complete"
        run.summary_json = dumps(summary)
        run.completed_at = utcnow()
        case.last_analyzed = utcnow()
        case_service.set_status(db, case, "ACTIVE_REVIEW", actor="Orchestrator")
        case_service.log_event(
            db, case.id, action="Analysis completed", object_type="case", object_id=case.case_id,
            actor="Orchestrator", actor_type="ai",
            details=(
                f"{summary['claims']} claim(s), {summary['evidence']} evidence item(s), "
                f"{summary['conflicts']} potential conflict(s). Human review required."
            ),
            commit=False,
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("Analysis run failed")
        db.rollback()
        run = db.get(AnalysisRun, run_id)
        if run:
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"[:400]
            run.message = "Analysis interrupted"
            run.completed_at = utcnow()
            case = db.get(Case, run.case_id)
            if case:
                case_service.set_status(db, case, "ACTIVE_REVIEW", actor="System")
            db.commit()
    finally:
        db.close()


def _clear_previous_analysis(db: Session, case_row_id: str) -> None:
    """Re-analysis replaces derived data. Reviews and audit events are preserved."""
    for model in (Claim, Evidence, ClaimEvidence, Citation, CaseAuthority):
        db.execute(delete(model).where(model.case_id == case_row_id))
    db.execute(
        delete(Finding).where(Finding.case_id == case_row_id, Finding.status == "open")
    )
    db.commit()


def _summarise(key: str, data: dict) -> str:
    if key == "claim_agent":
        return f"{len(data.get('claims', []))} claim(s) extracted"
    if key == "evidence_agent":
        return f"{len(data.get('evidence', []))} evidence item(s) identified"
    if key == "relationship_agent":
        return f"{len(data.get('relationships', []))} relationship(s) classified"
    if key == "conflict_agent":
        return f"{len(data.get('conflicts', []))} potential conflict(s) surfaced"
    if key == "legal_research_agent":
        return f"{len(data.get('authorities', []))} authority record(s) retrieved"
    if key == "citation_audit_agent":
        return f"{len(data.get('citations', []))} citation record(s) audited"
    if key == "document_agent":
        return f"{len(data.get('documents', []))} document(s) indexed"
    if key == "transcript_agent":
        return f"{len(data.get('transcripts', []))} transcript(s) processed"
    return "completed"


# ── persistence per stage ─────────────────────────────────────────────────────

def _persist_stage(db: Session, case: Case, context: CaseContext, key: str, data: dict) -> None:
    if key == "transcript_agent":
        _persist_transcripts(db, case, context, data)
    elif key == "claim_agent":
        _persist_claims(db, case, context, data)
    elif key == "evidence_agent":
        _persist_evidence(db, case, context, data)
    elif key == "relationship_agent":
        _persist_relationships(db, case, context, data)
    elif key == "conflict_agent":
        _persist_conflicts(db, case, context, data)
    elif key == "signal_agent":
        _persist_signals(db, case, data)
    elif key == "legal_research_agent":
        _persist_authorities(db, case, context, data)
    elif key == "citation_audit_agent":
        _persist_citations(db, case, context, data)


def _persist_transcripts(db: Session, case: Case, context: CaseContext, data: dict) -> None:
    for item in data.get("transcripts", []):
        row = db.scalar(
            select(Transcript).where(
                Transcript.case_id == case.id, Transcript.transcript_id == item["transcript_id"]
            )
        )
        if row is None:
            continue
        statements = []
        for i, st in enumerate(item.get("statements", []), start=1):
            statements.append(
                {
                    "statementId": f"S-{str(i).zfill(3)}",
                    "time": st.get("time", ""),
                    "speaker": st.get("speaker", ""),
                    "text": st.get("text", ""),
                    "marker": (
                        {"kind": st["marker"], "label": st["marker"].replace("_", " ").title()}
                        if st.get("marker") else None
                    ),
                    "location": {
                        "documentId": item.get("document_id") or "",
                        "page": st.get("page", 1),
                        "paragraph": st.get("paragraph", 1),
                        "quote": st.get("text", "")[:200],
                    },
                    "claimIds": [],
                    "evidenceIds": [],
                    "findingIds": [],
                }
            )
        row.speakers_json = dumps(item.get("speakers", []))
        row.statements_json = dumps(statements)
        # Update the in-memory context so later agents see the parsed statements.
        for tr in context.transcripts:
            if tr.get("transcript_id") == item["transcript_id"]:
                tr["statements"] = statements


def _persist_claims(db: Session, case: Case, context: CaseContext, data: dict) -> None:
    items = data.get("claims", [])
    context.claims = []
    for index, item in enumerate(items, start=1):
        source = item.get("source") or {}
        claim_id = seq_id("C", index)
        row = Claim(
            claim_id=claim_id,
            case_id=case.id,
            title=item.get("title") or item["text"][:70],
            claim_text=item["text"],
            claim_type=item.get("type", "STATEMENT"),
            speaker=item.get("speaker"),
            source_document_id=source.get("document_id"),
            source_page=source.get("page"),
            source_paragraph=source.get("paragraph"),
            source_quote=source.get("quote"),
            origin_note=item.get("origin_note"),
            status="needs_review",
            extraction_confidence=float(item.get("confidence", 0.6)),
            hearing_statement_ids=dumps([]),
        )
        db.add(row)
        context.claims.append(
            {
                "claim_id": claim_id,
                "text": item["text"],
                "type": item.get("type", "STATEMENT"),
                "confidence": item.get("confidence", 0.6),
                "source": {
                    "document_id": source.get("document_id"),
                    "page": source.get("page"),
                    "paragraph": source.get("paragraph"),
                },
            }
        )
        case_service.log_event(
            db, case.id, action="Claim extracted", object_type="claim", object_id=claim_id,
            actor="Claim Agent", actor_type="ai",
            details=(
                f"Source {source.get('document_id')} page {source.get('page')} "
                f"paragraph {source.get('paragraph')}."
            ),
            commit=False,
        )


def _persist_evidence(db: Session, case: Case, context: CaseContext, data: dict) -> None:
    items = data.get("evidence", [])
    context.evidence = []
    for index, item in enumerate(items, start=1):
        source = item.get("source") or {}
        evidence_id = seq_id("E", index)
        db.add(
            Evidence(
                evidence_id=evidence_id,
                case_id=case.id,
                evidence_type=item.get("type", "Document"),
                description=item["description"],
                source_document_id=source.get("document_id"),
                source_page=source.get("page"),
                source_paragraph=source.get("paragraph"),
                source_quote=source.get("quote"),
                item_date=item.get("item_date"),
            )
        )
        context.evidence.append(
            {
                "evidence_id": evidence_id,
                "type": item.get("type", "Document"),
                "description": item["description"],
                "source": {"document_id": source.get("document_id")},
            }
        )


def _persist_relationships(db: Session, case: Case, context: CaseContext, data: dict) -> None:
    items = data.get("relationships", [])
    context.relationships = items
    for index, item in enumerate(items, start=1):
        db.add(
            ClaimEvidence(
                relationship_id=seq_id("R", index, 3),
                case_id=case.id,
                claim_id=item["claim_ref"],
                evidence_id=item["evidence_ref"],
                relationship=item["relationship"],
                reason=item.get("reason", ""),
                assessment_signal=(
                    "Potential conflict — requires human verification."
                    if item["relationship"] == "CONFLICTS"
                    else "Assessment signal only."
                ),
            )
        )


def _persist_conflicts(db: Session, case: Case, context: CaseContext, data: dict) -> None:
    items = data.get("conflicts", [])
    context.conflicts = items
    existing = list(db.scalars(select(Finding.finding_id).where(Finding.case_id == case.id)))
    index = next_index(existing, "F")
    for item in items:
        finding_id = seq_id("F", index, 3)
        index += 1
        comparison = _comparison_for(db, case.id, item)
        db.add(
            Finding(
                finding_id=finding_id,
                case_id=case.id,
                kind="conflict",
                category=item["type"].replace("_", " ").title(),
                group_name="timeline" if item["type"] == "TEMPORAL_CONFLICT" else "evidence",
                priority="high" if item.get("severity") == "REVIEW_REQUIRED" else "medium",
                claim_id=item.get("claim_a"),
                title=f"Potential {item['type'].replace('_', ' ').lower()}",
                reason=item.get("description", ""),
                conflict_type=item["type"],
                comparison_json=dumps(comparison) if comparison else None,
                relationship_ids=dumps([]),
                evidence_ids=dumps([item["evidence_id"]] if item.get("evidence_id") else []),
                status="open",
            )
        )
        case_service.log_event(
            db, case.id, action="Potential conflict detected", object_type="finding",
            object_id=finding_id, actor="Conflict Agent", actor_type="ai",
            details=item.get("description", "")[:300], commit=False,
        )
    _persist_missing_sources(db, case, context, index)
    _recompute_signals(db, case, context)


def _comparison_for(db: Session, case_row_id: str, item: dict) -> dict | None:
    claim_a = db.scalar(
        select(Claim).where(Claim.case_id == case_row_id, Claim.claim_id == item.get("claim_a"))
    )
    if claim_a is None:
        return None
    side_a = {
        "label": claim_a.source_document_id or "Source A",
        "location": {
            "documentId": claim_a.source_document_id or "",
            "page": claim_a.source_page or 1,
            "paragraph": claim_a.source_paragraph or 1,
            "quote": claim_a.source_quote or "",
        },
        "excerpt": claim_a.source_quote or claim_a.claim_text,
        "value": claim_a.claim_text[:160],
        "time": "",
    }
    if item.get("claim_b"):
        claim_b = db.scalar(
            select(Claim).where(Claim.case_id == case_row_id, Claim.claim_id == item["claim_b"])
        )
        if claim_b is None:
            return None
        side_b = {
            "label": claim_b.source_document_id or "Source B",
            "location": {
                "documentId": claim_b.source_document_id or "",
                "page": claim_b.source_page or 1,
                "paragraph": claim_b.source_paragraph or 1,
                "quote": claim_b.source_quote or "",
            },
            "excerpt": claim_b.source_quote or claim_b.claim_text,
            "value": claim_b.claim_text[:160],
            "time": "",
        }
    elif item.get("evidence_id"):
        ev = db.scalar(
            select(Evidence).where(
                Evidence.case_id == case_row_id, Evidence.evidence_id == item["evidence_id"]
            )
        )
        if ev is None:
            return None
        side_b = {
            "label": f"{ev.evidence_type} · {ev.source_document_id or ''}".strip(" ·"),
            "location": {
                "documentId": ev.source_document_id or "",
                "page": ev.source_page or 1,
                "paragraph": ev.source_paragraph or 1,
                "quote": ev.source_quote or "",
            },
            "excerpt": ev.description,
            "value": ev.description[:160],
            "time": ev.item_date or "",
        }
    else:
        return None
    return {"a": side_a, "b": side_b}


def _persist_missing_sources(db: Session, case: Case, context: CaseContext, index: int) -> None:
    for claim in db.scalars(select(Claim).where(Claim.case_id == case.id)):
        if claim.source_document_id:
            continue
        finding_id = seq_id("F", index, 3)
        index += 1
        db.add(
            Finding(
                finding_id=finding_id,
                case_id=case.id,
                kind="missing_source",
                category="Missing source",
                group_name="evidence",
                priority="medium",
                claim_id=claim.claim_id,
                title="Claim has no resolvable source location",
                reason=(
                    "This claim could not be anchored to a page and paragraph in the uploaded "
                    "material. Requires human verification."
                ),
                relationship_ids=dumps([]),
                evidence_ids=dumps([]),
                status="open",
            )
        )


def _recompute_signals(db: Session, case: Case, context: CaseContext) -> None:
    from ai_engine.analysis import assessment_signals

    relationships = list(db.scalars(select(ClaimEvidence).where(ClaimEvidence.case_id == case.id)))
    evidence = {e.evidence_id: e for e in db.scalars(select(Evidence).where(Evidence.case_id == case.id))}
    conflicts_by_claim: dict[str, int] = {}
    for finding in db.scalars(select(Finding).where(Finding.case_id == case.id, Finding.kind == "conflict")):
        if finding.claim_id:
            conflicts_by_claim[finding.claim_id] = conflicts_by_claim.get(finding.claim_id, 0) + 1

    for claim in db.scalars(select(Claim).where(Claim.case_id == case.id)):
        support, conflict = [], []
        for rel in relationships:
            if rel.claim_id != claim.claim_id:
                continue
            ev = evidence.get(rel.evidence_id)
            if ev is None:
                continue
            entry = {"evidence_type": ev.evidence_type, "source_document_id": ev.source_document_id}
            if rel.relationship == "SUPPORTS":
                support.append(entry)
            elif rel.relationship == "CONFLICTS":
                conflict.append(entry)
        conflict.extend([{}] * conflicts_by_claim.get(claim.claim_id, 0))
        signals = assessment_signals(
            claim_text=claim.claim_text,
            supporting=support,
            conflicting=conflict,
            has_source=bool(claim.source_document_id),
            extraction_confidence=claim.extraction_confidence or 0.6,
        )
        signals["supportStrength"] = support_strength(signals)
        signals["conflictStrength"] = conflict_strength(signals)
        claim.signals_json = dumps(signals)
        if conflict:
            claim.status = "unresolved"


def _persist_authorities(db: Session, case: Case, context: CaseContext, data: dict) -> None:
    items = data.get("authorities", [])
    context.authorities = items
    for item in items:
        db.add(
            CaseAuthority(
                case_id=case.id,
                authority_id=item["authority_id"],
                claim_ids=dumps(item.get("claim_ids", [])),
                relevance=item.get("relevance"),
                why_retrieved=item.get("why_retrieved", ""),
                status=item.get("status", "verification_required"),
            )
        )
        case_service.log_event(
            db, case.id, action="Authority retrieved", object_type="authority",
            object_id=item["authority_id"], actor="Legal Research Agent", actor_type="ai",
            details="Retrieval signal only — the reviewer must verify relevance.", commit=False,
        )


def _persist_citations(db: Session, case: Case, context: CaseContext, data: dict) -> None:
    items = data.get("citations", [])
    context.citations = items
    existing = list(db.scalars(select(Finding.finding_id).where(Finding.case_id == case.id)))
    finding_index = next_index(existing, "F")
    for index, item in enumerate(items, start=1):
        source = item.get("source") or {}
        citation_id = seq_id("CIT", index, 3)
        db.add(
            Citation(
                citation_id=citation_id,
                case_id=case.id,
                claim_id=item.get("claim_id"),
                authority_id=item.get("authority_id"),
                source_document_id=source.get("document_id"),
                source_page=source.get("page"),
                source_paragraph=source.get("paragraph"),
                matched_passage=item.get("matched_passage", ""),
                result=item.get("result", "unable_to_map"),
                note=item.get("note", ""),
                requires_review=item.get("result") != "potentially_relevant",
            )
        )
        if item.get("result") != "potentially_relevant":
            finding_id = seq_id("F", finding_index, 3)
            finding_index += 1
            db.add(
                Finding(
                    finding_id=finding_id,
                    case_id=case.id,
                    kind="citation",
                    category="Citation audit",
                    group_name="citation",
                    priority="medium",
                    claim_id=item.get("claim_id"),
                    title="Citation requires review",
                    reason=item.get("note", ""),
                    authority_id=item.get("authority_id"),
                    relationship_ids=dumps([]),
                    evidence_ids=dumps([]),
                    status="open",
                )
            )
        case_service.log_event(
            db, case.id, action="Citation audited", object_type="claim",
            object_id=item.get("claim_id") or citation_id,
            actor="Citation Audit Agent", actor_type="ai",
            details=item.get("result", ""), commit=False,
        )


def _persist_signals(db: Session, case: Case, data: dict) -> None:  # pragma: no cover
    for claim_id, signals in data.get("signals", {}).items():
        row = db.scalar(select(Claim).where(Claim.case_id == case.id, Claim.claim_id == claim_id))
        if row:
            row.signals_json = dumps(signals)


def run_in_background(run_id: str, ui_settings: dict | None = None) -> None:
    """Entry point used by FastAPI BackgroundTasks."""
    asyncio.run(execute_run(run_id, ui_settings))
