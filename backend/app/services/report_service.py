"""Human review and report generation."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    AuditEvent, Case, CaseAuthority, Citation, Claim, ClaimEvidence, Document,
    Evidence, Finding, Report, Review, Transcript, User,
)
from ..utils import pii
from ..utils.ids import next_index, seq_id
from ..utils.serialize import (
    audit_out, authority_out, case_out, citation_out, claim_out, document_summary,
    dumps, evidence_out, finding_out, loads, relationship_out, review_out, transcript_out,
)
from . import case_service
from .case_service import NotFound

DECISION_TO_STATUS = {
    "accept": "accepted",
    "reject": "rejected",
    "needs_verification": "needs_verification",
    "modify": "needs_verification",
}
STATUS_LABEL = {
    "open": "Open",
    "accepted": "Accepted",
    "rejected": "Rejected",
    "needs_verification": "Needs verification",
}

DISCLAIMER = (
    "This report is an AI-assisted research and evidence-auditing output. It does not "
    "determine guilt, innocence, liability, witness credibility, admissibility, or judicial "
    "outcome. Human legal review remains required."
)


# ── review ────────────────────────────────────────────────────────────────────

def save_review(
    db: Session, case: Case, user: User, finding_public_id: str, decision: str, comment: str
) -> tuple[Finding, Review, list[AuditEvent]]:
    if decision not in DECISION_TO_STATUS:
        raise ValueError(f"Unsupported review decision '{decision}'.")
    finding = db.scalar(
        select(Finding).where(Finding.case_id == case.id, Finding.finding_id == finding_public_id)
    )
    if finding is None:
        raise NotFound(f"No finding was found for '{finding_public_id}'.")

    previous = finding.status
    new_status = DECISION_TO_STATUS[decision]

    existing = list(db.scalars(select(Review.review_id).where(Review.case_id == case.id)))
    review = Review(
        review_id=seq_id("RV", next_index(existing, "RV"), 3),
        case_id=case.id,
        finding_id=finding.finding_id,
        reviewer_id=user.id,
        reviewer_name=user.full_name,
        decision=decision,
        comment=comment.strip(),
        previous_status=previous,
        new_status=new_status,
    )
    db.add(review)

    # The original AI finding text is never overwritten — only its review status moves.
    finding.status = new_status
    finding.requires_human_review = new_status == "needs_verification"

    events = [
        case_service.log_event(
            db, case.id, action="Reviewer changed finding status", object_type="finding",
            object_id=finding.finding_id, actor=user.full_name, actor_type="reviewer",
            previous_state=STATUS_LABEL.get(previous, previous),
            new_state=STATUS_LABEL.get(new_status, new_status), commit=False,
        )
    ]
    if comment.strip():
        events.append(
            case_service.log_event(
                db, case.id, action="Reviewer comment added", object_type="finding",
                object_id=finding.finding_id, actor=user.full_name, actor_type="reviewer",
                details=comment.strip()[:500], commit=False,
            )
        )

    if finding.claim_id:
        claim = db.scalar(
            select(Claim).where(Claim.case_id == case.id, Claim.claim_id == finding.claim_id)
        )
        if claim:
            open_for_claim = db.scalar(
                select(Finding).where(
                    Finding.case_id == case.id,
                    Finding.claim_id == claim.claim_id,
                    Finding.status == "open",
                )
            )
            claim.status = "needs_review" if open_for_claim else (
                "reviewed" if new_status in ("accepted", "rejected") else "unresolved"
            )

    open_left = db.scalar(select(Finding).where(Finding.case_id == case.id, Finding.status == "open"))
    if not open_left:
        case_service.set_status(db, case, "REVIEW_COMPLETE", actor=user.full_name)

    db.commit()
    db.refresh(finding)
    db.refresh(review)
    return finding, review, events


# ── case bundle (one round trip for the UI) ───────────────────────────────────

def build_bundle(db: Session, case: Case) -> dict:
    documents = case_service.list_documents(db, case.id)
    transcripts = case_service.list_transcripts(db, case.id)
    claims = list(db.scalars(select(Claim).where(Claim.case_id == case.id).order_by(Claim.claim_id)))
    evidence = list(
        db.scalars(select(Evidence).where(Evidence.case_id == case.id).order_by(Evidence.evidence_id))
    )
    relationships = list(db.scalars(select(ClaimEvidence).where(ClaimEvidence.case_id == case.id)))
    findings = list(
        db.scalars(select(Finding).where(Finding.case_id == case.id).order_by(Finding.finding_id))
    )
    citations = list(db.scalars(select(Citation).where(Citation.case_id == case.id)))
    reviews = list(db.scalars(select(Review).where(Review.case_id == case.id)))
    links = list(db.scalars(select(CaseAuthority).where(CaseAuthority.case_id == case.id)))

    from ..models import Authority

    authority_rows = {
        a.authority_id: a
        for a in db.scalars(
            select(Authority).where(Authority.authority_id.in_([l.authority_id for l in links] or [""]))
        )
    }
    authorities = [
        authority_out(authority_rows[l.authority_id], l) for l in links if l.authority_id in authority_rows
    ]

    return {
        "currentCase": case_out(case, case_service.case_counts(db, case.id)),
        "documents": [document_summary(d) for d in documents],
        "transcripts": [transcript_out(t) for t in transcripts],
        "claims": [claim_out(c) for c in claims],
        "evidence": [evidence_out(e) for e in evidence],
        "relationships": [relationship_out(r) for r in relationships],
        "authorities": authorities,
        "citations": [citation_out(c) for c in citations],
        "findings": [finding_out(f) for f in findings],
        "reviews": [review_out(r) for r in reviews],
        "auditLogs": [audit_out(a, case.case_id) for a in case_service.list_audit(db, case.id)],
        "hearing": transcript_out(transcripts[0]) if transcripts else None,
        "timeline": build_timeline(db, case),
    }


def build_timeline(db: Session, case: Case) -> list[dict]:
    """Time-anchored claims and evidence, ordered for the timeline view."""
    from ai_engine.analysis import first_time
    from ai_engine.extraction import TIME_RE

    events: list[dict] = []
    conflicted = {
        f.claim_id
        for f in db.scalars(
            select(Finding).where(Finding.case_id == case.id, Finding.kind == "conflict")
        )
        if f.claim_id
    }

    for claim in db.scalars(select(Claim).where(Claim.case_id == case.id)):
        m = TIME_RE.search(claim.claim_text)
        if not m:
            continue
        events.append(
            {
                "eventId": f"TL-{claim.claim_id}",
                "time": m.group(0).strip(),
                "sortKey": first_time(claim.claim_text) or 0,
                "label": (claim.title or claim.claim_text)[:90],
                "detail": claim.claim_text[:300],
                "kind": "witness" if claim.speaker else "record",
                "source": {
                    "documentId": claim.source_document_id or "",
                    "page": claim.source_page or 1,
                    "paragraph": claim.source_paragraph or 1,
                },
                "claimIds": [claim.claim_id],
                "conflict": claim.claim_id in conflicted,
            }
        )

    for ev in db.scalars(select(Evidence).where(Evidence.case_id == case.id)):
        m = TIME_RE.search(ev.description)
        if not m:
            continue
        kind = {
            "CCTV": "cctv", "Phone Metadata": "phone", "Witness Statement": "witness",
            "Hearing Statement": "witness",
        }.get(ev.evidence_type, "record")
        events.append(
            {
                "eventId": f"TL-{ev.evidence_id}",
                "time": m.group(0).strip(),
                "sortKey": first_time(ev.description) or 0,
                "label": f"{ev.evidence_type}: {ev.description[:70]}",
                "detail": ev.description[:300],
                "kind": kind,
                "source": {
                    "documentId": ev.source_document_id or "",
                    "page": ev.source_page or 1,
                    "paragraph": ev.source_paragraph or 1,
                },
                "claimIds": [],
                "conflict": False,
            }
        )

    events.sort(key=lambda e: e["sortKey"])
    for e in events:
        e.pop("sortKey", None)
    return events


# ── reports ───────────────────────────────────────────────────────────────────

def report_payload(db: Session, case: Case, user: User, redact: bool = False) -> dict:
    bundle = build_bundle(db, case)
    payload = {
        "meta": {
            "product": "NyayaSahayak",
            "generatedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "generatedBy": user.full_name,
            "role": user.role,
            "disclaimer": DISCLAIMER,
            "piiRedaction": pii.DISCLAIMER if redact else "Not applied",
        },
        **bundle,
    }
    if redact:
        payload = json.loads(pii.redact(json.dumps(payload, ensure_ascii=False)))
    return payload


def generate_report(db: Session, case: Case, user: User, redact: bool = False) -> Report:
    payload = report_payload(db, case, user, redact)
    counts = case_service.case_counts(db, case.id)

    existing = list(db.scalars(select(Report.report_id).where(Report.case_id == case.id)))
    report_id = seq_id("RPT", next_index(existing, "RPT"), 3)

    directory = settings.reports_dir / user.id / case.case_id
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{report_id}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    pdf_path = directory / f"{report_id}.pdf"
    try:
        _write_pdf(pdf_path, case, user, payload, counts)
    except Exception:  # noqa: BLE001 - PDF is a nice-to-have; JSON export always works
        pdf_path = None  # type: ignore[assignment]

    report = Report(
        report_id=report_id,
        case_id=case.id,
        file_path=str(pdf_path) if pdf_path else None,
        json_path=str(json_path),
        counts_json=dumps(counts),
        generated_by=user.full_name,
    )
    db.add(report)
    case_service.log_event(
        db, case.id, action="Report generated", object_type="report", object_id=report_id,
        actor=user.full_name, actor_type="reviewer",
        details=f"Audit report {report_id} generated.", commit=False,
    )
    db.commit()
    db.refresh(report)
    return report


def _write_pdf(path: Path, case: Case, user: User, payload: dict, counts: dict) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=6,
                        textColor=colors.HexColor("#1B2437"))
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12.5, spaceBefore=14,
                        spaceAfter=6, textColor=colors.HexColor("#2E3B52"))
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=14,
                          alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.HexColor("#5C6880"))
    mono = ParagraphStyle("mono", parent=body, fontName="Courier", fontSize=8.5, leading=12)

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"NyayaSahayak audit report — {case.case_id}", author="NyayaSahayak",
    )
    flow: list = []

    def table(rows: list[list[str]], widths: list[float]) -> Table:
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF1F6")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#2E3B52")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5DCE6")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return t

    def p(text: str, style=body) -> Paragraph:
        return Paragraph((text or "—").replace("&", "&amp;").replace("<", "&lt;"), style)

    width = doc.width

    # 1. Case information
    flow += [p("NyayaSahayak — Evidence Audit Report", h1),
             p("Evidence. Context. Traceability.", small), Spacer(1, 8)]
    flow += [p("1. Case information", h2)]
    flow += [
        table(
            [
                ["Field", "Value"],
                ["Case ID", case.case_id],
                ["Case name", case.name],
                ["Case number", case.case_number or "—"],
                ["Case type", case.case_type or "—"],
                ["Jurisdiction", case.jurisdiction or "—"],
                ["Court / institution", case.court or "—"],
                ["Status", case.status],
                ["Generated by", f"{user.full_name} ({user.role})"],
                ["Generated at", payload["meta"]["generatedAt"]],
            ],
            [width * 0.28, width * 0.72],
        )
    ]
    flow += [Spacer(1, 4), p(
        "Professional credentials provided by the user are not independently verified by this "
        "prototype.", small)]

    # 2. Materials analysed
    flow += [p("2. Materials analysed", h2)]
    docs = payload["documents"]
    flow += [
        table(
            [["Document", "Name", "Type", "Pages", "Status"]]
            + [[d["documentId"], d["name"][:48], d["type"], str(d["pages"]), d["status"]] for d in docs]
            or [["Document", "Name", "Type", "Pages", "Status"]],
            [width * 0.12, width * 0.40, width * 0.22, width * 0.10, width * 0.16],
        )
    ]

    # 3. Hearing transcript
    flow += [p("3. Hearing transcript summary", h2)]
    transcripts = payload["transcripts"]
    if transcripts:
        for t in transcripts:
            flow += [
                p(f"{t['hearingId']} · hearing {t.get('hearingNumber') or '—'} · "
                  f"{t.get('date') or 'date not stated'} · {len(t.get('statements', []))} "
                  f"segmented statement(s) across {len(t.get('speakers', []))} speaker(s).")
            ]
    else:
        flow += [p("No hearing transcript was uploaded for this case.")]

    # 4. Claims
    flow += [p("4. Extracted claims", h2)]
    claims = payload["claims"]
    if claims:
        rows = [["ID", "Claim", "Type", "Source", "Status"]]
        for c in claims:
            src = c.get("source") or {}
            rows.append([
                c["claimId"], c["text"][:150], c["type"],
                f"{src.get('documentId', '—')} p{src.get('page', '—')}¶{src.get('paragraph', '—')}"
                if src else "No source",
                c["status"].replace("_", " "),
            ])
        flow += [table(rows, [width * 0.08, width * 0.46, width * 0.16, width * 0.18, width * 0.12])]
    else:
        flow += [p("No claims were extracted.")]

    flow += [PageBreak()]

    # 5. Evidence mapping
    flow += [p("5. Evidence mapping", h2)]
    rel_by_claim: dict[str, list[str]] = {}
    ev_index = {e["evidenceId"]: e for e in payload["evidence"]}
    for r in payload["relationships"]:
        ev = ev_index.get(r["evidenceId"])
        rel_by_claim.setdefault(r["claimId"], []).append(
            f"{r['evidenceId']} ({ev['type'] if ev else '—'}) — {r['type']}"
        )
    if rel_by_claim:
        rows = [["Claim", "Linked evidence"]]
        for claim_id, items in rel_by_claim.items():
            rows.append([claim_id, "\n".join(items[:8])])
        flow += [table(rows, [width * 0.14, width * 0.86])]
    else:
        flow += [p("No claim–evidence relationships were recorded.")]

    # 6. Potential conflicts
    flow += [p("6. Potential conflicts", h2)]
    conflicts = [f for f in payload["findings"] if f["kind"] == "conflict"]
    if conflicts:
        rows = [["Finding", "Type", "Claim", "Description", "Review status"]]
        for f in conflicts:
            rows.append([f["findingId"], f.get("conflictType") or "—", f.get("claimId") or "—",
                         f["reason"][:180], STATUS_LABEL.get(f["status"], f["status"])])
        flow += [table(rows, [width * 0.10, width * 0.18, width * 0.10, width * 0.44, width * 0.18])]
        flow += [Spacer(1, 3), p(
            "Potential conflicts are surfaced for human verification. The system does not "
            "determine which source is correct.", small)]
    else:
        flow += [p("No potential conflicts were surfaced by the current analysis.")]

    # 7. Authorities
    flow += [p("7. Legal authority references", h2)]
    authorities = payload["authorities"]
    if authorities:
        rows = [["Authority", "Citation", "Retrieved passage", "Status"]]
        for a in authorities:
            rows.append([a["authorityId"], a.get("citation") or "—", a["passage"][:200],
                         a["status"].replace("_", " ")])
        flow += [table(rows, [width * 0.12, width * 0.20, width * 0.48, width * 0.20])]
        flow += [Spacer(1, 3), p(
            "Retrieval relevance is a ranking signal only. It is not a measure of legal "
            "correctness, and each passage must be verified by the reviewer.", small)]
    else:
        flow += [p("No authorities were retrieved. The curated authority corpus is empty or no "
                   "record matched the extracted claims; this prototype never fabricates legal "
                   "authorities.")]

    # 8. Citation audit
    flow += [p("8. Citation audit", h2)]
    citations = payload["citations"]
    if citations:
        rows = [["Citation", "Claim", "Authority", "Result", "Note"]]
        for c in citations:
            rows.append([c["citationId"], c.get("claimId") or "—", c.get("authorityId") or "—",
                         c["result"].replace("_", " "), c.get("note", "")[:140]])
        flow += [table(rows, [width * 0.12, width * 0.10, width * 0.14, width * 0.18, width * 0.46])]
    else:
        flow += [p("No citations were located in the uploaded material.")]

    # 9. Human review
    flow += [p("9. Human review actions", h2)]
    reviews = payload["reviews"]
    if reviews:
        rows = [["Review", "Finding", "Decision", "Reviewer", "Comment", "At"]]
        for r in reviews:
            rows.append([r["reviewId"], r["findingId"], r["decision"].replace("_", " "),
                         r["reviewer"], r.get("comment", "")[:120], r["timestamp"]])
        flow += [table(rows, [width * 0.09, width * 0.09, width * 0.14, width * 0.16,
                              width * 0.35, width * 0.17])]
    else:
        flow += [p("No review actions have been recorded yet.")]

    # 10. Audit trail
    flow += [PageBreak(), p("10. Audit trail", h2)]
    logs = payload["auditLogs"]
    if logs:
        rows = [["Timestamp", "Actor", "Action", "Object", "From → To"]]
        for entry in logs:
            transition = (
                f"{entry.get('previousState') or '—'} → {entry.get('newState') or '—'}"
                if entry.get("previousState") or entry.get("newState") else "—"
            )
            rows.append([entry["timestamp"], f"{entry['actor']} ({entry['actorType']})",
                         entry["action"], f"{entry['objectType']} {entry['objectId']}", transition])
        flow += [table(rows, [width * 0.18, width * 0.20, width * 0.28, width * 0.18, width * 0.16])]
    else:
        flow += [p("No audit events recorded.")]

    # 11. Limitations
    flow += [p("11. System limitations", h2)]
    flow += [p(DISCLAIMER)]
    flow += [Spacer(1, 4), p(
        "Assessment signals shown in the application (support strength, conflict strength, "
        "uncertainty) are prototype workflow indicators. They are not probabilities of truth, "
        "credibility or legal validity. Extraction confidence describes how cleanly a sentence "
        "read as a discrete assertion, nothing more.", small)]
    flow += [Spacer(1, 4), p(pii.DISCLAIMER, small)]

    doc.build(flow)
