from .agent import AuthorityCitationAgent, LLMProvider
from .citations import authority_matches_citation, identify_citation_type, normalize_citation
from .prompts import AUTHORITY_CITATION_SYSTEM_PROMPT
from .retrieval import AuthorityRetriever, InMemoryAuthorityRetriever
from .schemas import (
    AuthorityCitationInput,
    AuthorityCitationResult,
    AuthorityPassage,
    AuthorityType,
    CitationFinding,
    CitationRelationship,
    CitedAuthority,
    LegalProposition,
    RejectedModelOutput,
    SourceProvenance,
    SuppliedAuthority,
)
from .validation import (
    VerifiedAssessment,
    find_ungrounded_references,
    verify_model_assessment,
    verify_quote,
)

__all__ = [
    "AuthorityCitationAgent",
    "LLMProvider",
    "AUTHORITY_CITATION_SYSTEM_PROMPT",
    "AuthorityRetriever",
    "InMemoryAuthorityRetriever",
    "AuthorityCitationInput",
    "AuthorityCitationResult",
    "AuthorityPassage",
    "AuthorityType",
    "CitationFinding",
    "CitationRelationship",
    "CitedAuthority",
    "LegalProposition",
    "RejectedModelOutput",
    "SourceProvenance",
    "SuppliedAuthority",
    "VerifiedAssessment",
    "authority_matches_citation",
    "identify_citation_type",
    "normalize_citation",
    "find_ungrounded_references",
    "verify_model_assessment",
    "verify_quote",
]
