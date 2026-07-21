"""Read-only domain tools for engagement / collaboration modules.

Covered models:
  - event.event           (Events)
  - event.registration    (Event attendees)
  - calendar.event        (Calendar meetings)
  - mail.activity         (Scheduled activities / to-dos)
  - survey.survey         (Surveys)
  - mailing.mailing       (Email marketing campaigns)
"""

from __future__ import annotations

from .runtime import date_domain, get_client, mcp, name_domain, safe


# --- Events -------------------------------------------------------------------


@mcp.tool()
def list_events(
    query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> str:
    """List events (event.event).

    Args:
        query: Free text matched against the event name.
        date_from: Inclusive lower bound on the event start date (YYYY-MM-DD).
        date_to: Inclusive upper bound on the event start date (YYYY-MM-DD).
        limit: Max results.
    """
    def run():
        domain = name_domain(query, ["name"])
        domain.extend(date_domain("date_begin", date_from, date_to, as_datetime=True))
        return get_client().search_read(
            "event.event",
            domain=domain,
            fields=["name", "date_begin", "date_end", "seats_expected", "seats_limited", "address_id"],
            limit=limit,
            order="date_begin desc",
        )

    return safe(run)


@mcp.tool()
def list_event_registrations(
    event: str | None = None, state: str | None = None, limit: int = 20
) -> str:
    """List event registrations / attendees (event.registration).

    Args:
        event: Filter by event name.
        state: draft, open (confirmed), done (attended) or cancel.
        limit: Max results.
    """
    domain: list = []
    if event:
        domain.append(("event_id.name", "ilike", event))
    if state:
        domain.append(("state", "=", state))
    return safe(
        lambda: get_client().search_read(
            "event.registration",
            domain=domain,
            fields=["name", "event_id", "email", "phone", "state"],
            limit=limit,
            order="create_date desc",
        )
    )


# --- Calendar -----------------------------------------------------------------


@mcp.tool()
def list_calendar_events(
    query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> str:
    """List calendar meetings (calendar.event).

    Args:
        query: Free text matched against the meeting title.
        date_from: Inclusive lower bound on the start datetime (YYYY-MM-DD).
        date_to: Inclusive upper bound on the start datetime (YYYY-MM-DD).
        limit: Max results.
    """
    def run():
        domain = name_domain(query, ["name"])
        domain.extend(date_domain("start", date_from, date_to, as_datetime=True))
        return get_client().search_read(
            "calendar.event",
            domain=domain,
            fields=["name", "start", "stop", "user_id", "partner_ids", "location"],
            limit=limit,
            order="start desc",
        )

    return safe(run)


# --- Activities ---------------------------------------------------------------


@mcp.tool()
def list_activities(user: str | None = None, overdue_only: bool = False, limit: int = 20) -> str:
    """List scheduled activities / to-dos (mail.activity).

    Args:
        user: Filter by the assigned user's name.
        overdue_only: If true, only activities whose deadline has passed.
        limit: Max results.
    """
    domain: list = []
    if user:
        domain.append(("user_id.name", "ilike", user))
    if overdue_only:
        domain.append(("date_deadline", "<", "today"))
    return safe(
        lambda: get_client().search_read(
            "mail.activity",
            domain=domain,
            fields=["summary", "activity_type_id", "user_id", "date_deadline", "res_model", "res_name"],
            limit=limit,
            order="date_deadline",
        )
    )


# --- Marketing ----------------------------------------------------------------


@mcp.tool()
def list_surveys(query: str | None = None, limit: int = 20) -> str:
    """List surveys (survey.survey) with response counts."""
    domain = name_domain(query, ["title"])
    return safe(
        lambda: get_client().search_read(
            "survey.survey",
            domain=domain,
            fields=["title", "answer_count", "success_count", "state"],
            limit=limit,
            order="title",
        )
    )


@mcp.tool()
def list_email_campaigns(query: str | None = None, limit: int = 20) -> str:
    """List email marketing mailings (mailing.mailing) with engagement stats."""
    domain = name_domain(query, ["subject"])
    return safe(
        lambda: get_client().search_read(
            "mailing.mailing",
            domain=domain,
            fields=["subject", "state", "sent", "delivered", "opened", "clicked"],
            limit=limit,
            order="create_date desc",
        )
    )
