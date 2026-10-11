"""Keep operator prompts separate from the automated work they initiate."""
import re


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
        standing = re.search(r"operator['’]s request:\s*[\"“](.*?)[\"”]", first_line)
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


def organize(requests):
    out = [r | {"automated": automated(r), "parent_request_id": parent_for(r, requests)} for r in requests]
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
