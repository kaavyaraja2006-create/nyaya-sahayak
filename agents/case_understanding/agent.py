"""CaseUnderstandingAgent.

Converts uploaded case material into atomic, source-grounded claims. This is
an extraction agent only — see prompts.py and the module docstring rules it
enforces. It never decides guilt, credibility, liability, admissibility, or
outcome, and it never returns free-form text: every run produces a
CaseUnderstandingResult, a fully typed Pydantic model.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Protocol

from pydantic import ValidationError

from .prompts import CASE_UNDERSTANDING_SYSTEM_PROMPT
from .schemas import (
    CaseUnderstandingInput,
    CaseUnderstandingResult,
    Claim,
    RejectedClaim,
    SourceDocument,
)
from .validation import check_claim_provenance, enforce_no_false_verification

log = logging.getLogger("nyayasahayak.agents.case_understanding")

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)


class LLMProvider(Protocol):
    """Minimal contract the agent needs from a model backend.

    Kept intentionally narrow (one method, two strings in, one string out) so
    tests can supply a trivial fake without any real API dependency, and so
    swapping the underlying model provider never touches this agent's logic.
    """

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        ...


class CaseUnderstandingAgent:
    """Extracts atomic, source-grounded claims from case material.

    Usage:
        agent = CaseUnderstandingAgent(llm=my_provider)
        result = agent.run(CaseUnderstandingInput(case_id="NS-2026-001", documents=[...]))
    """

    system_prompt: str = CASE_UNDERSTANDING_SYSTEM_PROMPT

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    # -- public API ---------------------------------------------------

    def run(self, input_data: CaseUnderstandingInput) -> CaseUnderstandingResult:
        documents = {doc.document_id: doc for doc in input_data.documents}
        warnings: list[str] = []
        degraded = False

        user_prompt = self._build_user_prompt(input_data)

        try:
            raw_output = self._llm.generate(
                system_prompt=self.system_prompt, user_prompt=user_prompt
            )
        except Exception as exc:  # noqa: BLE001 - any provider failure is non-fatal here
            log.warning("CaseUnderstandingAgent: LLM call failed: %s", exc)
            return CaseUnderstandingResult(
                case_id=input_data.case_id,
                claims=[],
                rejected_claims=[],
                documents_processed=list(documents.keys()),
                warnings=[f"Model call failed: {exc}. No claims were extracted this run."],
                degraded=True,
            )

        try:
            raw_claims = self._parse_model_output(raw_output)
        except ValueError as exc:
            log.warning("CaseUnderstandingAgent: could not parse model output: %s", exc)
            return CaseUnderstandingResult(
                case_id=input_data.case_id,
                claims=[],
                rejected_claims=[],
                documents_processed=list(documents.keys()),
                warnings=[f"Model output was not valid JSON ({exc}); no claims were extracted."],
                degraded=True,
            )

        claims: list[Claim] = []
        rejected: list[RejectedClaim] = []
        seen_ids: set[str] = set()

        for position, raw_claim in enumerate(raw_claims, start=1):
            if not isinstance(raw_claim, dict):
                rejected.append(
                    RejectedClaim(raw={"value": raw_claim}, reason="Claim entry was not a JSON object.")
                )
                continue

            candidate = dict(raw_claim)
            candidate.setdefault("claim_id", f"CU-{position:03d}")
            # Never trust the model's own verification_status; it is recomputed below.
            candidate.pop("verification_status", None)
            candidate.pop("verification_notes", None)

            try:
                claim = Claim(**candidate)
            except ValidationError as exc:
                rejected.append(
                    RejectedClaim(raw=raw_claim, reason=self._describe_validation_error(exc))
                )
                continue

            if claim.claim_id in seen_ids:
                original_id = claim.claim_id
                claim.claim_id = f"{original_id}-DUP{position:03d}"
                warnings.append(
                    f"Duplicate claim_id {original_id!r} from the model was renamed to "
                    f"{claim.claim_id!r} to keep claim_id unique."
                )
            seen_ids.add(claim.claim_id)

            check = check_claim_provenance(claim, documents)
            claim.verification_status = check.status
            claim.verification_notes = check.notes

            claims.append(claim)

        violations = enforce_no_false_verification(claims, documents)
        if violations:
            # Should be unreachable given check_claim_provenance is the sole
            # writer of verification_status above, but this is the hard
            # backstop against ever shipping a falsely-VERIFIED claim.
            degraded = True
            for v in violations:
                log.error("CaseUnderstandingAgent provenance invariant violated: %s", v)
            for claim in claims:
                if claim.verification_status.value == "VERIFIED":
                    recheck = check_claim_provenance(claim, documents)
                    claim.verification_status = recheck.status
                    claim.verification_notes = recheck.notes
            warnings.append(
                "One or more claims failed a final provenance re-check and were downgraded "
                "to UNVERIFIED."
            )

        if rejected:
            warnings.append(
                f"{len(rejected)} candidate claim(s) were rejected for lacking any valid "
                "provenance and are excluded from `claims` (see `rejected_claims`)."
            )

        referenced_unknown_docs = {
            c.source.document_id
            for c in claims
            if c.source.document_id and c.source.document_id not in documents
        }
        for doc_id in sorted(referenced_unknown_docs):
            warnings.append(
                f"One or more claims cite document_id {doc_id!r}, which was not among the "
                "documents supplied to this run."
            )

        return CaseUnderstandingResult(
            case_id=input_data.case_id,
            claims=claims,
            rejected_claims=rejected,
            documents_processed=list(documents.keys()),
            warnings=warnings,
            degraded=degraded,
        )

    # -- internals ------------------------------------------------------

    def _build_user_prompt(self, input_data: CaseUnderstandingInput) -> str:
        sections: list[str] = [
            f"Case ID: {input_data.case_id}",
            "",
            "Below is the complete set of case material for this run. Extract claims ONLY "
            "from what appears below. Do not use outside knowledge of this case, this area "
            "of law, or these parties.",
            "",
        ]
        for doc in input_data.documents:
            sections.append(self._render_document(doc))
        return "\n".join(sections)

    @staticmethod
    def _render_document(doc: SourceDocument) -> str:
        lines = [
            "-----",
            f"document_id: {doc.document_id}",
            f"document_kind: {doc.document_kind.value}",
            f"title: {doc.title or '(untitled)'}",
            f"is_transcript: {doc.is_transcript}",
        ]
        if doc.pages:
            for page in doc.pages:
                lines.append(f"[page {page.number}]")
                for para in page.paragraphs:
                    lines.append(f"  [paragraph {para.number}] {para.text}")
        if doc.utterances:
            for utt in doc.utterances:
                speaker = utt.speaker or "(unattributed)"
                lines.append(f"[{utt.location}] {speaker}: {utt.text}")
        if not doc.pages and not doc.utterances:
            lines.append(doc.raw_text)
        lines.append("-----")
        return "\n".join(lines)

    @staticmethod
    def _parse_model_output(raw_output: str) -> list[dict]:
        text = _CODE_FENCE_RE.sub("", raw_output).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(str(exc)) from exc

        if isinstance(parsed, dict) and "claims" in parsed:
            claims = parsed["claims"]
        elif isinstance(parsed, list):
            claims = parsed
        else:
            raise ValueError("expected a JSON object with a \"claims\" array, or a bare JSON array")

        if not isinstance(claims, list):
            raise ValueError("\"claims\" must be a JSON array")
        return claims

    @staticmethod
    def _describe_validation_error(exc: ValidationError) -> str:
        messages = []
        for error in exc.errors():
            loc = ".".join(str(p) for p in error["loc"]) or "<root>"
            messages.append(f"{loc}: {error['msg']}")
        return "; ".join(messages) or str(exc)
