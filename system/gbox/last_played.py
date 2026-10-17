"""Last played: offer to bring back the game the operator was playing after it ended (2026-10-13 operator request:
"When I close the emulator or rebuild the emulator or exit and relaunch it ... offer a pop-up to reload the same game
that I had up previously. And also offer an option to reload the same state that I had previously.").

The entry is derived from the persisted session records (the store survives restarts), so every way a game ends is
covered without a hook on each path: the newest operator session (agent test / capture sessions don't count) that has
ended - closed window, Stop, a crash, the worker / app restarting, a relaunch that failed - and was not continued by a
replacement (a swap or reset relaunch sets replaced_by to the running copy). Its moment is the state saved just before
the end where gBox could (Stop / reset relaunch / swap / app quit record it as the session's `checkpoint`), else the
newest state artifact uploaded for that session. Dismissals and "don't ask again for this game" are store documents.
Clients: clients/web/viz/last-played.js (the web shell, which the desktop app embeds).
"""
from __future__ import annotations

import json

DISMISS_KIND = "last_played_dismissed"          # session id -> {ts}
MUTE_KIND = "last_played_mute"                  # game id -> {ts}: don't ask again for this game
STATE_SUFFIXES = (".s01", ".s02", ".s03", ".s08", ".s09", ".state", ".sav", ".p2s")
AGENT_ACTORS = ("agent", "mcp", "gbox-agent", "hermes")


def _rows(store, kind: str, fields: tuple[str, ...]) -> list[dict]:
    try:
        cols = ", ".join(f"json_extract(body,'$.{f}')" for f in fields)
        with store.lock:
            rows = store.db.execute(f"SELECT {cols} FROM docs WHERE kind=? ORDER BY rowid", (kind,)).fetchall()
        out = []
        for r in rows:
            d = dict(zip(fields, r))
            for k, v in d.items():                 # nested JSON comes back as text
                if isinstance(v, str) and v[:1] in "{[":
                    try:
                        d[k] = json.loads(v)
                    except ValueError:
                        pass
            out.append(d)
        return out
    except Exception:                                            # noqa: BLE001 - another store: decode them all
        return [{f: d.get(f) for f in fields} for d in store.all(kind)]


def is_agent_session(store, s: dict) -> bool:
    """Agents' test sessions and Examine 3D capture sessions are not the operator's game."""
    if (s.get("detail") or {}).get("capture_session"):
        return True
    label = store.get("slabel", s.get("session_id") or "") or {}
    if label.get("owner") == "agent":
        return True
    job = store.get("job", (s.get("session_id") or "").split("-", 1)[-1]) or {}
    return bool(job.get("agent_use")) or job.get("actor") in AGENT_ACTORS


def end_reason(s: dict, worker_online: bool = True) -> dict:
    """How the game ended: {kind, text, crash}."""
    ex = s.get("exit")
    if s.get("state") == "running":
        return {"kind": "offline", "crash": False,
                "text": "The PC running it stopped answering (gBox closed, restarted or updating)."}
    if ex == "worker restarted":
        return {"kind": "worker_restarted", "crash": False, "text": "gBox on that PC restarted (closed, relaunched or updated)."}
    if isinstance(ex, str):
        return {"kind": "ended", "crash": False, "text": ex}
    ex = ex if isinstance(ex, dict) else {}
    via = ex.get("via")
    if via == "relaunch_failed":
        return {"kind": "relaunch_failed", "crash": True,
                "text": f"Its relaunch failed: {ex.get('error') or 'the new copy did not start'}."}
    if via in ("swap", "relaunch"):
        return {"kind": via, "crash": False, "text": "It was replaced by a new copy that has since ended."}
    if via == "single_game":
        return {"kind": "single_game", "crash": False, "text": "It closed when another game started on that PC."}
    if via == "cancel":
        return {"kind": "cancelled", "crash": False, "text": "Its launch was cancelled."}
    if "timings" in ex or via in ("stop", "operator"):
        return {"kind": "stopped", "crash": False, "text": "You stopped it."}
    rc = ex.get("returncode")
    from .session_exit import crash_code
    if crash_code(ex):
        return {"kind": "crash", "crash": True, "text": f"The emulator quit unexpectedly (exit code {rc})."}
    if rc not in (None, 0):
        return {"kind": "ended", "crash": False, "text": "The emulator closed."}
    return {"kind": "closed", "crash": False, "text": "The emulator window was closed."}


def _artifact_rows(store, sid: str) -> list[dict]:
    """Artifacts uploaded for one session (newest first): state files and pictures."""
    try:
        with store.lock:
            rows = store.db.execute(
                "SELECT body FROM docs WHERE kind='artifact' AND (json_extract(body,'$.provenance.session')=? "
                "OR json_extract(body,'$.provenance.session_id')=?) ORDER BY rowid DESC LIMIT 50", (sid, sid)).fetchall()
        return [json.loads(r[0]) for r in rows]
    except Exception:                                            # noqa: BLE001
        return []


def moment_of(store, s: dict) -> dict | None:
    """The saved moment to reload: the checkpoint recorded at the end, else the newest state uploaded for the session."""
    ex = s.get("exit") if isinstance(s.get("exit"), dict) else {}
    digest = s.get("checkpoint") or (ex.get("moment") or {}).get("artifact")
    arts = _artifact_rows(store, s.get("session_id") or "")
    if not digest:
        state = next((a for a in arts if str(a.get("name") or "").lower().endswith(STATE_SUFFIXES)
                      and not str(a.get("media_type") or "").startswith("image/")), None)
        digest = state and state.get("sha256")
    if not digest:
        return None
    art = store.get("artifact", digest) or {}
    frame = s.get("moment_frame") or (ex.get("moment") or {}).get("frame") or next(
        (a.get("sha256") for a in arts if str(a.get("media_type") or "").startswith("image/")
         and int(((a.get("provenance") or {}) if isinstance(a.get("provenance"), dict) else {}).get("covered") or 0) == 0), None)
    ts = s.get("moment_ts") or s.get("ended") or None
    return {"artifact": digest, "bytes": art.get("size"), "name": art.get("name"), "ts": ts,
            "frame": frame, "frame_url": f"/api/artifacts/{frame}" if frame else None}


def entry(store, workers: list[dict], resolve=lambda wid: wid) -> dict | None:
    """The pop-up's entry, or None (a game runs, it was continued, dismissed, muted, or nothing was played)."""
    online = {w["id"]: w for w in workers if w.get("online")}
    names = {w["id"]: w.get("name") for w in workers}
    sessions = _rows(store, "session", ("session_id", "game_id", "title", "mod", "collection_mod", "launch_mod", "state",
                                        "started", "ended", "exit", "replaced_by", "checkpoint", "moment_frame", "moment_ts",
                                        "adapter", "detail"))
    sessions = [s for s in sessions if s.get("session_id") and s.get("game_id")]
    by_id = {s["session_id"]: s for s in sessions}
    for s in sorted(sessions, key=lambda s: -(s.get("started") or 0)):
        if is_agent_session(store, s):
            continue
        wid = resolve(s["session_id"].split("-")[0])             # a restarted worker has a new id (worker_alias)
        if s.get("state") == "running" and wid in online:
            return None                                          # the operator is playing: never interrupt a game
        nxt, seen = s, set()
        while nxt and nxt.get("replaced_by") and nxt["session_id"] not in seen:   # continued in a replacement copy
            seen.add(nxt["session_id"]); nxt = by_id.get(nxt["replaced_by"])
        if nxt is not s and nxt and nxt.get("state") == "running":
            return None
        if store.get(DISMISS_KIND, s["session_id"]) or store.get(MUTE_KIND, s["game_id"]):
            return None
        detail = s.get("detail") if isinstance(s.get("detail"), dict) else {}
        mod = str(s.get("collection_mod") or s.get("mod") or "").split("~")[0]
        return {"session_id": s["session_id"], "game_id": s["game_id"], "title": s.get("title") or s["game_id"], "mod": mod,
                "node": detail.get("worker_name") or names.get(wid) or wid, "worker_id": wid, "node_online": wid in online,
                "started": s.get("started"), "ended": s.get("ended") or (s.get("started") if s.get("state") == "running" else None),
                "reason": end_reason(s, wid in online), "moment": moment_of(store, s), "report": report_for(store, s["session_id"])}
    return None


def report_for(store, sid: str) -> dict | None:
    """A request / failure report filed for this session (the launch-failure reports), if any: linked, never required."""
    try:
        with store.lock:
            row = store.db.execute(
                "SELECT body FROM docs WHERE kind='request' AND (json_extract(body,'$.context.session_id')=? "
                "OR json_extract(body,'$.session_id')=?) ORDER BY rowid DESC LIMIT 1", (sid, sid)).fetchone()
        if row:
            r = json.loads(row[0])
            return {"id": r.get("id"), "number": r.get("number"), "title": r.get("title"), "status": r.get("status")}
    except Exception:                                            # noqa: BLE001
        pass
    return None
