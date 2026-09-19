"""The seam between the FastAPI/MongoDB backend and the five-agent LangGraph
pipeline in the top-level `agents` package.

Direction of dependency is one-way on purpose:

    backend  ->  agents          (allowed, through this package only)
    agents   ->  backend         (never)

The agents know nothing about MongoDB. Everything they need arrives as their
own Pydantic input objects, built here from backend domain models; everything
they produce comes back as their own result objects and is translated here
into backend domain models for the repository layer.
"""
from .inputs import build_state, evidence_from_documents
from .llm import build_llm_provider
from .persistence import persist_pipeline_output
from .pipeline import build_graph, run_graph

__all__ = [
    "build_graph",
    "build_llm_provider",
    "build_state",
    "evidence_from_documents",
    "persist_pipeline_output",
    "run_graph",
]
