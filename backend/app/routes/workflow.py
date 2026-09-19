"""Analysis pipeline, review workflow, research and reporting routes using PyMongo."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse

from ..config import settings
from ..database import get_db, get_collection
from ..models.case import Case, User
from ..models.review import Review
from ..repositories import (
    case_repository,
    counter_argument_repository,
    risk_item_repository,
    claim_repository,
    evidence_repository,
    relationship_repository,
    conflict_repository,
    authority_repository,
    citation_repository,
    review_repository,
    audit_repository,
    analysis_run_repository,
)
from ..services import analysis_service, case_service, report_service
from ..services.analysis_service import AnalysisBusy
from ..services.auth_service import get_current_user, owned_case
from ..services.authority_service import CorpusAuthorityService, load_corpus
from ..services.case_service import NotFound

analysis_router = APIRouter(prefix="/cases", tags=["analysis"])
system_router = APIRouter(prefix="/system", tags=["system"])


# ── analysis ──────────────────────────────────────────────────────────────────

@analysis_router.post("/{case_id}/analyze", status_code=202)
def start_analysis(
    background: BackgroundTasks,
    payload: dict = Body(default={}),
    case: Case = Depends(owned_case),
    user: User = Depends(get_current_user),
) -> dict:
    ui_settings = {
        "conflict_sensitivity": payload.get("conflictSensitivity", "balanced"),
        "authority_top_k": payload.get("authorityTopK", 5),
    }
    try:
        run = analysis_service.start_run(case, user.full_name, ui_settings)
    except AnalysisBusy as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    # The pipeline is synchronous and CPU/IO-blocking. Starlette runs a sync
    # background task in a worker thread, so the event loop stays free and no
    # running loop is required here (this endpoint itself is sync).
    background.add_task(analysis_service.execute_run, run.id, case.id, user.full_name)

    return {"runId": run.id, "status": run.status, "aiMode": run.ai_mode}


@analysis_router.get("/{case_id}/analysis")
def analysis_status(case: Case = Depends(owned_case)) -> dict:
    return analysis_service.get_analysis_status(case.id)


@analysis_router.get("/{case_id}/claims")
def list_claims(case: Case = Depends(owned_case)) -> list[dict]:
    claims = claim_repository.list_by_case(case.id)
    return [c.to_dict() for c in claims]


@analysis_router.get("/{case_id}/claims/{claim_id}")
def get_claim(claim_id: str, case: Case = Depends(owned_case)) -> dict:
    claim = claim_repository.get_by_id(claim_id, case_id=case.id)
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No claim was found for '{claim_id}'.")
    return claim.to_dict()


@analysis_router.get("/{case_id}/evidence")
def list_evidence(case: Case = Depends(owned_case)) -> list[dict]:
    evidence = evidence_repository.list_by_case(case.id)
    return [e.to_dict() for e in evidence]


@analysis_router.get("/{case_id}/relationships")
def list_relationships(case: Case = Depends(owned_case)) -> list[dict]:
    rels = relationship_repository.list_by_case(case.id)
    return [r.to_dict() for r in rels]


@analysis_router.get("/{case_id}/findings")
def list_findings(case: Case = Depends(owned_case)) -> list[dict]:
    conflicts = conflict_repository.list_by_case(case.id)
    return [c.to_dict() for c in conflicts]


@analysis_router.get("/{case_id}/conflicts")
def list_conflicts(case: Case = Depends(owned_case)) -> list[dict]:
    conflicts = conflict_repository.list_by_case(case.id)
    return [c.to_dict() for c in conflicts if c.kind == "conflict"]


# ── authorities & citations ───────────────────────────────────────────────────

@analysis_router.get("/{case_id}/authorities")
def case_authorities(case: Case = Depends(owned_case)) -> list[dict]:
    authorities = authority_repository.list_all()
    return [a.to_dict() for a in authorities]


@analysis_router.post("/{case_id}/authorities/search")
def search_authorities(
    payload: dict = Body(...),
    case: Case = Depends(owned_case),
) -> dict:
    service = CorpusAuthorityService()
    results = service.search(payload.get("query", ""), int(payload.get("limit", 5)))
    return {
        "corpusSize": service.size(),
        "results": results,
        "notice": (
            "Relevance is a retrieval/ranking signal only — never a measure of legal "
            "correctness. Every retrieved passage requires human verification."
        ),
    }


@analysis_router.get("/{case_id}/citations")
def list_citations(case: Case = Depends(owned_case)) -> list[dict]:
    """Citation findings exactly as the AuthorityCitationAgent produced them,
    including the full source provenance behind each verification result."""
    citations = citation_repository.list_by_case(case.id)
    return [c.to_dict() for c in citations]


@analysis_router.get("/{case_id}/counter-arguments")
def list_counter_arguments(case: Case = Depends(owned_case)) -> list[dict]:
    items = counter_argument_repository.list_by_case(case.id)
    return [i.to_dict() for i in items]


@analysis_router.get("/{case_id}/risks")
def list_risk_items(case: Case = Depends(owned_case)) -> list[dict]:
    items = risk_item_repository.list_by_case(case.id)
    return [i.to_dict() for i in items]


# ── review & audit ────────────────────────────────────────────────────────────

@analysis_router.post("/{case_id}/findings/{finding_id}/review")
def save_review(
    finding_id: str,
    payload: dict = Body(...),
    case: Case = Depends(owned_case),
    user: User = Depends(get_current_user),
) -> dict:
    finding_type = payload.get("finding_type", "CLAIM")
    try:
        review, event = report_service.save_review(
            case,
            user,
            finding_id,
            payload.get("decision", ""),
            payload.get("comment", "") or "",
            finding_type=finding_type,
        )
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {
        "review": review.to_dict(),
        "auditLog": event.to_dict(),
    }


@analysis_router.get("/{case_id}/reviews")
def list_reviews(case: Case = Depends(owned_case)) -> list[dict]:
    reviews = review_repository.list_by_case(case.id)
    return [r.to_dict() for r in reviews]


@analysis_router.get("/{case_id}/audit")
def list_audit(case: Case = Depends(owned_case)) -> list[dict]:
    events = audit_repository.list_by_case(case.id)
    return [e.to_dict() for e in events]


@analysis_router.post("/{case_id}/audit")
def append_audit(
    payload: dict = Body(...),
    case: Case = Depends(owned_case),
    user: User = Depends(get_current_user),
) -> dict:
    event = case_service.log_event(
        case.id,
        action=payload.get("action", "Reviewer action"),
        object_type=payload.get("objectType", "case"),
        object_id=payload.get("objectId", case.case_id),
        actor=user.full_name,
        actor_type="reviewer",
        details=payload.get("details"),
        previous_state=payload.get("previousState"),
        new_state=payload.get("newState"),
    )
    return event.to_dict()


# ── system ────────────────────────────────────────────────────────────────────

@system_router.get("/status")
def system_status() -> dict:
    try:
        get_db().command("ping")
        database = "connected"
    except Exception:
        database = "error"
    corpus = CorpusAuthorityService().size()
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
def reload_authorities(user: User = Depends(get_current_user)) -> dict:
    count = load_corpus(settings.authority_corpus_dir)
    return {"loaded": count, "corpusSize": CorpusAuthorityService().size()}
