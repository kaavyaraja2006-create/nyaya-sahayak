"""Building and running the existing five-agent LangGraph pipeline.

This module deliberately contains no pipeline of its own. It calls
`agents.graph.build_nyaya_graph` with the agents from
`agents.graph.build_default_agents`, substituting only the citation-supplying
wrapper around the AuthorityCitationAgent (see citations.py). If a sixth stage
is ever added to the product, it is added in the agents package, not here.
"""
from __future__ import annotations

import logging

from agents.graph import NyayaSahayakState, build_default_agents, build_nyaya_graph

from .citations import CitationSupplyingAuthorityAgent
from .llm import build_llm_provider

log = logging.getLogger("nyayasahayak.agents_bridge.pipeline")


def build_graph(llm=None, *, authority_retriever=None, supply_citations: bool = True):
    """Return the compiled NyayaSahayakGraph the backend runs cases through."""
    provider = llm or build_llm_provider()
    agents = build_default_agents(provider, authority_retriever=authority_retriever)
    if supply_citations:
        agents["authority_citation_agent"] = CitationSupplyingAuthorityAgent(
            agents["authority_citation_agent"]
        )
    return build_nyaya_graph(**agents)


def run_graph(
    state: NyayaSahayakState,
    *,
    llm=None,
    authority_retriever=None,
    supply_citations: bool = True,
) -> NyayaSahayakState:
    """Run one case through the five agents. Blocking — call it in a thread.

    The graph never raises for a failed stage: it records the failure in
    `stage_log`/`errors` and leaves that stage's result as None, so the caller
    always gets a state back and can report exactly what did and did not run.
    """
    graph = build_graph(llm, authority_retriever=authority_retriever, supply_citations=supply_citations)
    return graph.run(state)
