"""A read-time delivery ledger: every completed request, including backend subtasks.

Legacy completions remain visible without inventing features or testing steps.
Reopening a request immediately removes it from the completed ledger.
"""
from pydantic import BaseModel, Field


class Delivery(BaseModel):
    added: list[str] = Field(default_factory=list)
    test_steps: list[str] = Field(default_factory=list)
    mods: list[str] = Field(default_factory=list)
    accomplished: list[str] = Field(default_factory=list)
    where: list[str] = Field(default_factory=list)
    verification: str = ""


def features(requests, mods):
    by_request = {}
    for mod in mods:
        for number in mod.get("requests", []):
            by_request.setdefault(number, []).append({k: mod.get(k) for k in
                ("id", "title", "game_title", "game_id", "verified", "state_slot")})
    rows = []
    for request in requests:
        if request.get("status") != "done":
            continue
        delivery = request.get("delivery") or {}
        notes = [m.get("text", "") for m in request.get("messages", [])
                 if m.get("author") == "agent" and m.get("text")]
        rows.append({"id": request["id"], "number": request.get("number"),
                     "title": request.get("title", ""), "completed": request.get("completed"),
                     "parent_request_id": request.get("parent_request_id"),
                     "automated": bool(request.get("automated")),
                     "delivery": delivery, "documented": any(delivery.get(key) for key in Delivery.model_fields),
                     "completion_note": notes[-1] if notes else "No completion summary was recorded.",
                     "files_changed": request.get("metrics", {}).get("files_changed", []),
                     "linked_mods": by_request.get(request.get("number"), [])})
    return sorted(rows, key=lambda r: (r.get("completed") or 0, r.get("number") or 0), reverse=True)
