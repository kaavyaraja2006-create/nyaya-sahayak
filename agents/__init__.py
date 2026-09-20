"""NyayaSahayak agents.

Five agents, plus the LangGraph pipeline that joins them in a fixed line:

    START
      -> CaseUnderstandingAgent   — agents.case_understanding
      -> EvidenceConflictAgent    — agents.evidence_conflict
      -> AuthorityCitationAgent   — agents.authority_citation
      -> CounterArgumentAgent     — agents.counter_argument
      -> RiskReviewReportAgent    — agents.risk_review_report
      -> END

The pipeline lives in agents.graph. There is no router, no supervisor and no
sixth agent: each stage is handed only the structured output it needs, and
uncertainty states (UNVERIFIED, SOURCE_NOT_FOUND, NO_CONTRARY_SOURCE_FOUND,
REQUIRES_HUMAN_REVIEW) travel through unchanged.

Not yet implemented (do not assume these exist):
    * CaseContext / provider wiring for the FastAPI backend
"""
from .authority_citation import (
    AUTHORITY_CITATION_SYSTEM_PROMPT,
    AuthorityCitationAgent,
    AuthorityCitationInput,
    AuthorityCitationResult,
    AuthorityPassage,
    AuthorityRetriever,
    AuthorityType,
    CitationFinding,
    CitationRelationship,
    CitedAuthority,
    InMemoryAuthorityRetriever,
    LegalProposition,
    RejectedModelOutput,
    SourceProvenance,
    SuppliedAuthority,
)
from .authority_citation import LLMProvider as AuthorityCitationLLMProvider
from .case_understanding import (
    CASE_UNDERSTANDING_SYSTEM_PROMPT,
    CaseUnderstandingAgent,
    CaseUnderstandingInput,
    CaseUnderstandingResult,
    Claim,
    ClaimType,
    DocumentKind,
    Page,
    Paragraph,
    RejectedClaim,
    SourceDocument,
    SourceReference,
    TranscriptUtterance,
    VerificationStatus,
)
from .case_understanding import LLMProvider as CaseUnderstandingLLMProvider
from .evidence_conflict import (
    EVIDENCE_CONFLICT_SYSTEM_PROMPT,
    Conflict,
    ConflictSide,
    ConflictType,
    ClaimEvidenceRelationship,
    EvidenceConflictAgent,
    EvidenceConflictInput,
    EvidenceConflictResult,
    EvidenceItem,
    EvidenceType,
    GapType,
    RejectedFinding,
    RelationshipType,
    SupportGap,
)
from .evidence_conflict import LLMProvider as EvidenceConflictLLMProvider
from .counter_argument import (
    COUNTER_ARGUMENT_SYSTEM_PROMPT,
    CounterAnalysisStatus,
    CounterArgumentAgent,
    CounterArgumentFinding,
    CounterArgumentInput,
    CounterArgumentResult,
    CounterArgumentTarget,
    Counterpoint,
    CounterpointBasis,
    CounterpointType,
    MaterialKind,
    RejectedCounterMaterial,
    RetrievedAuthority,
    RetrievedEvidence,
    UnresolvedQuestion,
)
from .counter_argument import LLMProvider as CounterArgumentLLMProvider
from .risk_review_report import (
    RISK_REVIEW_REPORT_SYSTEM_PROMPT,
    AuthorityStatus,
    AuthorityStatusRecord,
    Dashboard,
    FindingKind,
    IssueType,
    ReportSummary,
    ReviewItem,
    ReviewType,
    RiskItem,
    RiskLevel,
    RiskReviewReportAgent,
    RiskReviewReportInput,
    RiskReviewReportResult,
    SourceRef,
    StageStatus,
    ValidationFailure,
)
from .risk_review_report import LLMProvider as RiskReviewReportLLMProvider
from .graph import (
    PIPELINE_ORDER,
    NyayaSahayakGraph,
    NyayaSahayakState,
    StageName,
    StageOutcome,
    StageRecord,
    build_default_agents,
    build_nyaya_graph,
    run_pipeline,
)

__all__ = [
    # Authority Citation
    "AUTHORITY_CITATION_SYSTEM_PROMPT",
    "AuthorityCitationAgent",
    "AuthorityCitationInput",
    "AuthorityCitationLLMProvider",
    "AuthorityCitationResult",
    "AuthorityPassage",
    "AuthorityRetriever",
    "AuthorityType",
    "CitationFinding",
    "CitationRelationship",
    "CitedAuthority",
    "InMemoryAuthorityRetriever",
    "LegalProposition",
    "RejectedModelOutput",
    "SourceProvenance",
    "SuppliedAuthority",
    # Case Understanding
    "CASE_UNDERSTANDING_SYSTEM_PROMPT",
    "CaseUnderstandingAgent",
    "CaseUnderstandingInput",
    "CaseUnderstandingResult",
    "Claim",
    "ClaimType",
    "DocumentKind",
    "CaseUnderstandingLLMProvider",
    "Page",
    "Paragraph",
    "RejectedClaim",
    "SourceDocument",
    "SourceReference",
    "TranscriptUtterance",
    "VerificationStatus",
    # Evidence Conflict
    "EVIDENCE_CONFLICT_SYSTEM_PROMPT",
    "Conflict",
    "ConflictSide",
    "ConflictType",
    "ClaimEvidenceRelationship",
    "EvidenceConflictAgent",
    "EvidenceConflictInput",
    "EvidenceConflictResult",
    "EvidenceItem",
    "EvidenceType",
    "GapType",
    "RejectedFinding",
    "RelationshipType",
    "SupportGap",
    "EvidenceConflictLLMProvider",
    # Counter Argument
    "COUNTER_ARGUMENT_SYSTEM_PROMPT",
    "CounterAnalysisStatus",
    "CounterArgumentAgent",
    "CounterArgumentFinding",
    "CounterArgumentInput",
    "CounterArgumentLLMProvider",
    "CounterArgumentResult",
    "CounterArgumentTarget",
    "Counterpoint",
    "CounterpointBasis",
    "CounterpointType",
    "MaterialKind",
    "RejectedCounterMaterial",
    "RetrievedAuthority",
    "RetrievedEvidence",
    "UnresolvedQuestion",
    # Risk Review Report
    "RISK_REVIEW_REPORT_SYSTEM_PROMPT",
    "AuthorityStatus",
    "AuthorityStatusRecord",
    "Dashboard",
    "FindingKind",
    "IssueType",
    "ReportSummary",
    "ReviewItem",
    "ReviewType",
    "RiskItem",
    "RiskLevel",
    "RiskReviewReportAgent",
    "RiskReviewReportInput",
    "RiskReviewReportLLMProvider",
    "RiskReviewReportResult",
    "SourceRef",
    "StageStatus",
    "ValidationFailure",
    # Pipeline
    "NyayaSahayakGraph",
    "NyayaSahayakState",
    "PIPELINE_ORDER",
    "StageName",
    "StageOutcome",
    "StageRecord",
    "build_default_agents",
    "build_nyaya_graph",
    "run_pipeline",
]
