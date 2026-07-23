"""Immutable date and company scope shared by composed report services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ..common.dates import today_in_tz
from ..common.reporting import resolve_company_id


@dataclass(frozen=True, slots=True)
class ReportContext:
    client: Any
    today: date
    timezone_offset: int
    company_id: int | None

    @property
    def company_domain(self) -> tuple[tuple, ...]:
        return self.company_filter()

    def company_filter(self, field: str = "company_id") -> tuple[tuple, ...]:
        if self.company_id is None:
            return ()
        return ((field, "=", self.company_id),)


def build_report_context(
    client,
    *,
    timezone_offset: int,
    company: str | int | None = None,
) -> ReportContext:
    return ReportContext(
        client=client,
        today=today_in_tz(timezone_offset),
        timezone_offset=timezone_offset,
        company_id=resolve_company_id(client, company),
    )
