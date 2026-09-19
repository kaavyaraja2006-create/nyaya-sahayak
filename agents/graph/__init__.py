"""The LangGraph pipeline joining the five NyayaSahayak agents.

Import `build_nyaya_graph` to wire agents you constructed yourself, or
`run_pipeline` for the default wiring from a single LLM provider.
"""
from .graph import (
    NyayaSahayakGraph,
    build_default_agents,
    build_nyaya_graph,
    make_authority_citation_node,
    make_case_understanding_node,
    make_counter_argument_node,
    make_evidence_conflict_node,
    make_risk_review_report_node,
    run_pipeline,
)
from .state import (
    PIPELINE_ORDER,
    NyayaSahayakState,
    StageName,
    StageOutcome,
    StageRecord,
)

__all__ = [
    "NyayaSahayakGraph",
    "NyayaSahayakState",
    "PIPELINE_ORDER",
    "StageName",
    "StageOutcome",
    "StageRecord",
    "build_default_agents",
    "build_nyaya_graph",
    "make_authority_citation_node",
    "make_case_understanding_node",
    "make_counter_argument_node",
    "make_evidence_conflict_node",
    "make_risk_review_report_node",
    "run_pipeline",
]
