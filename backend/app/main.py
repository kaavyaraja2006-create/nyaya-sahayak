"""NyayaSahayak FastAPI application."""
from __future__ import annotations

import logging
import sys
import time
import uuid
from pathlib import Path

# Make the repository root importable so `agents` and `ai_engine` resolve.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .database import init_db, session_scope
from .routes.core import auth_router, case_router
from .routes.workflow import analysis_router, system_router
from .services.authority_service import load_corpus

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("nyayasahayak")

app = FastAPI(
    title="NyayaSahayak API",
    version="1.0.0",
    description=(
        "Human-in-the-loop legal evidence audit and research platform. "
        "The system organises, traces and compares case material; it does not determine "
        "guilt, innocence, liability, credibility, admissibility or judicial outcome."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("request_id=%s path=%s unhandled error", request_id, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR",
                               "message": "Something went wrong. Please try again."}},
        )
    latency = int((time.perf_counter() - started) * 1000)
    log.info("request_id=%s %s %s -> %s (%sms)", request_id, request.method,
             request.url.path, response.status_code, latency)
    response.headers["X-Request-ID"] = request_id
    return response


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    db = session_scope()
    try:
        count = load_corpus(db, settings.authority_corpus_dir)
        if count == 0:
            log.info(
                "Authority corpus is empty — authority retrieval will report no matches. "
                "Add verified records to %s", settings.authority_corpus_dir,
            )
    finally:
        db.close()
    log.info(
        "NyayaSahayak API ready. AI provider=%s configured=%s",
        settings.ai_provider, settings.ai_configured,
    )


@app.get("/api/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "service": settings.app_name}


app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(case_router, prefix=settings.api_prefix)
app.include_router(analysis_router, prefix=settings.api_prefix)
app.include_router(system_router, prefix=settings.api_prefix)
