"""Analysis pipeline, review workflow, research and reporting routes."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import (
    AgentRun, Authority, CaseAuthority, Case, Citation, Claim, ClaimEvidence,
    Evidence, Finding, Report, Review, ToolCall, User,
)
from ..services import analysis_service, case_service, report_service
from ..services.analysis_service import AnalysisBusy
from ..services.auth_service import get_current_user, owned_case
from ..services.authority_service import CorpusAuthorityService, load_corpus
from ..services.case_service import NotFound
from ..utils.serialize import (
    agent_run_out, audit_out, authority_out, citation_out, claim_out, evidence_out,
    finding_out, loads, relationship_out, report_out, review_out, tool_call_out,
)

analysis_router = APIRouter(prefix="/cases", tags=["analysis"])
system_router = APIRouter(prefix="/system", tags=["system"])


# ── analysis ──────────────────────────────────────────────────────────────────

@analysis_router.post("/{case_id}/analyze", status_code=202)
def start_analysis(
    background: BackgroundTasks,
    payload: dict = Body(default={}),
    case: Case = Depends(owned_case),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    ui_settings = {
        "conflict_sensitivity": payload.get("conflictSensitivity", "balanced"),
        "authority_top_k": payload.get("authorityTopK", 5),
    }
    try:
        run = analysis_service.start_run(db, case, user.full_name, ui_settings)
    except AnalysisBusy as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    background.add_task(analysis_service.run_in_background, run.id, ui_settings)
    return {"runId": run.id, "status": run.status, "aiMode": run.ai_mode}


@analysis_router.get("/{case_id}/analysis")
def analysis_status(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> dict:
    run = analysis_service.current_run(db, case.id)
    agents = list(
        db.scalars(select(AgentRun).where(AgentRun.case_id == case.id).order_by(AgentRun.run_id))
    )
    stages = [{"key": k, "label": label} for k, label in analysis_service.PIPELINE_STAGES]
    if run is None:
        return {"status": "idle", "stageIndex": 0, "progress": 0, "stages": stages,
                "agents": [], "summary": None, "aiMode": None, "message": ""}
    return {
        "runId": run.id,
        "status": run.status,
        "stageIndex": run.stage_index,
        "progress": run.progress,
        "message": run.message or "",
        "error": run.error,
        "aiMode": run.ai_mode,
        "startedAt": run.started_at.strftime("%Y-%m-%dT%H:%M:%S") if run.started_at else None,
        "completedAt": run.completed_at.strftime("%Y-%m-%dT%H:%M:%S") if run.completed_at else None,
        "stages": stages,
        "agents": [agent_run_out(a) for a in agents],
        "summary": loads(run.summary_json, None),
    }


@analysis_router.get("/{case_id}/agent-runs")
def agent_runs(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    return [
        agent_run_out(a)
        for a in db.scalars(
            select(AgentRun).where(AgentRun.case_id == case.id).order_by(AgentRun.run_id)
        )
    ]


@analysis_router.get("/{case_id}/tool-calls")
def tool_calls(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(
        select(ToolCall).where(ToolCall.case_id == case.case_id).order_by(ToolCall.created_at.desc())
    )
    return [tool_call_out(t) for t in list(rows)[:50]]


# ── derived data ──────────────────────────────────────────────────────────────

@analysis_router.get("/{case_id}/claims")
def list_claims(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    return [
        claim_out(c)
        for c in db.scalars(select(Claim).where(Claim.case_id == case.id).order_by(Claim.claim_id))
    ]


@analysis_router.get("/{case_id}/claims/{claim_id}")
def get_claim(claim_id: str, case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> dict:
    claim = db.scalar(select(Claim).where(Claim.case_id == case.id, Claim.claim_id == claim_id))
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No claim was found for '{claim_id}'.")
    return claim_out(claim)


@analysis_router.get("/{case_id}/evidence")
def list_evidence(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    return [
        evidence_out(e)
        for e in db.scalars(
            select(Evidence).where(Evidence.case_id == case.id).order_by(Evidence.evidence_id)
        )
    ]


@analysis_router.get("/{case_id}/relationships")
def list_relationships(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    return [
        relationship_out(r)
        for r in db.scalars(select(ClaimEvidence).where(ClaimEvidence.case_id == case.id))
    ]


@analysis_router.get("/{case_id}/findings")
def list_findings(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    return [
        finding_out(f)
        for f in db.scalars(
            select(Finding).where(Finding.case_id == case.id).order_by(Finding.finding_id)
        )
    ]


@analysis_router.get("/{case_id}/conflicts")
def list_conflicts(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    return [
        finding_out(f)
        for f in db.scalars(
            select(Finding).where(Finding.case_id == case.id, Finding.kind == "conflict")
            .order_by(Finding.finding_id)
        )
    ]


@analysis_router.get("/{case_id}/timeline")
def timeline(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    return report_service.build_timeline(db, case)


# ── authorities & citations ───────────────────────────────────────────────────

@analysis_router.get("/{case_id}/authorities")
def case_authorities(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    links = list(db.scalars(select(CaseAuthority).where(CaseAuthority.case_id == case.id)))
    rows = {
        a.authority_id: a
        for a in db.scalars(
            select(Authority).where(Authority.authority_id.in_([l.authority_id for l in links] or [""]))
        )
    }
    return [authority_out(rows[l.authority_id], l) for l in links if l.authority_id in rows]


@analysis_router.post("/{case_id}/authorities/search")
def search_authorities(
    payload: dict = Body(...),
    case: Case = Depends(owned_case),
    db: Session = Depends(get_db),
) -> dict:
    service = CorpusAuthorityService(db)
    results = service.search(payload.get("query", ""), int(payload.get("limit", 5)))
    return {
        "corpusSize": service.size(),
        "results": results,
        "notice": (
            "Relevance is a retrieval/ranking signal only — never a measure of legal "
            "correctness. Every retrieved passage requires human verification."
        ),
    }


@analysis_router.post("/{case_id}/authorities/{authority_id}/link")
def link_authority(
    authority_id: str,
    payload: dict = Body(...),
    case: Case = Depends(owned_case),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    row = db.scalar(select(Authority).where(Authority.authority_id == authority_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No authority '{authority_id}' in the corpus.")
    claim_id = payload.get("claimId")
    link = db.scalar(
        select(CaseAuthority).where(
            CaseAuthority.case_id == case.id, CaseAuthority.authority_id == authority_id
        )
    )
    if link is None:
        link = CaseAuthority(
            case_id=case.id, authority_id=authority_id, claim_ids="[]",
            why_retrieved="Linked manually by the reviewer.", status="verification_required",
        )
        db.add(link)
    claim_ids = loads(link.claim_ids, [])
    if claim_id and claim_id not in claim_ids:
        claim_ids.append(claim_id)
    link.claim_ids = __import__("json").dumps(claim_ids)
    case_service.log_event(
        db, case.id, action="Authority linked to claim", object_type="authority",
        object_id=authority_id, actor=user.full_name, actor_type="reviewer",
        details=f"Linked to {claim_id}", commit=False,
    )
    db.commit()
    db.refresh(link)
    return authority_out(row, link)


@analysis_router.get("/{case_id}/citations")
def list_citations(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    return [citation_out(c) for c in db.scalars(select(Citation).where(Citation.case_id == case.id))]


# ── review & audit ────────────────────────────────────────────────────────────

@analysis_router.post("/{case_id}/findings/{finding_id}/review")
def save_review(
    finding_id: str,
    payload: dict = Body(...),
    case: Case = Depends(owned_case),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        finding, review, events = report_service.save_review(
            db, case, user, finding_id,
            payload.get("decision", ""), payload.get("comment", "") or "",
        )
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {
        "finding": finding_out(finding),
        "review": review_out(review),
        "auditLogs": [audit_out(e, case.case_id) for e in events],
    }


@analysis_router.get("/{case_id}/reviews")
def list_reviews(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    return [review_out(r) for r in db.scalars(select(Review).where(Review.case_id == case.id))]


@analysis_router.get("/{case_id}/audit")
def list_audit(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    return [audit_out(a, case.case_id) for a in case_service.list_audit(db, case.id)]


@analysis_router.post("/{case_id}/audit")
def append_audit(
    payload: dict = Body(...),
    case: Case = Depends(owned_case),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    event = case_service.log_event(
        db, case.id,
        action=payload.get("action", "Reviewer action"),
        object_type=payload.get("objectType", "case"),
        object_id=payload.get("objectId", case.case_id),
        actor=user.full_name, actor_type="reviewer",
        details=payload.get("details"),
        previous_state=payload.get("previousState"),
        new_state=payload.get("newState"),
    )
    return audit_out(event, case.case_id)


# ── reports ───────────────────────────────────────────────────────────────────

@analysis_router.get("/{case_id}/reports")
def list_reports(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Report).where(Report.case_id == case.id).order_by(Report.created_at.desc()))
    return [report_out(r) for r in rows]


@analysis_router.post("/{case_id}/report", status_code=201)
def create_report(
    payload: dict = Body(default={}),
    case: Case = Depends(owned_case),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    report = report_service.generate_report(db, case, user, bool(payload.get("redactPii")))
    return report_out(report)


@analysis_router.get("/{case_id}/report")
def report_preview(
    redactPii: bool = Query(False),
    case: Case = Depends(owned_case),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return report_service.report_payload(db, case, user, redactPii)


@analysis_router.get("/{case_id}/report/{report_id}/pdf")
def report_pdf(report_id: str, case: Case = Depends(owned_case),
               db: Session = Depends(get_db)) -> FileResponse:
    report = db.scalar(select(Report).where(Report.case_id == case.id, Report.report_id == report_id))
    if report is None or not report.file_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No PDF is available for this report.")
    return FileResponse(report.file_path, media_type="application/pdf",
                        filename=f"{case.case_id}-{report_id}.pdf")


@analysis_router.get("/{case_id}/report/{report_id}/json")
def report_json(report_id: str, case: Case = Depends(owned_case),
                db: Session = Depends(get_db)) -> FileResponse:
    report = db.scalar(select(Report).where(Report.case_id == case.id, Report.report_id == report_id))
    if report is None or not report.json_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No JSON export is available for this report.")
    return FileResponse(report.json_path, media_type="application/json",
                        filename=f"{case.case_id}-{report_id}.json")


# ── system ────────────────────────────────────────────────────────────────────

@system_router.get("/status")
def system_status(db: Session = Depends(get_db)) -> dict:
    from sqlalchemy import text

    try:
        db.execute(text("SELECT 1"))
        database = "connected"
    except Exception:  # noqa: BLE001
        database = "error"
    corpus = CorpusAuthorityService(db).size()
    return {
        "api": "online",
        "database": database,
        "aiProvider": {
            "name": settings.ai_provider,
            "model": settings.ai_model if settings.ai_configured else "",
            "state": "ready" if settings.ai_configured else "not_configured",
            "note": (
                "Gemini Flash is configured."
                if settings.ai_configured
                else "No API key configured — deterministic extraction only."
            ),
        },
        "mcpServer": {"name": settings.mcp_server_name, "tools": 7, "state": "available"},
        "authorityIndex": {
            "records": corpus,
            "state": "ready" if corpus else "empty",
            "note": (
                "Curated corpus loaded."
                if corpus
                else "The authority corpus is empty. Add verified records to legal_data/authorities/."
            ),
        },
    }


@system_router.post("/authorities/reload")
def reload_authorities(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    count = load_corpus(db, settings.authority_corpus_dir)
    return {"loaded": count, "corpusSize": CorpusAuthorityService(db).size()}


@system_router.get("/search")
def global_search(
    q: str = Query("", min_length=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Cross-case search over the signed-in user's own material only."""
    query = q.strip().lower()
    results: dict[str, list[dict]] = {"cases": [], "documents": [], "claims": [], "evidence": []}
    if len(query) < 2:
        return results
    cases = case_service.list_cases(db, user)
    case_ids = {c.id: c for c in cases}
    for c in cases:
        if query in (c.name or "").lower() or query in c.case_id.lower():
            results["cases"].append({"id": c.case_id, "label": c.name, "caseId": c.case_id})
    for claim in db.scalars(select(Claim).where(Claim.case_id.in_(list(case_ids) or [""]))):
        if query in (claim.claim_text or "").lower():
            results["claims"].append({
                "id": claim.claim_id, "label": claim.claim_text[:120],
                "caseId": case_ids[claim.case_id].case_id,
            })
    for ev in db.scalars(select(Evidence).where(Evidence.case_id.in_(list(case_ids) or [""]))):
        if query in (ev.description or "").lower():
            results["evidence"].append({
                "id": ev.evidence_id, "label": ev.description[:120],
                "caseId": case_ids[ev.case_id].case_id,
            })
    from ..models import Document

    for doc in db.scalars(select(Document).where(Document.case_id.in_(list(case_ids) or [""]))):
        if query in (doc.filename or "").lower():
            results["documents"].append({
                "id": doc.document_id, "label": doc.filename,
                "caseId": case_ids[doc.case_id].case_id,
            })
    for key in results:
        results[key] = results[key][:8]
    return results
