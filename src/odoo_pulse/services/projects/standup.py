"""Daily standup digest report service."""

from __future__ import annotations

from datetime import timedelta

from ...common.dates import parse_when
from ...common.paging import fetch_with_truncation
from ..report_context import build_report_context
from .queries import resolve_user_names
from .subtasks import (
    task_closed_scope,
    task_matches_scope,
    task_scope_warning,
)


def build_standup_digest(
    client,
    *,
    project: str,
    exclude_stages: list[str] | None = None,
    lookahead_days: int = 7,
    timezone_offset: int = 7,
) -> str:
    if exclude_stages is None:
        exclude_stages = ["Done", "Cancelled", "Delivered"]

    context = build_report_context(client, timezone_offset=timezone_offset)
    today = context.today
    today_str = today.strftime("%d/%m/%Y")
    cutoff = today + timedelta(days=lookahead_days)

    domain = [
        ("project_id.name", "ilike", project),
        ("parent_id", "!=", False),
        ("stage_id.name", "not in", exclude_stages),
    ]

    scope_domain, scope_fields, scope_strategy = task_closed_scope(
        client, closed=False, stage_names=exclude_stages)
    domain.extend(scope_domain)
    scope_warning = task_scope_warning(scope_strategy)

    tasks, truncation = fetch_with_truncation(
        client, "project.task", domain,
        fields=["id", "name", "user_ids", "stage_id",
                "date_deadline", "priority", *scope_fields],
        limit=200, order="date_deadline",
    )

    # Defensively re-filter client-side (stable state/is_closed schemas
    # already filter server-side; the stage-name fallback needs this).
    tasks = [t for t in tasks if task_matches_scope(
        t, scope_strategy, closed=False, stage_names=exclude_stages)]

    # Resolve user names including archived users (shared helper).
    all_uid = {uid for t in tasks for uid in t.get("user_ids", [])}
    user_map = resolve_user_names(client, all_uid)

    # Filter: exactly 1 assignee
    filtered = [t for t in tasks if len(t.get("user_ids", [])) == 1]

    overdue: list[dict] = []
    today_tasks: list[dict] = []
    upcoming: list[dict] = []
    no_deadline: list[dict] = []

    for t in filtered:
        uid = t["user_ids"][0]
        entry = {
            "id": t["id"],
            "name": t["name"],
            "assignee": user_map.get(uid, f"User#{uid}"),
            "priority": "High" if t.get("priority") == "1" else "Normal",
            "deadline": None,
        }
        dd = parse_when(t.get("date_deadline"), timezone_offset)
        if dd is None:
            no_deadline.append(entry)
            continue
        entry["deadline"] = dd
        if dd < today:
            overdue.append(entry)
        elif dd == today:
            today_tasks.append(entry)
        elif dd <= cutoff:
            upcoming.append(entry)

    overdue.sort(key=lambda x: x["deadline"])
    today_tasks.sort(key=lambda x: x["name"])
    upcoming.sort(key=lambda x: x["deadline"])
    no_deadline.sort(key=lambda x: x["name"])

    def days_ago(d) -> str:
        n = (today - d).days
        return f"{n} ngày trước" if n > 1 else "hôm qua"

    def task_table(rows: list[dict], deadline_col: str, deadline_fn) -> list[str]:
        out = [
            f"| # | Task | Assignee | {deadline_col} |",
            f"|---|------|----------|{''.join(['-'] * len(deadline_col))}--|",
        ]
        for t in rows:
            raw_name = t["name"].replace("|", "\\|")
            name = f"🔴 {raw_name}" if t["priority"] == "High" else raw_name
            out.append(f"| #{t['id']} | {name} | {t['assignee']} | {deadline_fn(t)} |")
        return out

    lines = [f"## 🗓️ Daily Standup — {project}", f"**{today_str}**"]
    if scope_warning:
        lines.append(f"> ⚠️ {scope_warning}")
    lines.append("")

    if truncation:
        lines.append(
            f"⚠️ Chỉ hiển thị {truncation['fetched']}/"
            f"{truncation['total_matching']} task — dữ liệu bị cắt bớt.")
        lines.append("")

    if overdue:
        lines.append(f"### ❌ Quá hạn ({len(overdue)})")
        lines += task_table(overdue, "Quá hạn", lambda t: days_ago(t["deadline"]))
        lines.append("")

    if today_tasks:
        lines.append(f"### ⏳ Hôm nay ({len(today_tasks)})")
        lines += task_table(today_tasks, "Deadline", lambda t: "Hôm nay")
        lines.append("")

    if upcoming:
        lines.append(f"### ⭕ Sắp đến hạn ({len(upcoming)})")
        lines += task_table(upcoming, "Deadline", lambda t: t["deadline"].strftime("%d/%m/%Y"))
        lines.append("")

    if no_deadline:
        lines.append(f"### ❓ Chưa có deadline ({len(no_deadline)})")
        lines += task_table(no_deadline, "Deadline", lambda t: "—")
        lines.append("")

    total = len(overdue) + len(today_tasks) + len(upcoming) + len(no_deadline)
    if total == 0:
        lines.append("✅ Không có task pending nào hôm nay.")
    else:
        parts = []
        if overdue:
            parts.append(f"**{len(overdue)} quá hạn**")
        if today_tasks:
            parts.append(f"**{len(today_tasks)} hôm nay**")
        if upcoming:
            parts.append(f"{len(upcoming)} sắp đến")
        if no_deadline:
            parts.append(f"{len(no_deadline)} chưa có deadline")
        lines.append(f"---\n📊 Tổng: {' · '.join(parts)}")

    return "\n".join(lines)
