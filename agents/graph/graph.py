"""The minimal LangGraph StateGraph that runs the five agents in a fixed line.

    START
      -> CaseUnderstandingAgent
      -> EvidenceConflictAgent
      -> AuthorityCitationAgent
      -> CounterArgumentAgent
      -> RiskReviewReportAgent
      -> END

There is no router, no supervisor, no conditional edge and no sixth agent.
The graph's only job is to hand each agent exactly the structured input it
needs and to keep everything else out of its way.

Three rules govern every node here.

**Structured hand-off.** A node reads the previous stages' *result objects*
from the state and converts them only by the adapters the agents' own schemas
provide (`LegalProposition.from_claim`, `CounterArgumentTarget.from_claim`).
Nothing is re-typed by hand, re-summarised, or flattened into prose, so the
`SourceReference` attached to a claim in stage 1 is the very same object the
counter-argument stage sees in stage 4.

**Uncertainty is never upgraded.** No node inspects a `verification_status`,
a `CitationRelationship`, or a `CounterAnalysisStatus` and decides it is good
enough to treat as settled. `UNVERIFIED`, `SOURCE_NOT_FOUND`,
`NO_CONTRARY_SOURCE_FOUND` and `REQUIRES_HUMAN_REVIEW` travel through the
graph untouched and arrive at the report stage as they were produced.

**Failure is never silence.** If a stage raises, the node records `FAILED`,
leaves that stage's result as `None`, and appends the exception text to
`errors`. The report stage still runs, and because it is given `None` rather
than an empty result it reports the stage as missing instead of reporting
that the stage found no problems. A crash can therefore never be mistaken
for a clean bill of health.
"""
from __future__ import annotations

from typing import Any, Optional

from langgraph.graph import END, START, StateGraph

from ..authority_citation.agent import AuthorityCitationAgent
from ..authority_citation.schemas import AuthorityCitationInput, LegalProposition
from ..case_understanding.agent import CaseUnderstandingAgent
from ..case_understanding.schemas import CaseUnderstandingInput
from ..counter_argument.agent import CounterArgumentAgent
from ..counter_argument.schemas import CounterArgumentInput, CounterArgumentTarget
from ..evidence_conflict.agent import EvidenceConflictAgent
from ..evidence_conflict.schemas import EvidenceConflictInput
from ..risk_review_report.agent import RiskReviewReportAgent
from ..risk_review_report.schemas import RiskReviewReportInput
from .state import (
    PIPELINE_ORDER,
    NyayaSahayakState,
    StageName,
    StageOutcome,
    StageRecord,
)

__all__ = [
    "NyayaSahayakGraph",
    "build_nyaya_graph",
    "build_default_agents",
    "run_pipeline",
]


# --------------------------------------------------------------------------
# Small helpers shared by the nodes
# --------------------------------------------------------------------------

def _log(
    state: NyayaSahayakState,
    stage: StageName,
    outcome: StageOutcome,
    detail: str = "",
) -> dict:
    """Return the state update that appends one audit record.

    The append is written out explicitly rather than relying on a reducer
    annotation, so the state object stays a plain, readable Pydantic model.
    """
    record = StageRecord(stage=stage, outcome=outcome, detail=detail)
    return {"stage_log": list(state.stage_log) + [record]}


def _failure(state: NyayaSahayakState, stage: StageName, exc: Exception) -> dict:
    detail = f"{type(exc).__name__}: {exc}"
    update = _log(state, stage, StageOutcome.FAILED, detail)
    update["errors"] = list(state.errors) + [f"{stage.value}: {detail}"]
    # The stage's result key is deliberately left untouched, i.e. None. A
    # failed stage must not be represented by an empty successful result.
    return update


def _is_material(state: NyayaSahayakState, claim_id: str) -> bool:
    """Materiality for the *counter-analysis* stage.

    When the caller has not declared any material claims, every claim is
    analysed: erring toward looking costs only effort. Risk escalation in the
    report stage deliberately does *not* share this default — escalating a
    claim to HIGH is a statement about importance that only a human should
    make.
    """
    if not state.material_claim_ids:
        return True
    return claim_id in state.material_claim_ids


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------

def make_case_understanding_node(agent: CaseUnderstandingAgent):
    def node(state: NyayaSahayakState) -> dict:
        stage = StageName.CASE_UNDERSTANDING
        if not state.documents:
            return _log(state, stage, StageOutcome.SKIPPED, "No source documents supplied.")
        try:
            result = agent.run(
                CaseUnderstandingInput(case_id=state.case_id, documents=list(state.documents))
            )
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            return _failure(state, stage, exc)
        update = _log(
            state,
            stage,
            StageOutcome.COMPLETED,
            f"{len(result.claims)} claim(s) extracted.",
        )
        update["case_understanding"] = result
        return update

    return node


def make_evidence_conflict_node(agent: EvidenceConflictAgent):
    def node(state: NyayaSahayakState) -> dict:
        stage = StageName.EVIDENCE_CONFLICT
        claims = state.claims()
        if not claims:
            return _log(state, stage, StageOutcome.SKIPPED, "No claims from the previous stage.")
        try:
            result = agent.run(
                EvidenceConflictInput(
                    case_id=state.case_id,
                    claims=claims,            # the claim objects themselves, provenance intact
                    evidence=list(state.evidence),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _failure(state, stage, exc)
        update = _log(
            state,
            stage,
            StageOutcome.COMPLETED,
            f"{len(result.conflicts)} conflict(s), {len(result.support_gaps)} gap(s).",
        )
        update["evidence_conflict"] = result
        return update

    return node


def make_authority_citation_node(agent: AuthorityCitationAgent):
    def node(state: NyayaSahayakState) -> dict:
        stage = StageName.AUTHORITY_CITATION
        claims = state.claims()
        if not claims:
            return _log(state, stage, StageOutcome.SKIPPED, "No claims from the previous stage.")
        propositions = [
            LegalProposition.from_claim(
                claim, citations=state.citations_by_claim.get(claim.claim_id, [])
            )
            for claim in claims
        ]
        try:
            result = agent.run(
                AuthorityCitationInput(
                    case_id=state.case_id,
                    propositions=propositions,
                    authorities=list(state.authorities),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _failure(state, stage, exc)
        update = _log(
            state,
            stage,
            StageOutcome.COMPLETED,
            f"{len(result.findings)} citation finding(s).",
        )
        update["authority_citation"] = result
        return update

    return node


def make_counter_argument_node(agent: CounterArgumentAgent):
    def node(state: NyayaSahayakState) -> dict:
        stage = StageName.COUNTER_ARGUMENT
        claims = state.claims()
        if not claims:
            return _log(state, stage, StageOutcome.SKIPPED, "No claims from the previous stage.")
        targets = [
            CounterArgumentTarget.from_claim(
                claim, is_material=_is_material(state, claim.claim_id)
            )
            for claim in claims
        ]
        try:
            result = agent.run(
                CounterArgumentInput(
                    case_id=state.case_id,
                    targets=targets,
                    evidence=list(state.evidence),
                    authorities=list(state.authorities),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _failure(state, stage, exc)
        update = _log(
            state,
            stage,
            StageOutcome.COMPLETED,
            f"{len(result.findings)} counter-analysis finding(s).",
        )
        update["counter_argument"] = result
        return update

    return node


def make_risk_review_report_node(agent: RiskReviewReportAgent):
    def node(state: NyayaSahayakState) -> dict:
        """Always runs.

        Even with every earlier stage skipped or failed, the report is the
        thing that tells a human the pipeline did not complete. Suppressing it
        would hide exactly the information it exists to surface.
        """
        stage = StageName.RISK_REVIEW_REPORT
        try:
            result = agent.run(
                RiskReviewReportInput(
                    case_id=state.case_id,
                    case_understanding=state.case_understanding,
                    evidence_conflict=state.evidence_conflict,
                    authority_citation=state.authority_citation,
                    counter_argument=state.counter_argument,
                    material_claim_ids=list(state.material_claim_ids),
                    authority_statuses=list(state.authority_statuses),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _failure(state, stage, exc)
        update = _log(
            state,
            stage,
            StageOutcome.COMPLETED,
            f"{len(result.risk_items)} risk item(s), {len(result.review_items)} review item(s).",
        )
        update["risk_review_report"] = result
        return update

    return node


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

class NyayaSahayakGraph:
    """A compiled pipeline plus a typed `run`.

    LangGraph hands back a plain mapping; `run` validates it back into a
    `NyayaSahayakState` so callers never have to touch untyped dictionaries.
    """

    def __init__(self, compiled: Any) -> None:
        self.compiled = compiled

    def run(self, state: NyayaSahayakState) -> NyayaSahayakState:
        raw = self.compiled.invoke(state)
        if isinstance(raw, NyayaSahayakState):
            return raw
        return NyayaSahayakState.model_validate(raw)

    # `invoke` mirrors the LangGraph vocabulary for callers who expect it.
    invoke = run


def build_nyaya_graph(
    *,
    case_understanding_agent: CaseUnderstandingAgent,
    evidence_conflict_agent: EvidenceConflictAgent,
    authority_citation_agent: AuthorityCitationAgent,
    counter_argument_agent: CounterArgumentAgent,
    risk_review_report_agent: RiskReviewReportAgent,
) -> NyayaSahayakGraph:
    """Wire the five supplied agents into the fixed pipeline."""
    builder = StateGraph(NyayaSahayakState)

    builder.add_node(
        StageName.CASE_UNDERSTANDING.value,
        make_case_understanding_node(case_understanding_agent),
    )
    builder.add_node(
        StageName.EVIDENCE_CONFLICT.value,
        make_evidence_conflict_node(evidence_conflict_agent),
    )
    builder.add_node(
        StageName.AUTHORITY_CITATION.value,
        make_authority_citation_node(authority_citation_agent),
    )
    builder.add_node(
        StageName.COUNTER_ARGUMENT.value,
        make_counter_argument_node(counter_argument_agent),
    )
    builder.add_node(
        StageName.RISK_REVIEW_REPORT.value,
        make_risk_review_report_node(risk_review_report_agent),
    )

    # One straight line, START -> ... -> END, in PIPELINE_ORDER.
    builder.add_edge(START, PIPELINE_ORDER[0].value)
    for earlier, later in zip(PIPELINE_ORDER, PIPELINE_ORDER[1:]):
        builder.add_edge(earlier.value, later.value)
    builder.add_edge(PIPELINE_ORDER[-1].value, END)

    return NyayaSahayakGraph(builder.compile())


def build_default_agents(llm, *, authority_retriever: Optional[Any] = None) -> dict:
    """Construct the five agents from one LLM provider.

    The RiskReviewReportAgent is given the same provider, but only ever uses
    it to phrase a narrative sentence; its risk levels stay deterministic.
    """
    return {
        "case_understanding_agent": CaseUnderstandingAgent(llm),
        "evidence_conflict_agent": EvidenceConflictAgent(llm),
        "authority_citation_agent": AuthorityCitationAgent(llm, authority_retriever),
        "counter_argument_agent": CounterArgumentAgent(llm),
        "risk_review_report_agent": RiskReviewReportAgent(llm),
    }


def run_pipeline(state: NyayaSahayakState, *, llm, authority_retriever: Optional[Any] = None) -> NyayaSahayakState:
    """Convenience: build the default graph and run one case through it."""
    graph = build_nyaya_graph(**build_default_agents(llm, authority_retriever=authority_retriever))
    return graph.run(state)
