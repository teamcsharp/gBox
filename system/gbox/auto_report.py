"""Auto report context rules (gbox/server.py, POST /api/requests/auto-mod-failure).

A model replacement failure is filed by a client: the web/desktop app, or the automation that
watches a live session. The report only helps if it names something an agent can act on: the live
session, the failed job, the game, or the model/character/target that was replaced.

A report with none of those is unresolvable. Dispatching it to the durable Hermes queue spends a
whole agent run, and an inference slot, to rediscover that there is nothing to do. That is exactly
what happened to gBox request #2933: a context-free report (game "unknown game", empty model,
session, job, character and target) was queued, ran for 107 minutes, and exhausted the local
inference node with HTTP 429 before anyone noticed the report was empty.

`identified()` is the single rule both the server and the work queue use, so the report is never
queued for work it cannot define.
"""

# The report fields that name something an agent can act on.
IDENTIFYING_FIELDS = ("session_id", "job_id", "game", "model", "character", "target")

# Placeholder words a client or the server may send instead of a real value.
PLACEHOLDERS = {"", "?", "none", "null", "undefined", "unknown", "unknown game", "not identified"}


def meaningful(value) -> bool:
    """True for a real value, not for an empty string or a placeholder word."""
    text = str(value if value is not None else "").strip().lower()
    return bool(text) and text not in PLACEHOLDERS


def identified(report, session=None) -> bool:
    """True when the report names something an agent can act on.

    `report` is the request payload (the AutoFailureIn fields, or the request context that holds
    the same names), `session` the session record the server resolved for it. A resolved session
    counts: the session knows its game even when the client sent no title.
    """
    report = report or {}
    session = session or {}
    if any(meaningful(report.get(key)) for key in IDENTIFYING_FIELDS):
        return True
    return bool(meaningful(session.get("game_id")) or meaningful(session.get("title"))
                or meaningful(session.get("game_title")))


def unresolved_context_message() -> str:
    """The note left on a report that names nothing (kept for the record, never queued)."""
    return ("This report arrived without a session, a failed job, a game or a model, so no actor or "
            "native asset can be identified from it. It is filed for the record and is not queued: an "
            "agent run cannot resolve it. Re-file it from the client with the game, the selected actor "
            "and the failed job id.")
