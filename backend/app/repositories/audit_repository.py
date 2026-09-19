"""Audit and AnalysisRun MongoDB repositories."""
from __future__ import annotations

from typing import Any
from ..models.audit import AnalysisRun, AuditEvent
from ..models.risk import RiskItem
from .base_repository import BaseRepository


class AnalysisRunRepository(BaseRepository[AnalysisRun]):
    def __init__(self) -> None:
        super().__init__("analysis_runs")

    def get_latest_by_case(self, case_id: str) -> AnalysisRun | None:
        raws = self.find_many({"case_id": case_id}, sort=[("started_at", -1)], limit=1)
        return AnalysisRun.from_dict(raws[0]) if raws else None

    def create(self, run: AnalysisRun) -> AnalysisRun:
        self.insert(run.to_dict())
        return run

    def update(self, run: AnalysisRun) -> AnalysisRun:
        self.update_one({"id": run.id}, run.to_dict())
        return run


class AuditRepository(BaseRepository[AuditEvent]):
    def __init__(self) -> None:
        super().__init__("audit_events")

    def list_by_case(self, case_id: str) -> list[AuditEvent]:
        raws = self.find_many({"case_id": case_id}, sort=[("created_at", 1)])
        return [AuditEvent.from_dict(r) for r in raws]

    def create(self, event: AuditEvent) -> AuditEvent:
        self.insert(event.to_dict())
        return event


analysis_run_repository = AnalysisRunRepository()
audit_repository = AuditRepository()

class RiskItemRepository(BaseRepository[RiskItem]):
    def __init__(self) -> None:
        super().__init__("risk_items")

    def list_by_case(self, case_id: str) -> list[RiskItem]:
        raws = self.find_many({"case_id": case_id}, sort=[("created_at", 1)])
        return [RiskItem.from_dict(r) for r in raws]

    def create(self, item: RiskItem) -> RiskItem:
        self.insert(item.to_dict())
        return item


risk_item_repository = RiskItemRepository()
