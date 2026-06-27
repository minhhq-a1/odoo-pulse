"""Read-only domain tools for Human Resources.

Covered models:
  - hr.employee        (employees)
  - hr.department      (departments)
  - hr.leave           (time off / leave requests)
  - hr.expense         (expenses)
  - hr.job             (job positions, recruitment)
  - hr.applicant       (recruitment applicants)
  - hr.attendance      (check in/out records)

Note: some models (hr.expense, recruitment) require their app to be installed.
Missing models surface as a friendly error rather than crashing.
"""

from __future__ import annotations

from .runtime import date_domain, get_client, mcp, name_domain, safe


@mcp.tool()
def list_employees(
    query: str | None = None, department: str | None = None, limit: int = 20
) -> str:
    """List employees (hr.employee).

    Args:
        query: Free text matched against name, work email or job title.
        department: Filter by department name.
        limit: Max results.
    """
    domain = name_domain(query, ["name", "work_email", "job_title"])
    if department:
        domain.append(("department_id.name", "ilike", department))
    return safe(
        lambda: get_client().search_read(
            "hr.employee",
            domain=domain,
            fields=[
                "name",
                "job_title",
                "department_id",
                "work_email",
                "work_phone",
                "parent_id",
            ],
            limit=limit,
            order="name",
        )
    )


@mcp.tool()
def list_departments(limit: int = 50) -> str:
    """List HR departments (hr.department) with employee headcount."""
    return safe(
        lambda: get_client().search_read(
            "hr.department",
            domain=[],
            fields=["name", "manager_id", "parent_id", "total_employee"],
            limit=limit,
            order="name",
        )
    )


@mcp.tool()
def list_time_off(
    employee: str | None = None,
    state: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> str:
    """List time off / leave requests (hr.leave).

    Args:
        employee: Filter by employee name.
        state: draft, confirm, refuse, validate1 or validate (approved).
        date_from: Inclusive lower bound on the leave start date (YYYY-MM-DD).
        date_to: Inclusive upper bound on the leave start date (YYYY-MM-DD).
        limit: Max results.
    """
    domain: list = []
    if employee:
        domain.append(("employee_id.name", "ilike", employee))
    if state:
        domain.append(("state", "=", state))
    domain += date_domain("date_from", date_from, date_to)
    return safe(
        lambda: get_client().search_read(
            "hr.leave",
            domain=domain,
            fields=[
                "employee_id",
                "holiday_status_id",
                "date_from",
                "date_to",
                "number_of_days",
                "state",
            ],
            limit=limit,
            order="date_from desc",
        )
    )


@mcp.tool()
def list_expenses(
    employee: str | None = None, state: str | None = None, limit: int = 20
) -> str:
    """List employee expenses (hr.expense).

    Args:
        employee: Filter by employee name.
        state: draft, reported, approved, done or refused.
        limit: Max results.
    """
    domain: list = []
    if employee:
        domain.append(("employee_id.name", "ilike", employee))
    if state:
        domain.append(("state", "=", state))
    return safe(
        lambda: get_client().search_read(
            "hr.expense",
            domain=domain,
            fields=["name", "employee_id", "product_id", "total_amount", "date", "state"],
            limit=limit,
            order="date desc",
        )
    )


@mcp.tool()
def list_job_positions(query: str | None = None, limit: int = 20) -> str:
    """List recruitment job positions (hr.job) with expected/recruited counts."""
    domain = name_domain(query, ["name"])
    return safe(
        lambda: get_client().search_read(
            "hr.job",
            domain=domain,
            fields=[
                "name",
                "department_id",
                "no_of_recruitment",
                "no_of_employee",
            ],
            limit=limit,
            order="name",
        )
    )


@mcp.tool()
def list_applicants(
    job: str | None = None, stage: str | None = None, limit: int = 20
) -> str:
    """List recruitment applicants (hr.applicant).

    Args:
        job: Filter by the job position name applied for.
        stage: Filter by recruitment stage name (e.g. 'New', 'Interview').
        limit: Max results.
    """
    domain: list = []
    if job:
        domain.append(("job_id.name", "ilike", job))
    if stage:
        domain.append(("stage_id.name", "ilike", stage))
    return safe(
        lambda: get_client().search_read(
            "hr.applicant",
            domain=domain,
            fields=[
                "partner_name",
                "job_id",
                "stage_id",
                "email_from",
                "create_date",
            ],
            limit=limit,
            order="create_date desc",
        )
    )


@mcp.tool()
def list_attendances(
    employee: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> str:
    """List attendance records (hr.attendance) - employee check in/out.

    Args:
        employee: Filter by employee name.
        date_from: Inclusive lower bound on check-in (YYYY-MM-DD).
        date_to: Inclusive upper bound on check-in (YYYY-MM-DD).
        limit: Max results.
    """
    domain: list = []
    if employee:
        domain.append(("employee_id.name", "ilike", employee))
    domain += date_domain("check_in", date_from, date_to)
    return safe(
        lambda: get_client().search_read(
            "hr.attendance",
            domain=domain,
            fields=["employee_id", "check_in", "check_out", "worked_hours"],
            limit=limit,
            order="check_in desc",
        )
    )
