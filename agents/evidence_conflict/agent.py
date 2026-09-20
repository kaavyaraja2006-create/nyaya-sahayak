"""EvidenceConflictAgent.

Maps claims to evidence, and reports support, contradiction, missing
evidence, insufficient support, and conflicts between sources. This agent
detects relationships; it never resolves them (see prompts.py). It never
returns free-form text: every run produces an EvidenceConflictResult, a
fully typed Pydantic model.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Protocol

from pydantic import ValidationError

from ..case_understanding.schemas import Claim
from .prompts import EVIDENCE_CONFLICT_SYSTEM_PROMPT
from .schemas import (
    Conflict,
    ConflictSide,
    ClaimEvidenceRelationship,
    EvidenceConflictInput,
    EvidenceConflictResult,
    EvidenceItem,
    RejectedFinding,
    SupportGap,
)
from .validation import (
    enforce_all_references_resolve,
    resolve_claim,
    resolve_evidence,
    resolve_side,
)

log = logging.getLogger("nyayasahayak.agents.evidence_conflict")

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)


class LLMProvider(Protocol):
    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        ...


class EvidenceConflictAgent:
    """Detects (never resolves) relationships between claims and evidence.

    Usage:
        agent = EvidenceConflictAgent(llm=my_provider)
        result = agent.run(EvidenceConflictInput(case_id="NS-2026-001", claims=[...], evidence=[...]))
    """

    system_prompt: str = EVIDENCE_CONFLICT_SYSTEM_PROMPT

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    # -- public API -------------------------------------------------------

    def run(self, input_data: EvidenceConflictInput) -> EvidenceConflictResult:
        claims_by_id: dict[str, Claim] = {c.claim_id: c for c in input_data.claims}
        evidence_by_id: dict[str, EvidenceItem] = {e.evidence_id: e for e in input_data.evidence}
        warnings: list[str] = []
        degraded = False

        user_prompt = self._build_user_prompt(input_data)

        try:
            raw_output = self._llm.generate(system_prompt=self.system_prompt, user_prompt=user_prompt)
        except Exception as exc:  # noqa: BLE001
            log.warning("EvidenceConflictAgent: LLM call failed: %s", exc)
            return EvidenceConflictResult(
                case_id=input_data.case_id,
                claims_processed=list(claims_by_id.keys()),
                evidence_processed=list(evidence_by_id.keys()),
                warnings=[f"Model call failed: {exc}. No findings were produced this run."],
                degraded=True,
            )

        try:
            payload = self._parse_model_output(raw_output)
        except ValueError as exc:
            log.warning("EvidenceConflictAgent: could not parse model output: %s", exc)
            return EvidenceConflictResult(
                case_id=input_data.case_id,
                claims_processed=list(claims_by_id.keys()),
                evidence_processed=list(evidence_by_id.keys()),
                warnings=[f"Model output was not valid JSON ({exc}); no findings were produced."],
                degraded=True,
            )

        relationships: list[ClaimEvidenceRelationship] = []
        conflicts: list[Conflict] = []
        gaps: list[SupportGap] = []
        rejected: list[RejectedFinding] = []

        for i, raw in enumerate(payload.get("relationships", []), start=1):
            result = self._build_relationship(i, raw, claims_by_id, evidence_by_id)
            if isinstance(result, RejectedFinding):
                rejected.append(result)
            else:
                relationships.append(result)

        for i, raw in enumerate(payload.get("conflicts", []), start=1):
            result = self._build_conflict(i, raw, claims_by_id, evidence_by_id)
            if isinstance(result, RejectedFinding):
                rejected.append(result)
            else:
                conflicts.append(result)

        for i, raw in enumerate(payload.get("support_gaps", []), start=1):
            result = self._build_gap(i, raw, claims_by_id, evidence_by_id)
            if isinstance(result, RejectedFinding):
                rejected.append(result)
            else:
                gaps.append(result)

        violations = enforce_all_references_resolve(relationships, conflicts, gaps, claims_by_id, evidence_by_id)
        if violations:
            # Should be unreachable given every builder above resolves ids
            # before construction, but this is the hard backstop against
            # ever shipping a finding with a dangling reference.
            degraded = True
            for v in violations:
                log.error("EvidenceConflictAgent reference invariant violated: %s", v)
            bad_rel_ids = {m.split()[1] for m in violations if m.startswith("relationship")}
            bad_conf_ids = {m.split()[1] for m in violations if m.startswith("conflict")}
            bad_gap_ids = {m.split()[1] for m in violations if m.startswith("support_gap")}
            relationships = [r for r in relationships if r.relationship_id not in bad_rel_ids]
            conflicts = [c for c in conflicts if c.conflict_id not in bad_conf_ids]
            gaps = [g for g in gaps if g.gap_id not in bad_gap_ids]
            warnings.append(
                "One or more findings failed a final reference re-check and were removed."
            )

        if rejected:
            warnings.append(
                f"{len(rejected)} candidate finding(s) were rejected for referencing unknown "
                "ids or lacking valid provenance and are excluded from the result "
                "(see `rejected_findings`)."
            )

        return EvidenceConflictResult(
            case_id=input_data.case_id,
            relationships=relationships,
            conflicts=conflicts,
            support_gaps=gaps,
            rejected_findings=rejected,
            claims_processed=list(claims_by_id.keys()),
            evidence_processed=list(evidence_by_id.keys()),
            warnings=warnings,
            degraded=degraded,
        )

    # -- builders: each either returns a valid model or a RejectedFinding ---

    def _build_relationship(
        self, index: int, raw: dict, claims_by_id: dict[str, Claim], evidence_by_id: dict[str, EvidenceItem]
    ) -> ClaimEvidenceRelationship | RejectedFinding:
        if not isinstance(raw, dict):
            return RejectedFinding(kind="relationship", raw={"value": raw}, reason="Entry was not a JSON object.")

        claim, claim_res = resolve_claim(raw.get("claim_id"), claims_by_id)
        if not claim_res.ok:
            return RejectedFinding(kind="relationship", raw=raw, reason=claim_res.reason)

        evidence, evidence_res = resolve_evidence(raw.get("evidence_id"), evidence_by_id)
        if not evidence_res.ok:
            return RejectedFinding(kind="relationship", raw=raw, reason=evidence_res.reason)

        try:
            return ClaimEvidenceRelationship(
                relationship_id=raw.get("relationship_id") or f"REL-{index:03d}",
                claim_id=claim.claim_id,
                evidence_id=evidence.evidence_id,
                relationship_type=raw.get("relationship_type"),
                reasoning=raw.get("reasoning", ""),
                claim_source=claim.source,
                evidence_source=evidence.source,
            )
        except ValidationError as exc:
            return RejectedFinding(kind="relationship", raw=raw, reason=self._describe(exc))

    def _build_conflict(
        self, index: int, raw: dict, claims_by_id: dict[str, Claim], evidence_by_id: dict[str, EvidenceItem]
    ) -> Conflict | RejectedFinding:
        if not isinstance(raw, dict):
            return RejectedFinding(kind="conflict", raw={"value": raw}, reason="Entry was not a JSON object.")

        side_a_raw = raw.get("side_a")
        side_b_raw = raw.get("side_b")
        if not isinstance(side_a_raw, dict) or not isinstance(side_b_raw, dict):
            return RejectedFinding(
                kind="conflict", raw=raw, reason="A conflict must supply both side_a and side_b as objects."
            )

        resolved_a, res_a = resolve_side(side_a_raw, claims_by_id, evidence_by_id)
        if not res_a.ok:
            return RejectedFinding(kind="conflict", raw=raw, reason=f"side_a: {res_a.reason}")

        resolved_b, res_b = resolve_side(side_b_raw, claims_by_id, evidence_by_id)
        if not res_b.ok:
            return RejectedFinding(kind="conflict", raw=raw, reason=f"side_b: {res_b.reason}")

        try:
            return Conflict(
                conflict_id=raw.get("conflict_id") or f"CNF-{index:03d}",
                conflict_type=raw.get("conflict_type"),
                description=raw.get("description", ""),
                side_a=ConflictSide(**resolved_a),
                side_b=ConflictSide(**resolved_b),
            )
        except ValidationError as exc:
            return RejectedFinding(kind="conflict", raw=raw, reason=self._describe(exc))

    def _build_gap(
        self, index: int, raw: dict, claims_by_id: dict[str, Claim], evidence_by_id: dict[str, EvidenceItem]
    ) -> SupportGap | RejectedFinding:
        if not isinstance(raw, dict):
            return RejectedFinding(kind="support_gap", raw={"value": raw}, reason="Entry was not a JSON object.")

        claim, claim_res = resolve_claim(raw.get("claim_id"), claims_by_id)
        if not claim_res.ok:
            return RejectedFinding(kind="support_gap", raw=raw, reason=claim_res.reason)

        related_ids = raw.get("related_evidence_ids") or []
        if not isinstance(related_ids, list):
            return RejectedFinding(kind="support_gap", raw=raw, reason="related_evidence_ids must be a list.")
        for eid in related_ids:
            _, res = resolve_evidence(eid, evidence_by_id)
            if not res.ok:
                return RejectedFinding(kind="support_gap", raw=raw, reason=res.reason)

        try:
            return SupportGap(
                gap_id=raw.get("gap_id") or f"GAP-{index:03d}",
                claim_id=claim.claim_id,
                claim_source=claim.source,
                gap_type=raw.get("gap_type"),
                related_evidence_ids=related_ids,
                note=raw.get("note", ""),
            )
        except ValidationError as exc:
            return RejectedFinding(kind="support_gap", raw=raw, reason=self._describe(exc))

    # -- prompt / parsing -------------------------------------------------

    def _build_user_prompt(self, input_data: EvidenceConflictInput) -> str:
        lines = [f"Case ID: {input_data.case_id}", "", "CLAIMS:"]
        for claim in input_data.claims:
            lines.append(
                f"- claim_id={claim.claim_id} | type={claim.claim_type.value} | "
                f"speaker={claim.speaker or '(unattributed)'} | text: {claim.claim_text}"
            )
        lines.append("")
        lines.append("EVIDENCE:")
        if not input_data.evidence:
            lines.append("(none supplied)")
        for item in input_data.evidence:
            lines.append(
                f"- evidence_id={item.evidence_id} | type={item.evidence_type.value} | "
                f"date={item.item_date or 'unknown'} | description: {item.description}"
            )
        lines.append("")
        lines.append(
            "Using ONLY the claim_id and evidence_id values listed above, report relationships, "
            "conflicts, and support gaps as instructed."
        )
        return "\n".join(lines)

    @staticmethod
    def _parse_model_output(raw_output: str) -> dict:
        text = _CODE_FENCE_RE.sub("", raw_output).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(str(exc)) from exc
        if not isinstance(parsed, dict):
            raise ValueError("expected a JSON object with relationships/conflicts/support_gaps arrays")
        for key in ("relationships", "conflicts", "support_gaps"):
            parsed.setdefault(key, [])
            if not isinstance(parsed[key], list):
                raise ValueError(f"\"{key}\" must be a JSON array")
        return parsed

    @staticmethod
    def _describe(exc: ValidationError) -> str:
        parts = []
        for error in exc.errors():
            loc = ".".join(str(p) for p in error["loc"]) or "<root>"
            parts.append(f"{loc}: {error['msg']}")
        return "; ".join(parts) or str(exc)
