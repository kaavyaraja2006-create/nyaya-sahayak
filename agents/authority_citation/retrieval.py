"""The retrieval seam.

The agent never fetches law itself. It asks an `AuthorityRetriever` for
candidate authorities for a citation, and then applies its own identity
check to whatever comes back (see agent.py), so a retriever can never smuggle
in a "similar" authority for a citation it does not actually match.

Today the only implementation is `InMemoryAuthorityRetriever`, which serves
authorities supplied in the agent's input (or mocked in tests). Later, an
implementation backed by approved legal databases/APIs can be passed to the
agent's constructor without changing anything else:

    AuthorityCitationAgent(llm=..., retriever=MyApprovedSourceRetriever(...))

Contract for implementers:
  * Return only authorities whose text you actually hold. Never synthesise one.
  * Return an empty sequence when nothing matches. Do not raise for "not found".
  * Declare parallel citations in `SuppliedAuthority.aliases`; the agent's
    identity check is normalised equality against citation/title/aliases.
  * Raise for genuine failures (timeout, auth); the agent turns that into a
    REQUIRES_HUMAN_REVIEW finding rather than SOURCE_NOT_FOUND.
"""
from __future__ import annotations

from typing import Protocol, Sequence

from .citations import authority_matches_citation
from .schemas import CitedAuthority, SuppliedAuthority


class AuthorityRetriever(Protocol):
    def retrieve(self, cited: CitedAuthority) -> Sequence[SuppliedAuthority]:
        ...


class InMemoryAuthorityRetriever:
    """Serves a fixed list of supplied authorities. Also the test double."""

    def __init__(self, authorities: Sequence[SuppliedAuthority]) -> None:
        self._authorities = list(authorities)

    def retrieve(self, cited: CitedAuthority) -> Sequence[SuppliedAuthority]:
        return [a for a in self._authorities if authority_matches_citation(cited, a)]
