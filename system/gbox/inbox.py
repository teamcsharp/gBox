"""Keep operator prompts separate from the automated work they initiate."""
from bisect import bisect_right
import re


# A recurring review quotes its standing instruction with straight or curly
# quotes. Written as escapes so a non-UTF-8 copy of this file cannot corrupt
# the pattern (an earlier copy replaced the curly quotes with U+FFFD and '?').
_STANDING = re.compile("operator['\u2019]s request:\\s*[\"\u201c](.*?)[\"\u201d]")


def automated(request):
    text = (request.get("body") or request.get("title") or "").lstrip()
    return bool(request.get("automated") or request.get("parent_request_id")
                or request.get("source") in {"characters", "gap", "system", "automation", "agent", "review"}
                or request.get("author") in {"agent", "system"}
                or text.startswith(("<agent-message", "<task-notification", "gBox request review")))


def normalize(text):
    return " ".join((text or "").lower().split())


def parent_for(request, requests):
    by_id = {r["id"]: r for r in requests}
    context = request.get("context") or {}
    if context.get("auto_report"):
        return None  # failed-mod reports are first-class inbox jobs, visible without opening a parent thread
    explicit = request.get("parent_request_id") or context.get("parent_request_id") or context.get("request_id")
    if explicit:
        parent = by_id.get(str(explicit)) or next((r for r in requests if str(r.get("number")) == str(explicit)), None)
        return parent["id"] if parent and parent["id"] != request.get("id") else None
    if not automated(request):
        return None
    # Match the original prompt quoted in an automatic gap report. Never attach
    # an unknown task to an unrelated prompt simply because it was recent.
    body = request.get("body") or ""
    quoted = re.search(r"## What the operator asked\s*\n(.*?)(?:\n## |\Z)", body, re.S)
    prompt = normalize(quoted[1]) if quoted else ""
    roots = [r for r in requests if not automated(r) and r.get("created", 0) <= request.get("created", float("inf"))]
    if prompt:
        matches = [r for r in roots if normalize(r.get("body") or r.get("title")) == prompt]
        if matches:
            return max(matches, key=lambda r: r.get("created", 0))["id"]
    if body.lstrip().startswith("gBox request review"):
        # Recurring reviews reuse the originating conversation for months. Its
        # latest prompt can be unrelated (a thumbnail request, for example).
        # Only the exact standing instruction quoted by the review is evidence
        # of a parent; an absent original instruction leaves the review unlinked.
        first_line = body.lstrip().splitlines()[0]
        standing = _STANDING.search(first_line)
        if standing:
            instruction = normalize(standing[1])
            matches = [r for r in roots if instruction and normalize(r.get("body") or r.get("title")) == instruction]
            if matches:
                return max(matches, key=lambda r: r.get("created", 0))["id"]
        return None
    conversation_key = "conversation" if context.get("conversation") else "session"
    conversation = context.get(conversation_key)
    if conversation:
        matches = [r for r in roots if (r.get("context") or {}).get(conversation_key) == conversation]
        if matches:
            return max(matches, key=lambda r: r.get("created", 0))["id"]
    return None


class _ParentIndex:
    """Index one inbox snapshot without changing the parenting rules."""

    def __init__(self, requests):
        self.by_id = {r["id"]: r for r in requests}
        self.by_number = {}
        self.is_automated = [automated(r) for r in requests]
        self.prompts = {}
        self.contexts = {"conversation": {}, "session": {}}
        self.roots = []
        for position, (r, is_automated) in enumerate(zip(requests, self.is_automated)):
            # Imported ticket numbers can collide. The old linear fallback
            # selects the first record, whereas an exact ID always wins.
            self.by_number.setdefault(str(r.get("number")), r)
            if is_automated:
                continue
            self.roots.append(r)
            row = (r.get("created", 0), -position, r["id"])
            prompt = normalize(r.get("body") or r.get("title"))
            self.prompts.setdefault(prompt, []).append(row)
            context = r.get("context") or {}
            for key, groups in self.contexts.items():
                value = context.get(key)
                try:
                    hash(value)
                except TypeError:
                    continue  # uncommon structured contexts use equality below
                groups.setdefault(value, []).append(row)
        for groups in (self.prompts, *self.contexts.values()):
            for key, rows in groups.items():
                # At equal timestamps max() used the first input record. A
                # reversed position preserves that tie when selecting the last
                # eligible row with bisect_right().
                rows.sort(key=lambda row: row[:2])
                groups[key] = ([row[0] for row in rows], [row[2] for row in rows])

    @staticmethod
    def latest(group, created):
        if group:
            times, ids = group
            position = bisect_right(times, created) - 1
            if position >= 0:
                return ids[position]
        return None

    def context_parent(self, key, value, created):
        try:
            hash(value)
        except TypeError:
            # JSON context normally contains IDs. Preserve the existing equality
            # semantics for imported lists/dicts rather than stringifying them.
            matches = [r for r in self.roots if r.get("created", 0) <= created
                       and (r.get("context") or {}).get(key) == value]
            return max(matches, key=lambda r: r.get("created", 0))["id"] if matches else None
        return self.latest(self.contexts[key].get(value), created)

    def parent_for(self, request, is_automated):
        context = request.get("context") or {}
        if context.get("auto_report"):
            return None
        explicit = request.get("parent_request_id") or context.get("parent_request_id") or context.get("request_id")
        if explicit:
            parent = self.by_id.get(str(explicit)) or self.by_number.get(str(explicit))
            return parent["id"] if parent and parent["id"] != request.get("id") else None
        if not is_automated:
            return None
        body = request.get("body") or ""
        created = request.get("created", float("inf"))
        quoted = re.search(r"## What the operator asked\s*\n(.*?)(?:\n## |\Z)", body, re.S)
        prompt = normalize(quoted[1]) if quoted else ""
        if prompt:
            parent = self.latest(self.prompts.get(prompt), created)
            if parent is not None:
                return parent
        if body.lstrip().startswith("gBox request review"):
            first_line = body.lstrip().splitlines()[0]
            standing = _STANDING.search(first_line)
            instruction = normalize(standing[1]) if standing else ""
            return self.latest(self.prompts.get(instruction), created) if instruction else None
        key = "conversation" if context.get("conversation") else "session"
        conversation = context.get(key)
        return self.context_parent(key, conversation, created) if conversation else None


def organize(requests):
    index = _ParentIndex(requests)
    out = [r | {"automated": is_automated, "parent_request_id": index.parent_for(r, is_automated)}
           for r, is_automated in zip(requests, index.is_automated)]
    by_id = {r["id"]: r for r in out}
    for r in out:
        seen = {r["id"]}
        parent = r.get("parent_request_id")
        while parent:
            if parent in seen:
                r["parent_request_id"] = None
                break
            seen.add(parent)
            parent = by_id.get(parent, {}).get("parent_request_id")
    return out


# --- #1788: one inbox entry per kind of automated ticket -------------------------------------------------------------
# Presentation only (nothing is closed or deleted). clients/desktop/inbox-groups.js applies the same rules in the app.
GROUP_LABELS = {
    "launch_failure": "Launch failures",
    "readiness": "Character replacement readiness",
    "observer": "Session observer and gap reports",
    "agent_message": "Agent messages",
    "review": "Scheduled request reviews",
    "automation": "Other automated reports",
}
_OPERATOR_SOURCES = {"chat", "app", "gbox-chat"}


# --- #2801: standing per-game background work is not an inbox message ------------------------------------------------
STANDING_LABELS = {
    "readiness": "Character replacement readiness",
    "unlock_on_load": "Unlock on load",
    "unlock_everything": "Unlock everything",
    "extraction": "Extraction engineering",
    "policy": "Standing policies and supervision",
}


def standing_key(request):
    """The Background work kind of a standing per-game task the Hermes queue keeps open, or None for an inbox entry.
    clients/desktop/inbox-groups.js standingKey() keeps the same rules."""
    context = request.get("context") or {}
    if context.get("hermes_favorite_game"):
        return "readiness"
    if context.get("unlock_on_load") or context.get("unlock_inventory"):
        return "unlock_on_load"
    if context.get("custom_build_unlocks"):
        return "unlock_everything"
    if context.get("extraction_engineering"):
        return "extraction"
    if context.get("unlock_research_parent") or context.get("standing_policy") or context.get("nous_build_supervision"):
        return "policy"
    return None


def group_key(request):
    """The automated group a request collapses into, or None for operator-written requests and build reports."""
    title = request.get("title") or ""
    body = (request.get("body") or title).lstrip()
    context = request.get("context") or {}
    low = title.lower()
    if low.startswith("build report"):
        return None
    if context.get("launch_failure") or low.startswith("launch failed:"):
        return "launch_failure"
    if low.startswith("character replacement readiness"):
        return "readiness"
    if body.startswith(("<agent-message", "<task-notification")):
        return "agent_message"
    if body.startswith("gBox request review"):
        return "review"
    if request.get("source") == "gap" or re.match(r"session (observation|models)\b", low):
        return "observer"
    if (request.get("source") in _OPERATOR_SOURCES and (request.get("author") or "operator") == "operator"
            and not request.get("automated")):
        return None
    if request.get("source") == "automation" or request.get("automated"):
        return "automation"
    return None


def grouped(requests, minimum=2):
    """requests (newest first) as entries in the same order: each request unchanged, except that every kind of automated
    ticket with at least `minimum` members becomes one group entry at the place of its newest member:
    {"group": key, "label", "count", "pending", "newest", "latest": {id, number, title, status, created}, "ids": [...]}."""
    keys = [group_key(r) for r in requests]
    counts = {}
    for k in keys:
        if k:
            counts[k] = counts.get(k, 0) + 1
    out, groups = [], {}
    for r, k in zip(requests, keys):
        if not k or counts[k] < minimum:
            out.append(r)
            continue
        if k not in groups:
            groups[k] = {"group": k, "label": GROUP_LABELS[k], "members": []}
            out.append(groups[k])
        groups[k]["members"].append(r)
    for g in groups.values():
        members = g.pop("members")
        latest = max(members, key=lambda r: r.get("created") or 0)
        g.update(count=len(members), pending=sum(r.get("status") != "done" for r in members),
                 newest=latest.get("created") or 0, ids=[r["id"] for r in members],
                 latest={k: latest.get(k) for k in ("id", "number", "title", "status", "created")})
    return out


# --- the Hermes queue's view of the inbox: GET /api/requests?lite=1 ---------------------------------------------------
# 2026-10-27: the queue pump (gbox/hermes_work_queue.py) fetched the whole history every tick, 46 MB built in ~4 s inside
# the server that also relays the live game streams, which stalled for 2 s right after each tick started. The message
# threads were 27.6 MB of it and the metrics 2.4 MB; the queue reads neither.
LITE_DROPPED = ("messages", "metrics")
LITE_OPEN_BODY = 2500    # characters an open or in-progress request keeps: hermes_local.dispatch_size reads a body this
                         # long whole (a longer one is a "long ticket" by body_chars alone) - keep it >= its LONG_TICKET
LITE_CLOSED_BODY = 300   # a done or blocked request: the queue reads only its opening words (the review, agent-message
                         # and task-notification markers)


def lite(request):
    """`request` without its message thread and metrics, and with a body longer than its status's limit (counted after
    any leading whitespace) cut to that prefix; a cut row says body_chars, the whole body's length. Apply it after
    organize(), which matches parents on whole bodies."""
    out = {k: v for k, v in request.items() if k not in LITE_DROPPED}
    body = request.get("body")
    if isinstance(body, str):
        keep = len(body) - len(body.lstrip()) + (
            LITE_OPEN_BODY if request.get("status") in ("open", "in_progress") else LITE_CLOSED_BODY)
        if len(body) > keep:
            out.update(body=body[:keep], body_chars=len(body))
    return out


# --------------------------------------------------------------------------- stale work

# A request that an agent claimed and never finished holds the queue the way a duplicate would, except that nothing
# supersedes it: `round_reports.ANALYSIS_QUEUE_CAP` bounds how many analyses a title may leave open, but a ticket a
# worker picked up and abandoned stays `in_progress` for ever. Measured 2026-11-07: 1,694 of 8,894 requests were
# `in_progress`, against 1,109 open. This decides which of those have gone quiet long enough to be handed back.
STALE_AFTER_S = 6 * 3600


def activity(request) -> float:
    """The last moment anything happened on a request: its creation, its claim, or its newest message (or step)."""
    times = [request.get("created") or 0, request.get("started") or 0, request.get("completed") or 0]
    for message in request.get("messages") or ():
        if isinstance(message, dict):
            times.append(message.get("ts") or 0)
            step = message.get("task_step")
            if isinstance(step, dict):
                times.append(step.get("at") or 0)
    return max(times) if times else 0.0


def stale_in_progress(requests, *, now: float, after_s: float = STALE_AFTER_S, limit: int = 0) -> list[dict]:
    """Requests in `in_progress` with no activity for `after_s`, newest-quiet first.

    Only `in_progress` is touched. `open` work is waiting on purpose, `done`/`blocked` are settled, and a request with
    no timestamp at all is left alone rather than aged out on a guess.
    """
    rows = [r for r in requests
            if isinstance(r, dict) and r.get("status") == "in_progress" and activity(r) > 0
            and now - activity(r) >= after_s]
    rows.sort(key=activity)
    return rows[:limit] if limit else rows


def hand_back(request, *, now: float, after_s: float = STALE_AFTER_S) -> dict:
    """The request returned to `open` with a note saying why, so the queue shows work that is actually waiting."""
    quiet = (now - activity(request)) / 3600.0
    out = dict(request)
    # a shallow copy would hand the caller's own messages list back to them and the note would land in it too
    out["messages"] = list(request.get("messages") or ())
    out["status"] = "open"
    out["started"] = None
    out["handed_back_at"] = now
    out["messages"].append({
        "author": "system", "ts": now, "attachments": [],
        "text": (f"Returned to the queue: this was claimed and had no activity for {quiet:.1f} h (the limit is "
                 f"{after_s / 3600:.0f} h). Nothing was lost - the messages and attachments above are the work done "
                 f"so far."),
    })
    return out