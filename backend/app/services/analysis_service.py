"""Analysis service: runs a case through the five-agent LangGraph pipeline and
persists the validated results through the MongoDB repositories.

    FastAPI route
        -> start_run()            create the AnalysisRun, return immediately
        -> execute_run()          (background) build state, run the graph,
                                  persist, complete the run

`AnalysisRun` is execution metadata only. The workflow state is
`agents.graph.NyayaSahayakState`, which lives entirely inside the pipeline;
the two are translated at the boundary and never conflated.
"""
from __future__ import annotations

import logging
from datetime import datetime

from ..agents_bridge import build_state, evidence_from_documents, persist_pipeline_output, run_graph
from ..models.audit import AnalysisRun
from ..models.case import Case
from ..repositories import (
    analysis_run_repository,
    authority_repository,
    case_repository,
    document_repository,
    evidence_repository,
)
from . import case_service

log = logging.getLogger("nyayasahayak.analysis")

RUNNING_STATES = ("running",)

# Progress markers for the UI. The pipeline reports real stage outcomes in the
# run summary; these numbers only drive a progress bar.
_STAGE_MESSAGES = (
    (10, "Preparing case material..."),
    (25, "Running the five-agent pipeline..."),
    (85, "Persisting validated findings..."),
    (100, "Analysis completed."),
)


class AnalysisBusy(Exception):
    pass


def current_run(case_row_id: str) -> AnalysisRun | None:
    return analysis_run_repository.get_latest_by_case(case_row_id)


def _update(run: AnalysisRun, *, progress: int, message: str, stage_index: int | None = None) -> AnalysisRun:
    run.progress = progress
    run.message = message
    if stage_index is not None:
        run.stage_index = stage_index
    analysis_run_repository.update(run)
    return run


def start_run(case: Case, actor: str, ui_settings: dict | None = None) -> AnalysisRun:
    """Create the run row. Execution happens in `execute_run`, which the route
    schedules as a background task — no event loop is touched here, so this is
    safe to call from a synchronous endpoint.
    """
    existing = current_run(case.id)
    if existing and existing.status in RUNNING_STATES:
        raise AnalysisBusy("An analysis is already running for this case.")

    docs = document_repository.list_by_case(case.id)
    if not docs:
        raise ValueError("Upload at least one document or transcript before running an analysis.")

    from ..config import settings

    run = AnalysisRun(
        case_id=case.id,
        status="running",
        stage_index=0,
        progress=5,
        message="Initializing pipeline...",
        ai_mode="gemini" if settings.ai_configured else "unavailable",
        started_at=datetime.utcnow().isoformat(),
        summary_json={"ui_settings": ui_settings or {}},
    )
    analysis_run_repository.create(run)

    case_service.set_status(case, "ANALYZING", actor=actor)
    case.last_analyzed = datetime.utcnow().isoformat()
    case_repository.update(case)

    case_service.log_event(
        case.id,
        action="Analysis started",
        object_type="analysis",
        object_id=run.id,
        actor=actor,
        actor_type="reviewer",
        details="Pipeline execution initiated.",
    )
    return run


def execute_run(run_id: str, case_row_id: str, actor: str = "System") -> AnalysisRun | None:
    """Run the pipeline to completion. Blocking; intended for a worker thread.

    Every failure path ends with the run marked `failed` and the error stored,
    because a run that silently reports `completed` after doing nothing is the
    one outcome this service must never produce.
    """
    raw = analysis_run_repository.find_one({"id": run_id})
    if not raw:
        log.error("Analysis run %s no longer exists.", run_id)
        return None
    run = AnalysisRun.from_dict(raw)

    case = case_repository.get_by_id(case_row_id)
    if case is None:
        return _fail(run, "The case no longer exists.")

    try:
        _update(run, progress=_STAGE_MESSAGES[0][0], message=_STAGE_MESSAGES[0][1], stage_index=0)

        documents = document_repository.list_by_case(case.id)
        if not documents:
            return _fail(run, "No documents are attached to this case.")

        # Evidence segmentation is the caller's responsibility, not an agent's.
        evidence = evidence_repository.list_by_case(case.id)
        if not evidence:
            evidence = evidence_from_documents(documents)
            for item in evidence:
                evidence_repository.create(item)

        authorities = authority_repository.list_all(limit=500)

        state = build_state(
            case_public_id=case.case_id or case.id,
            documents=documents,
            evidence=evidence,
            authorities=authorities,
        )

        _update(run, progress=_STAGE_MESSAGES[1][0], message=_STAGE_MESSAGES[1][1], stage_index=1)

        final_state = run_graph(state)

        _update(run, progress=_STAGE_MESSAGES[2][0], message=_STAGE_MESSAGES[2][1], stage_index=4)

        summary = persist_pipeline_output(
            final_state, case_row_id=case.id, run_id=run.id, actor=actor
        )

        run.status = "completed"
        run.progress = _STAGE_MESSAGES[3][0]
        run.stage_index = 5
        run.message = (
            "Analysis completed with warnings."
            if summary["degraded"]
            else _STAGE_MESSAGES[3][1]
        )
        run.summary_json = {**(run.summary_json or {}), **summary}
        run.error = "; ".join(summary["errors"]) or None
        run.completed_at = datetime.utcnow().isoformat()
        analysis_run_repository.update(run)

        case_service.set_status(case, "ACTIVE_REVIEW", actor=actor)
        case_service.log_event(
            case.id,
            action="Analysis completed",
            object_type="analysis",
            object_id=run.id,
            actor=actor,
            actor_type="system",
            details={
                "counts": summary["counts"],
                "stages": summary["stages"],
                "degraded": summary["degraded"],
            },
        )
        return run

    except Exception as exc:  # noqa: BLE001 - recorded on the run, then re-read by the UI
        log.exception("Pipeline run %s failed: %s", run_id, exc)
        return _fail(run, f"{type(exc).__name__}: {exc}", case_row_id=case_row_id, actor=actor)


def _fail(run: AnalysisRun, message: str, case_row_id: str | None = None, actor: str = "System") -> AnalysisRun:
    run.status = "failed"
    run.error = message
    run.message = "Analysis failed."
    run.completed_at = datetime.utcnow().isoformat()
    analysis_run_repository.update(run)
    if case_row_id:
        case_service.log_event(
            case_row_id,
            action="Analysis failed",
            object_type="analysis",
            object_id=run.id,
            actor=actor,
            actor_type="system",
            details=message,
        )
    return run


def get_analysis_status(case_row_id: str) -> dict:
    run = current_run(case_row_id)
    if not run:
        return {"status": "none", "progress": 0, "message": "No analysis has been run yet."}
    return run.to_dict()
