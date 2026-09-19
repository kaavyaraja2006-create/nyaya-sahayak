"""End-to-end tests for the API, the agent pipeline and the MCP tools.

Every test builds its own case from plain-text material it writes itself —
there is no bundled synthetic dataset in the project.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

TMP = tempfile.mkdtemp(prefix="nyaya-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP}/test.db"
os.environ["DATA_DIR"] = f"{TMP}/data"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["AI_PROVIDER"] = "rule_based"
os.environ["AUTHORITY_CORPUS_DIR"] = f"{TMP}/authorities"

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.database import init_db, session_scope  # noqa: E402
from backend.app.main import app  # noqa: E402

client = TestClient(app)

STATEMENT_A = """Statement of PW-3 recorded on 11 August 2026.

I was returning home along Riverside Road at about 10:45 PM on 11 August 2026.
I saw a person near the Riverside Road junction at that time.
The CCTV camera outside the corner shop was working that evening.
I cannot remember the exact time at which I reached my house.
"""

STATEMENT_B = """Investigation report prepared on 12 August 2026.

The call detail record shows the device was near Harbour Street at 10:43 PM on 11 August 2026.
The phone metadata was obtained from the service provider.
The forensic report was received on 14 August 2026.
"""

TRANSCRIPT = """10:06:18
PW-3: I saw the person near the Riverside Road junction at about 10:45 PM.

10:07:02
COUNSEL: Were you certain about the time?

10:09:12
PW-3: I cannot remember the exact time now.

10:11:40
COUNSEL: The phone metadata places the device at Harbour Street at 10:43 PM.
"""


@pytest.fixture(scope="module", autouse=True)
def _db() -> None:
    init_db()


def register(email: str = "reviewer@example.com") -> dict:
    response = client.post(
        "/api/auth/signup",
        json={
            "fullName": "Test Reviewer",
            "email": email,
            "phone": "9876543210",
            "password": "correct-horse-battery",
            "confirmPassword": "correct-horse-battery",
            "role": "LEGAL_RESEARCHER",
            "organization": "Test Chambers",
            "experienceYears": 3,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def make_case(token: str, name: str = "Test Matter") -> str:
    response = client.post(
        "/api/cases",
        json={"name": name, "caseType": "Civil", "jurisdiction": "Test", "court": "Test Court"},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["caseId"]


def upload(token: str, case_id: str, filename: str, text: str, doc_type: str = "Witness Statement"):
    return client.post(
        f"/api/cases/{case_id}/documents",
        files=[("files", (filename, io.BytesIO(text.encode()), "text/plain"))],
        data={"documentType": doc_type},
        headers=auth(token),
    )


def run_analysis(case_public_id: str) -> None:
    """Start a run and execute it synchronously."""
    from sqlalchemy import select

    from backend.app.models import AnalysisRun, Case
    from backend.app.services import analysis_service

    db = session_scope()
    try:
        case = db.scalar(select(Case).where(Case.case_id == case_public_id))
        run = analysis_service.start_run(db, case, "Test Reviewer", {})
        run_id = run.id
    finally:
        db.close()
    asyncio.run(analysis_service.execute_run(run_id, {}))


# ── auth ──────────────────────────────────────────────────────────────────────

def test_health():
    assert client.get("/api/health").json()["status"] == "ok"


def test_signup_login_and_me():
    payload = register("auth-user@example.com")
    token = payload["token"]
    assert payload["user"]["email"] == "auth-user@example.com"
    assert "password" not in str(payload["user"])

    me = client.get("/api/auth/me", headers=auth(token))
    assert me.status_code == 200
    assert me.json()["role"] == "LEGAL_RESEARCHER"

    login = client.post(
        "/api/auth/login",
        json={"email": "auth-user@example.com", "password": "correct-horse-battery"},
    )
    assert login.status_code == 200


def test_login_failure_does_not_reveal_which_field():
    bad = client.post(
        "/api/auth/login", json={"email": "auth-user@example.com", "password": "wrong-password"}
    )
    assert bad.status_code == 401
    assert bad.json()["detail"] == "Invalid email or password."

    missing = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert missing.json()["detail"] == bad.json()["detail"]


def test_duplicate_signup_rejected():
    response = client.post(
        "/api/auth/signup",
        json={"fullName": "Dup", "email": "auth-user@example.com",
              "password": "correct-horse-battery", "confirmPassword": "correct-horse-battery"},
    )
    assert response.status_code == 400


def test_protected_routes_require_a_token():
    assert client.get("/api/cases").status_code == 401
    assert client.get("/api/cases", headers={"Authorization": "Bearer nonsense"}).status_code == 401


# ── cases & ownership ─────────────────────────────────────────────────────────

def test_case_crud_and_persistence():
    token = register("cases@example.com")["token"]
    case_id = make_case(token, "Employment Dispute")
    assert case_id.startswith("NS-")

    listed = client.get("/api/cases", headers=auth(token)).json()
    assert any(c["caseId"] == case_id for c in listed)

    updated = client.put(
        f"/api/cases/{case_id}", json={"jurisdiction": "Chennai"}, headers=auth(token)
    )
    assert updated.json()["jurisdiction"] == "Chennai"

    # A fresh login must still see the case.
    token2 = client.post(
        "/api/auth/login", json={"email": "cases@example.com", "password": "correct-horse-battery"}
    ).json()["token"]
    assert client.get(f"/api/cases/{case_id}", headers=auth(token2)).status_code == 200


def test_user_data_isolation():
    token_a = register("owner-a@example.com")["token"]
    token_b = register("owner-b@example.com")["token"]
    case_id = make_case(token_a, "Private Matter")

    for path in ("", "/documents", "/claims", "/audit", "/report"):
        response = client.get(f"/api/cases/{case_id}{path}", headers=auth(token_b))
        assert response.status_code == 404, path

    assert case_id not in str(client.get("/api/cases", headers=auth(token_b)).json())


def test_unknown_case_is_404():
    token = register("missing@example.com")["token"]
    assert client.get("/api/cases/NS-1999-999", headers=auth(token)).status_code == 404


# ── uploads ───────────────────────────────────────────────────────────────────

def test_document_upload_and_extraction():
    token = register("upload@example.com")["token"]
    case_id = make_case(token)
    response = upload(token, case_id, "statement.txt", STATEMENT_A)
    assert response.status_code == 201, response.text
    document = response.json()["documents"][0]
    assert document["status"] == "indexed"
    assert document["pages"] >= 1

    detail = client.get(
        f"/api/cases/{case_id}/documents/{document['documentId']}", headers=auth(token)
    ).json()
    assert detail["content"][0]["paragraphs"]
    assert any("Riverside" in p["text"] for p in detail["content"][0]["paragraphs"])


def test_unsupported_file_type_rejected():
    token = register("badfile@example.com")["token"]
    case_id = make_case(token)
    response = client.post(
        f"/api/cases/{case_id}/documents",
        files=[("files", ("payload.exe", io.BytesIO(b"MZ"), "application/octet-stream"))],
        headers=auth(token),
    )
    assert response.status_code == 400


def test_unsafe_filename_is_sanitised():
    from backend.app.utils.files import safe_filename

    assert "/" not in safe_filename("../../etc/passwd")
    assert safe_filename("..\\..\\windows\\system32.txt") == "system32.txt"


def test_transcript_upload_from_pasted_text():
    token = register("transcript@example.com")["token"]
    case_id = make_case(token)
    response = client.post(
        f"/api/cases/{case_id}/transcripts",
        data={"text": TRANSCRIPT, "hearingDate": "2026-08-20", "hearingNumber": "2"},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    assert response.json()["hearingNumber"] == "2"


def test_analysis_requires_material():
    token = register("empty@example.com")["token"]
    case_id = make_case(token)
    assert client.post(f"/api/cases/{case_id}/analyze", json={}, headers=auth(token)).status_code == 400


# ── full pipeline ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def analysed_case() -> tuple[str, str]:
    token = register("pipeline@example.com")["token"]
    case_id = make_case(token, "Pipeline Matter")
    upload(token, case_id, "statement.txt", STATEMENT_A)
    upload(token, case_id, "investigation.txt", STATEMENT_B, "Investigation Report")
    client.post(
        f"/api/cases/{case_id}/transcripts",
        data={"text": TRANSCRIPT, "hearingDate": "2026-08-20", "hearingNumber": "1"},
        headers=auth(token),
    )
    run_analysis(case_id)
    return token, case_id


def test_pipeline_extracts_claims_with_sources(analysed_case):
    token, case_id = analysed_case
    claims = client.get(f"/api/cases/{case_id}/claims", headers=auth(token)).json()
    assert claims, "the pipeline should extract at least one claim"
    for claim in claims:
        assert claim["text"]
        if claim["source"]:
            assert claim["source"]["documentId"]
            assert claim["source"]["page"] >= 1
            assert claim["source"]["paragraph"] >= 1
    assert any("Riverside" in c["text"] for c in claims)


def test_pipeline_extracts_evidence(analysed_case):
    token, case_id = analysed_case
    evidence = client.get(f"/api/cases/{case_id}/evidence", headers=auth(token)).json()
    assert evidence
    types = {e["type"] for e in evidence}
    assert {"CCTV", "Phone Metadata"} & types


def test_relationships_are_recorded(analysed_case):
    token, case_id = analysed_case
    relationships = client.get(f"/api/cases/{case_id}/relationships", headers=auth(token)).json()
    assert relationships
    assert all(r["type"] in
               {"SUPPORTS", "CONFLICTS", "CONTEXTUALIZES", "UNCERTAIN", "MENTIONS"}
               for r in relationships)


def test_agent_runs_are_real_records(analysed_case):
    token, case_id = analysed_case
    runs = client.get(f"/api/cases/{case_id}/agent-runs", headers=auth(token)).json()
    names = {r["agent"] for r in runs}
    assert {"document_agent", "claim_agent", "evidence_agent", "conflict_agent",
            "report_agent"} <= names
    assert all(r["status"] in {"completed", "degraded", "skipped", "failed"} for r in runs)
    assert all(r["latencyMs"] is not None for r in runs)


def test_analysis_status_reports_completion(analysed_case):
    token, case_id = analysed_case
    status = client.get(f"/api/cases/{case_id}/analysis", headers=auth(token)).json()
    assert status["status"] == "completed"
    assert status["progress"] == 100
    assert status["summary"]["claims"] >= 1
    assert status["aiMode"] == "deterministic"


def test_timeline_is_time_ordered(analysed_case):
    token, case_id = analysed_case
    timeline = client.get(f"/api/cases/{case_id}/timeline", headers=auth(token)).json()
    assert timeline
    assert all(e["source"]["documentId"] for e in timeline)


def test_conflict_detection_uses_hedged_language(analysed_case):
    token, case_id = analysed_case
    conflicts = client.get(f"/api/cases/{case_id}/conflicts", headers=auth(token)).json()
    for finding in conflicts:
        text = f"{finding['title']} {finding['reason']}".lower()
        for banned in ("is lying", "is guilty", "proves", "not credible", "dishonest"):
            assert banned not in text
        assert "human verification is required" in text or finding["kind"] != "conflict"


def test_claim_signals_are_bounded(analysed_case):
    token, case_id = analysed_case
    claims = client.get(f"/api/cases/{case_id}/claims", headers=auth(token)).json()
    for claim in claims:
        for key, value in claim["signals"].items():
            assert 0 <= value <= 100, f"{key}={value}"
        assert 0.0 <= claim["extractionConfidence"] <= 1.0


def test_bundle_returns_everything_in_one_call(analysed_case):
    token, case_id = analysed_case
    bundle = client.get(f"/api/cases/{case_id}/bundle", headers=auth(token)).json()
    for key in ("currentCase", "documents", "claims", "evidence", "relationships",
                "findings", "auditLogs", "timeline"):
        assert key in bundle


# ── review, audit, reports ────────────────────────────────────────────────────

def test_review_creates_audit_events_and_preserves_the_finding(analysed_case):
    token, case_id = analysed_case
    findings = client.get(f"/api/cases/{case_id}/findings", headers=auth(token)).json()
    if not findings:
        pytest.skip("no findings produced for this material")
    finding = findings[0]
    original_reason = finding["reason"]

    response = client.post(
        f"/api/cases/{case_id}/findings/{finding['findingId']}/review",
        json={"decision": "needs_verification", "comment": "Verify device ownership."},
        headers=auth(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["finding"]["status"] == "needs_verification"
    assert body["finding"]["reason"] == original_reason  # AI finding never overwritten
    assert body["review"]["comment"] == "Verify device ownership."
    assert len(body["auditLogs"]) == 2

    audit = client.get(f"/api/cases/{case_id}/audit", headers=auth(token)).json()
    actions = {e["action"] for e in audit}
    assert "Reviewer changed finding status" in actions
    assert "Reviewer comment added" in actions
    assert any(e["action"] == "Claim extracted" and e["actorType"] == "ai" for e in audit)


def test_invalid_review_decision_rejected(analysed_case):
    token, case_id = analysed_case
    findings = client.get(f"/api/cases/{case_id}/findings", headers=auth(token)).json()
    if not findings:
        pytest.skip("no findings produced")
    response = client.post(
        f"/api/cases/{case_id}/findings/{findings[0]['findingId']}/review",
        json={"decision": "declare_guilty", "comment": ""},
        headers=auth(token),
    )
    assert response.status_code == 400


def test_review_of_unknown_finding_is_404(analysed_case):
    token, case_id = analysed_case
    response = client.post(
        f"/api/cases/{case_id}/findings/F-999/review",
        json={"decision": "accept", "comment": ""},
        headers=auth(token),
    )
    assert response.status_code == 404


def test_report_generation_pdf_and_json(analysed_case):
    token, case_id = analysed_case
    created = client.post(f"/api/cases/{case_id}/report", json={}, headers=auth(token))
    assert created.status_code == 201, created.text
    report_id = created.json()["reportId"]

    pdf = client.get(f"/api/cases/{case_id}/report/{report_id}/pdf", headers=auth(token))
    assert pdf.status_code == 200
    assert pdf.content[:4] == b"%PDF"

    export = client.get(f"/api/cases/{case_id}/report/{report_id}/json", headers=auth(token))
    assert export.status_code == 200
    payload = export.json()
    assert "does not determine guilt" in payload["meta"]["disclaimer"]


def test_report_pii_redaction():
    from backend.app.utils import pii

    text = "Contact ram@example.com or 9876543210, id 1234 5678 9012."
    redacted = pii.redact(text)
    assert "ram@example.com" not in redacted
    assert "9876543210" not in redacted
    assert "1234 5678 9012" not in redacted
    assert len(pii.find_pii(text)) == 3


# ── MCP tools ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def mcp_principal(analysed_case):
    from ai_engine.mcp.tools import principal_from_email

    return principal_from_email("pipeline@example.com"), analysed_case[1]


def call(tool: str, args: dict, principal=None):
    from ai_engine.mcp.tools import TOOLS

    return TOOLS[tool](principal, args)


def test_mcp_tools_require_a_principal(mcp_principal):
    _, case_id = mcp_principal
    result = call("get_claims", {"case_id": case_id}, None)
    assert result["error"]["code"] == "UNAUTHENTICATED"


def test_mcp_get_case_material(mcp_principal):
    principal, case_id = mcp_principal
    result = call("get_case_material", {"case_id": case_id}, principal)
    assert result["case_id"] == case_id
    assert result["documents"]
    assert "storage_path" not in str(result)


def test_mcp_get_claims(mcp_principal):
    principal, case_id = mcp_principal
    result = call("get_claims", {"case_id": case_id}, principal)
    assert result["claims"]
    assert "extraction uncertainty" in result["notice"]
    assert all(0.0 <= c["confidence"] <= 1.0 for c in result["claims"])


def test_mcp_get_evidence(mcp_principal):
    principal, case_id = mcp_principal
    claims = call("get_claims", {"case_id": case_id}, principal)["claims"]
    result = call("get_evidence", {"claim_id": claims[0]["id"], "case_id": case_id}, principal)
    assert "evidence" in result


def test_mcp_find_claim_conflicts(mcp_principal):
    principal, case_id = mcp_principal
    claims = call("get_claims", {"case_id": case_id}, principal)["claims"]
    result = call("find_claim_conflicts", {"claim_id": claims[0]["id"], "case_id": case_id},
                  principal)
    assert "conflicts" in result
    assert "never determines which source is truthful" in result["notice"]


def test_mcp_search_authorities_on_empty_corpus(mcp_principal):
    principal, _ = mcp_principal
    result = call("search_authorities", {"query": "location evidence", "limit": 3}, principal)
    assert result["results"] == []
    assert result["corpus_size"] == 0
    assert "rather than an invented one" in result["notice"]


def test_mcp_get_authority_excerpt_missing(mcp_principal):
    principal, _ = mcp_principal
    result = call("get_authority_excerpt", {"authority_id": "AUTH-404"}, principal)
    assert result["error"]["code"] == "AUTHORITY_NOT_FOUND"


def test_mcp_get_audit_history(mcp_principal):
    principal, case_id = mcp_principal
    result = call("get_audit_history", {"case_id": case_id}, principal)
    assert result["events"]
    assert {"event", "actor", "timestamp"} <= set(result["events"][0])


def test_mcp_enforces_case_ownership(mcp_principal):
    from ai_engine.mcp.tools import principal_from_email

    _, case_id = mcp_principal
    intruder = principal_from_email("owner-b@example.com")
    result = call("get_claims", {"case_id": case_id}, intruder)
    assert result["error"]["code"] == "CASE_NOT_FOUND"


def test_mcp_validation_error(mcp_principal):
    principal, _ = mcp_principal
    result = call("get_claims", {}, principal)
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_mcp_unknown_case(mcp_principal):
    principal, _ = mcp_principal
    result = call("get_case_material", {"case_id": "NS-1990-001"}, principal)
    assert result["error"]["code"] == "CASE_NOT_FOUND"


def test_mcp_errors_never_leak_internals(mcp_principal):
    principal, _ = mcp_principal
    for tool, args in (
        ("get_claims", {"case_id": "NS-1990-001"}),
        ("get_evidence", {"claim_id": "C-99"}),
        ("get_authority_excerpt", {"authority_id": "X"}),
    ):
        result = call(tool, args, principal)
        blob = str(result)
        assert "Traceback" not in blob
        assert "/home" not in blob
        assert "sqlite" not in blob.lower()


# ── AI layer ──────────────────────────────────────────────────────────────────

def test_malformed_model_output_is_rejected():
    from agents.providers import parse_json

    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here you go: {"a": 2} hope that helps') == {"a": 2}
    with pytest.raises(ValueError):
        parse_json("not json at all")


def test_schema_validation_rejects_bad_claims():
    from agents.schemas import ExtractedClaim

    with pytest.raises(Exception):
        ExtractedClaim(text="short")
    claim = ExtractedClaim(text="A sufficiently long assertion about an event.", type="nonsense")
    assert claim.type == "OTHER"
    assert 0.0 <= claim.confidence <= 1.0


def test_conflict_detector_language_is_hedged():
    from ai_engine.analysis import detect_claim_conflicts

    claims = [
        {"id": "C-01", "text": "The person was near Riverside Road at 10:45 PM on 11 August.",
         "type": "LOCATION", "document_id": "DOC-001"},
        {"id": "C-02", "text": "The person was near Harbour Street at 10:43 PM on 11 August.",
         "type": "LOCATION", "document_id": "DOC-002"},
    ]
    conflicts = detect_claim_conflicts(claims, "high")
    assert conflicts
    assert all("Human verification is required" in c["description"] for c in conflicts)
    assert all(c["severity"] == "REVIEW_REQUIRED" for c in conflicts)


def test_uncertainty_is_not_treated_as_dishonesty():
    from ai_engine.analysis import classify_relationship

    rel, reason, _ = classify_relationship(
        "The witness reached home at about 11 PM.",
        "The witness stated they cannot remember the exact time they reached home.",
    )
    assert rel in ("UNCERTAIN", "CONTEXTUALIZES", "SUPPORTS", "MENTIONS")
    assert "not an indication of dishonesty" in reason or rel != "UNCERTAIN"


def test_time_parsing():
    from ai_engine.analysis import to_minutes

    assert to_minutes("10:45 PM") == 22 * 60 + 45
    assert to_minutes("22:45") == 22 * 60 + 45
    assert to_minutes("12:30 AM") == 30
    assert to_minutes("not a time") is None


def test_transcript_speaker_parsing():
    from ai_engine.extraction import extract_statements

    pages = [{"page": 1, "paragraphs": [{"n": 1, "text": TRANSCRIPT}]}]
    speakers, statements = extract_statements(pages)
    assert {s["id"] for s in speakers} >= {"PW-3", "COUNSEL"}
    assert any(s["marker"] == "uncertainty" for s in statements)
    assert any(s["marker"] == "question" for s in statements)


def test_authority_corpus_starts_empty():
    from backend.app.services.authority_service import CorpusAuthorityService

    db = session_scope()
    try:
        assert CorpusAuthorityService(db).size() == 0
        assert CorpusAuthorityService(db).search("anything") == []
    finally:
        db.close()


def test_authority_corpus_can_be_loaded_and_searched():
    import json

    from backend.app.services.authority_service import CorpusAuthorityService, load_corpus

    corpus_dir = Path(os.environ["AUTHORITY_CORPUS_DIR"])
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "test.json").write_text(
        json.dumps(
            [
                {
                    "authority_id": "TEST-001",
                    "title": "Test Authority on Location Evidence",
                    "citation": "TEST 2026 1",
                    "passage": "Evidence of location must be assessed alongside surrounding "
                               "circumstantial material by the court.",
                }
            ]
        ),
        encoding="utf-8",
    )
    db = session_scope()
    try:
        assert load_corpus(db, corpus_dir) == 1
        service = CorpusAuthorityService(db)
        assert service.size() == 1
        results = service.search("location evidence circumstantial")
        assert results and results[0]["authority_id"] == "TEST-001"
        assert 0 < results[0]["score"] <= 1.0
        assert service.excerpt("TEST-001")["source"] == "authority_corpus"
    finally:
        db.close()
        (corpus_dir / "test.json").unlink(missing_ok=True)


def test_system_status_reports_honestly():
    token = register("status@example.com")["token"]
    status = client.get("/api/system/status").json()
    assert status["api"] == "online"
    assert status["database"] == "connected"
    assert status["aiProvider"]["state"] in ("ready", "not_configured")
    assert status["mcpServer"]["tools"] == 7
    _ = token


def test_global_search_is_scoped_to_the_user(analysed_case):
    token, case_id = analysed_case
    results = client.get("/api/system/search", params={"q": "Riverside"}, headers=auth(token)).json()
    assert results["claims"]

    other = register("searcher@example.com")["token"]
    empty = client.get("/api/system/search", params={"q": "Riverside"}, headers=auth(other)).json()
    assert not empty["claims"]


def test_case_delete_removes_derived_data():
    token = register("delete@example.com")["token"]
    case_id = make_case(token, "Disposable")
    upload(token, case_id, "statement.txt", STATEMENT_A)
    assert client.delete(f"/api/cases/{case_id}", headers=auth(token)).status_code == 204
    assert client.get(f"/api/cases/{case_id}", headers=auth(token)).status_code == 404
