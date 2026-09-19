"""SQLAlchemy ORM models.

One database, one set of models. Every case-scoped row carries a case_id and
every case carries a user_id — ownership is enforced in the service layer and
in the MCP tools through the same services.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def uid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=uid)
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True, index=True)
    phone = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="OTHER")
    organization = Column(String, nullable=True)
    registration_number = Column(String, nullable=True)
    experience_years = Column(Integer, nullable=True)
    specialization = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    cases = relationship("Case", back_populates="user", cascade="all, delete-orphan")


class Case(Base):
    __tablename__ = "cases"

    id = Column(String, primary_key=True, default=uid)
    case_id = Column(String, nullable=False, unique=True, index=True)  # NS-2026-001
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    case_number = Column(String, nullable=True)
    case_type = Column(String, nullable=True)
    jurisdiction = Column(String, nullable=True)
    court = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="DRAFT")
    filed_on = Column(String, nullable=True)
    last_analyzed = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="cases")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=uid)
    document_id = Column(String, nullable=False, index=True)  # DOC-001 (unique per case)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    document_type = Column(String, nullable=False, default="Other")
    category = Column(String, nullable=False, default="Reports")
    storage_path = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)
    size_bytes = Column(Integer, default=0)
    page_count = Column(Integer, default=0)
    extracted_text = Column(Text, nullable=True)
    pages_json = Column(Text, nullable=True)   # [{page, paragraphs:[{n,text}]}]
    entities_json = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="processing")
    is_transcript = Column(Boolean, default=False)
    uploaded_at = Column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("case_id", "document_id", name="uq_doc_per_case"),)


class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(String, primary_key=True, default=uid)
    transcript_id = Column(String, nullable=False, index=True)  # HR-001
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(String, nullable=True)  # linked Document.document_id
    filename = Column(String, nullable=True)
    storage_path = Column(String, nullable=True)
    mime_type = Column(String, nullable=True)
    hearing_date = Column(String, nullable=True)
    hearing_number = Column(String, nullable=True)
    court = Column(String, nullable=True)
    extracted_text = Column(Text, nullable=True)
    speakers_json = Column(Text, nullable=True)
    statements_json = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, default=utcnow)


class Claim(Base):
    __tablename__ = "claims"

    id = Column(String, primary_key=True, default=uid)
    claim_id = Column(String, nullable=False, index=True)  # C-01
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=True)
    claim_text = Column(Text, nullable=False)
    claim_type = Column(String, nullable=True)
    speaker = Column(String, nullable=True)
    source_document_id = Column(String, nullable=True)
    source_page = Column(Integer, nullable=True)
    source_paragraph = Column(Integer, nullable=True)
    source_quote = Column(Text, nullable=True)
    origin_note = Column(String, nullable=True)
    status = Column(String, nullable=False, default="needs_review")
    extraction_confidence = Column(Float, default=0.0)
    signals_json = Column(Text, nullable=True)
    hearing_statement_ids = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(String, primary_key=True, default=uid)
    evidence_id = Column(String, nullable=False, index=True)  # E-01
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_type = Column(String, nullable=False, default="Document")
    description = Column(Text, nullable=False)
    source_document_id = Column(String, nullable=True)
    source_page = Column(Integer, nullable=True)
    source_paragraph = Column(Integer, nullable=True)
    source_quote = Column(Text, nullable=True)
    item_date = Column(String, nullable=True)
    meta_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"

    id = Column(String, primary_key=True, default=uid)
    relationship_id = Column(String, nullable=False, index=True)  # R-01
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id = Column(String, nullable=False)
    evidence_id = Column(String, nullable=False)
    relationship = Column(String, nullable=False, default="MENTIONS")
    reason = Column(Text, nullable=True)
    assessment_signal = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class Finding(Base):
    """Potential conflicts, citation issues and missing-source items awaiting review."""

    __tablename__ = "findings"

    id = Column(String, primary_key=True, default=uid)
    finding_id = Column(String, nullable=False, index=True)  # F-001
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String, nullable=False, default="conflict")
    category = Column(String, nullable=True)
    group_name = Column(String, nullable=False, default="evidence")
    priority = Column(String, nullable=False, default="medium")
    claim_id = Column(String, nullable=True)
    title = Column(String, nullable=False)
    reason = Column(Text, nullable=True)
    conflict_type = Column(String, nullable=True)
    comparison_json = Column(Text, nullable=True)
    relationship_ids = Column(Text, nullable=True)
    evidence_ids = Column(Text, nullable=True)
    authority_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="open")
    requires_human_review = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)


class Authority(Base):
    """Curated legal authority corpus. Loaded from legal_data/authorities/*.json."""

    __tablename__ = "authorities"

    id = Column(String, primary_key=True, default=uid)
    authority_id = Column(String, nullable=False, unique=True, index=True)
    label = Column(String, nullable=True)
    title = Column(String, nullable=False)
    court = Column(String, nullable=True)
    year = Column(Integer, nullable=True)
    citation = Column(String, nullable=True)
    jurisdiction = Column(String, nullable=True)
    paragraph = Column(Integer, nullable=True)
    passage = Column(Text, nullable=False)
    source_type = Column(String, nullable=True)
    source_file = Column(String, nullable=True)
    corpus = Column(String, nullable=True)


class CaseAuthority(Base):
    """An authority retrieved for a particular case/claim."""

    __tablename__ = "case_authorities"

    id = Column(String, primary_key=True, default=uid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    authority_id = Column(String, nullable=False)
    claim_ids = Column(Text, nullable=True)
    relevance = Column(Float, nullable=True)
    why_retrieved = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="verification_required")
    created_at = Column(DateTime, default=utcnow)


class Citation(Base):
    __tablename__ = "citations"

    id = Column(String, primary_key=True, default=uid)
    citation_id = Column(String, nullable=False, index=True)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id = Column(String, nullable=True)
    authority_id = Column(String, nullable=True)
    source_document_id = Column(String, nullable=True)
    source_page = Column(Integer, nullable=True)
    source_paragraph = Column(Integer, nullable=True)
    matched_passage = Column(Text, nullable=True)
    result = Column(String, nullable=False, default="unable_to_map")
    note = Column(Text, nullable=True)
    requires_review = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)


class Review(Base):
    __tablename__ = "reviews"

    id = Column(String, primary_key=True, default=uid)
    review_id = Column(String, nullable=False, index=True)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    finding_id = Column(String, nullable=False)
    reviewer_id = Column(String, nullable=False)
    reviewer_name = Column(String, nullable=False)
    decision = Column(String, nullable=False)
    comment = Column(Text, nullable=True)
    previous_status = Column(String, nullable=True)
    new_status = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String, primary_key=True, default=uid)
    log_id = Column(String, nullable=False, index=True)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    actor = Column(String, nullable=False)
    actor_type = Column(String, nullable=False, default="system")
    action = Column(String, nullable=False)
    object_type = Column(String, nullable=False, default="case")
    object_id = Column(String, nullable=True)
    previous_state = Column(String, nullable=True)
    new_state = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String, primary_key=True, default=uid)
    run_id = Column(String, nullable=False, index=True)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    input_summary = Column(Text, nullable=True)
    output_summary = Column(Text, nullable=True)
    warnings = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id = Column(String, primary_key=True, default=uid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String, nullable=False, default="running")
    stage_index = Column(Integer, default=0)
    progress = Column(Integer, default=0)
    message = Column(String, nullable=True)
    summary_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    ai_mode = Column(String, nullable=True)
    started_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)


class ToolCall(Base):
    """MCP tool invocation log — surfaced in the UI's technical panel."""

    __tablename__ = "tool_calls"

    id = Column(String, primary_key=True, default=uid)
    case_id = Column(String, nullable=True, index=True)
    tool_name = Column(String, nullable=False)
    request_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="completed")
    latency_ms = Column(Integer, nullable=True)
    detail = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class Report(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=uid)
    report_id = Column(String, nullable=False, index=True)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = Column(String, nullable=True)
    json_path = Column(String, nullable=True)
    counts_json = Column(Text, nullable=True)
    generated_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
