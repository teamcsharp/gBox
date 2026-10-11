"""Keep operator prompts separate from the automated work they initiate."""
from bisect import bisect_right
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
            standing = re.search(r"operator['�?T]s request:\s*[\"�?o](.*?)[\"�??]", first_line)
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
