"""Autoplay coaching (operator 2026-10-20): notes the operator types while watching autoplay play a game, kept with the
moment they were given in.

"During cloud sessions put a text box here where I can type ... and tell it things like 'Stop walking into walls',
'that's not an enemy', 'go after the enemy', 'aim at the enemy' ... batch that under a group ticket for this particular
game ... every message that I send should have you capturing a save state, the byte and hex data of the game ... and an
image." The box sits in the Sessions header (clients/web/viz/autoplay-coach.js); each note it sends becomes:

  * an operator message on the game's coaching ticket: one open inbox request per game (source "coach",
    context.coaching, titled "Autoplay coaching: <title>", created by the first note), with the session, the PC, the
    autoplay telemetry at that moment (gbox.screensaver.telemetry_get) and the time under the operator's words;
  * that moment captured on the PC running the game, each a job on the session's worker, attached to the message when
    it finishes: a frame (get_frame), a save state through gBox's own slot (state_transfer op=snapshot: the operator's
    save slots are never written; Dolphin and RetroArch only) and the main RAM (ram_dump: one gzip artifact with a JSON
    header: platform, base address, length, sha256). For Resident Evil 4 GameCube (G4BE08) a summary decoded from
    that RAM with gbox.re4_merc_bot.snapshot (room, Mercenaries clock, combo, Leon's position and facing, the live
    Ganados with distance and bearing) is attached as JSON and added to the message, so a note reads without tools;
  * an entry in a small store (kind "coaching", id = game id, the last NOTES_KEPT notes with their capture ids) that
    autoplay can read: GET /api/coaching/{game_id}. The watch panel shows the newest. The bot does not act on the words
    by itself; mapping notes to behaviour is a later change.

The note answers at once; a watcher thread attaches each capture when its job ends, and reading a note's status does
the same (idempotent), so a capture that finishes after a server restart is still attached.

  POST /api/sessions/{sid}/coach {text}       -> {request_id, number, message_id, note, jobs: {frame, state, ram}, captures}
  GET  /api/sessions/{sid}/coach/{message_id} -> that note's captures (pending / done / failed / skipped) and summary
  GET  /api/sessions/{sid}/coach              -> the newest note for the session's game (the watch panel)
  GET  /api/coaching/{game_id}                -> the game's ticket and its last notes, newest last, with capture ids
"""
from __future__ import annotations

import json
import math
import threading
import time

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .models import new_id

KIND = "coaching"
NOTES_KEPT = 50
CAPTURES = ("frame", "state", "ram")
STATE_ADAPTERS = {"dolphin", "retroarch"}       # a save slot of gBox's own (gbox/state_snapshot.py)
RAM_BUDGET_S = 20.0                             # ram_dump stops after this (Dolphin: ms; RetroArch: ~1 MiB/s)
WATCH_S = 300.0
POLL_S = 1.0
SETTLE_S = 86400.0                              # reads still attach a late capture for a day
WORKER_TTL = 30.0                               # server.WORKER_TTL: a worker silent this long is offline
OPEN = ("open", "in_progress", "blocked")
RE4 = "G4BE08"
TICKET_BODY = (
    "Autoplay coaching notes for {title} (game_id {game_id}): what the operator tells autoplay while watching it play.\n\n"
    "Each operator message below is one note in the operator's own words, with the session, the PC, the autoplay "
    "telemetry and the time under it, and the moment it was given captured on the PC running the game:\n"
    "- coach-N-frame.png: the game picture;\n"
    "- coach-N-<file>: a save state taken through gBox's own slot (Dolphin slot 10 / RetroArch slot 9; the operator's "
    "save slots are never written): load it from file in the same emulator build;\n"
    "- coach-N-<game>-ram.gz: the main RAM. gunzip it: one JSON header line (platform, base address, length, sha256, "
    "regions with their file offsets) padded to header_size bytes, then the RAM. Ghidra: Raw Binary, base address = "
    "the region's base_hex, file offset = its offset;\n"
    "- Resident Evil 4 GameCube only: coach-N-re4-summary.json (room, Mercenaries clock, combo, Leon, live Ganados), "
    "also written under the note.\n\n"
    "Use the notes to change how autoplay plays this game (RE4 Mercenaries: gbox/re4_merc_bot.py) and to point Ghidra "
    "at the moment they describe. The last {kept} notes are also at GET /api/coaching/{game_id}.")

_ticket_lock = threading.Lock()                 # one ticket per game, even for notes sent at the same time
_busy: set[tuple[str, str]] = set()             # (message id, capture) being attached right now
_busy_lock = threading.Lock()


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _spawn(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True, name=f"coach-{str(args[-1])[:8]}").start()


# --- the ticket ---------------------------------------------------------------------------------------------------------
def ticket_for(store, game_id: str) -> str | None:
    """The game's coaching ticket that is still open (newest), or None."""
    for row in store.game_requests(game_id, statuses=OPEN, limit=200):         # newest first
        if (row.get("context") or {}).get("coaching") is True:
            return row["id"]
    return None


def _worker(store, wid: str) -> dict:
    for _ in range(20):                         # a restarted worker has a new id (server._wid)
        alias = store.get("worker_alias", wid)
        if not alias:
            break
        wid = alias["to"]
    return store.get("worker", wid) or {}


def telemetry_line(tel: dict) -> str:
    """'autoplay playing (playbook): playbook: re4_merc_bot · combo 12 · rounds 2' from a telemetry snapshot."""
    if not tel:
        return "no autoplay telemetry"
    out = "autoplay " + ("playing" if tel.get("running") else "stopped") + (f" ({tel['mode']})" if tel.get("mode") else "")
    if tel.get("mission"):
        out += f": {tel['mission']}"
    stats = [f"{k.replace('_', ' ')} {v}" for k, v in (tel.get("stats") or {}).items()
             if isinstance(v, (int, float, str)) and not isinstance(v, bool)][:8]
    return " · ".join([out, *stats])[:400]


def compose(text: str, n: int, when: float, worker: str, sid: str, tel: dict) -> str:
    """The message: the operator's words, then one bracketed line of where and when."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when))
    return f"{text}\n\n[coach note #{n} · {stamp} · {worker} · session {sid} · {telemetry_line(tel)}]"


def plan(store, session: dict) -> dict:
    """capture -> {tool, input} to run, or {state: skipped, detail} when it can't be taken."""
    sid = session["session_id"]
    if session.get("state") != "running":
        return {k: {"state": "skipped", "detail": "the game has ended: nothing to capture"} for k in CAPTURES}
    w = _worker(store, sid.split("-")[0])
    if not w or time.time() - float(w.get("last_seen") or 0) >= WORKER_TTL:
        why = f"the PC running the game ({w.get('name') or sid.split('-')[0]}) is offline: nothing captured"
        return {k: {"state": "skipped", "detail": why} for k in CAPTURES}
    adapter = str(session.get("adapter") or "").lower()
    state = ({"tool": "state_transfer", "input": {"session_id": sid, "op": "snapshot"}} if adapter in STATE_ADAPTERS
             else {"state": "skipped", "detail": f"{adapter or 'this emulator'} has no save slot of gBox's own "
                                                 "(only Dolphin and RetroArch): no save state, your slots stay yours"})
    return {"frame": {"tool": "get_frame", "input": {"session_id": sid}}, "state": state,
            "ram": {"tool": "ram_dump", "input": {"session_id": sid, "budget_s": RAM_BUDGET_S}}}


# --- the store autoplay reads ---------------------------------------------------------------------------------------------
def _remember(store, game_id: str, title: str, request: dict, entry: dict) -> None:
    with store.lock:
        doc = store.get(KIND, game_id) or {"game_id": game_id, "notes": []}
        notes = [x for x in doc.get("notes") or [] if x.get("id") != entry["id"]] + [entry]
        store.put(KIND, game_id, doc | {"title": title, "request_id": request["id"], "number": request.get("number"),
                                        "updated": time.time(), "notes": notes[-NOTES_KEPT:]})


def _update_entry(store, game_id: str, mid: str, change: dict) -> None:
    with store.lock:
        doc = store.get(KIND, game_id)
        if not doc:
            return
        for x in doc.get("notes") or []:
            if x.get("id") == mid:
                for k, v in change.items():
                    x[k] = x.get(k, {}) | v if isinstance(v, dict) and isinstance(x.get(k), dict) else v
        store.put(KIND, game_id, doc | {"updated": time.time()})


def _brief(cap: dict) -> dict:
    return {k: cap[k] for k in ("state", "job", "sha256", "name", "size", "detail", "timed_out") if cap.get(k) is not None}


def _lesson(game: dict, kind: str, text: str, **kw) -> bool:
    """A note on a Mercenaries title (its RAM map has a "mercs" block) also goes to the title's run-lessons log, which
    the engine reads before its next round (gbox.mercs_bot.note_lesson). Other titles: nothing. Never raises."""
    try:
        from . import mercs_bot
        return mercs_bot.note_lesson(game, mercs_bot.lesson(kind, text, **kw))
    except Exception:                                # noqa: BLE001 - the note is filed either way
        return False


# --- a note -------------------------------------------------------------------------------------------------------------
def add_note(store, create_request, submit, sid: str, text: str, actor: str = "operator",
             now: float | None = None) -> dict:
    session = store.get("session", sid)
    if not session:
        raise HTTPException(404, "Session not found")
    gid = session.get("game_id")
    if not gid:
        raise HTTPException(409, "This session has no game to coach")
    game = store.catalog_get(gid) or {}
    title = game.get("title") or session.get("title") or gid
    wid = sid.split("-")[0]
    worker = (session.get("detail") or {}).get("worker_name") or _worker(store, wid).get("name") or wid
    from .screensaver import telemetry_get
    tel = telemetry_get(sid)
    now = time.time() if now is None else now
    with _ticket_lock:
        rid = ticket_for(store, gid)
        if rid is None:
            rid = create_request({"title": f"Autoplay coaching: {title}"[:140], "source": "coach", "kind": "text",
                                  "author": "operator", "context": {"coaching": True, "game_id": gid, "title": title},
                                  "body": TICKET_BODY.format(title=title, game_id=gid, kept=NOTES_KEPT)}, actor)["id"]
    captures, jobs = plan(store, session), {}
    for kind in CAPTURES:
        step = captures[kind]
        if "tool" not in step:
            continue
        try:
            job = submit(step["tool"], step["input"], rid, actor)
        except Exception as e:                       # noqa: BLE001 - an unknown tool / refused PC: the note still goes in
            captures[kind] = {"state": "failed", "tool": step["tool"],
                              "detail": f"not started: {getattr(e, 'detail', None) or e}"[:300]}
            continue
        jobs[kind] = job.get("id")
        captures[kind] = {"state": "pending", "tool": step["tool"], "job": job.get("id")}
        if job.get("state") not in ("queued", "running"):            # refused at once (that PC lacks the tool...)
            captures[kind] |= {"state": "failed", "detail": str(job.get("error") or job.get("state"))[:300]}
    mid = new_id()
    with store.lock:
        req = store.get("request", rid)
        if not req:
            raise HTTPException(409, "The coaching ticket disappeared while the note was filed: send it again")
        n = 1 + sum(1 for m in req.get("messages") or [] if m.get("coach"))
        req.setdefault("messages", []).append({
            "id": mid, "author": "operator", "text": compose(text, n, now, worker, sid, tel), "ts": now, "attachments": [],
            "coach": {"note": n, "text": text, "session_id": sid, "worker": worker, "worker_id": wid, "game_id": gid,
                      "telemetry": tel or None, "captures": captures}})
        if req.get("status") in ("done", "blocked"):  # the operator wrote again (req_message reopens the same way)
            req["status"], req["completed"] = "open", None
        store.put("request", rid, req)
        _remember(store, gid, title, req, {"id": mid, "note": n, "text": text, "ts": now, "session_id": sid,
                                            "worker": worker, "request_id": rid, "number": req.get("number"),
                                            "telemetry": {k: tel.get(k) for k in ("running", "mode", "mission")} if tel else None,
                                            "captures": {k: _brief(v) for k, v in captures.items()}, "summary": None})
    store.audit(actor, "request.coach_note", rid, {"session": sid, "note": n, "jobs": jobs})
    _lesson(dict(game, game_id=gid), "coach", text, session_id=sid, worker=worker, telemetry=tel or None,
            captures={k: _brief(v) for k, v in captures.items()}, request_id=rid, note=n, ts=now)
    return {"request_id": rid, "number": req.get("number"), "message_id": mid, "note": n, "game_id": gid,
            "jobs": {k: jobs.get(k) for k in CAPTURES}, "captures": captures}


def _message(req: dict | None, mid: str) -> dict | None:
    return next((m for m in (req or {}).get("messages") or [] if m.get("id") == mid and m.get("coach")), None)


def status(store, rid: str, mid: str) -> dict | None:
    req = store.get("request", rid)
    msg = _message(req, mid)
    if msg is None:
        return None
    coach = msg["coach"]
    caps = coach.get("captures") or {}
    return {"request_id": rid, "number": req.get("number"), "message_id": mid, "note": coach.get("note"),
            "game_id": coach.get("game_id"), "captures": caps, "summary": coach.get("summary"),
            "done": not any(c.get("state") == "pending" for c in caps.values())}


def _mib(n) -> str:
    return f"{(n or 0) / 2**20:.1f} MiB"


def _failed(base: dict, why: str) -> dict:
    return {"capture": base | {"state": "failed", "detail": why[:300]}}


def _finish(store, kind: str, job: dict, n: int, rid: str) -> dict:
    """What a finished capture job adds to its note: {capture, attachments, summary}."""
    base = {"tool": job.get("tool"), "job": job.get("id")}
    if job.get("state") != "succeeded":
        return _failed(base, str(job.get("error") or job.get("state") or "failed"))
    out = job.get("output") or {}
    res = out.get("result") if isinstance(out.get("result"), dict) else {}
    digest = out.get("sha256") if kind == "frame" else res.get("artifact")
    meta = store.get("artifact", digest or "")
    if not meta:
        return _failed(base, f"the {kind} job finished without uploading its file")
    if kind == "frame":
        name, kind_type = f"coach-{n}-frame.png", meta.get("media_type") or "image/png"
        luma, covered = out.get("mean_luma"), out.get("covered") or 0
        detail = (f"{out.get('width')}x{out.get('height')}" + (", black screen" if luma is not None and luma < 6 else "")
                  + (f", {covered}/9 points covered by another window" if covered else ""))
    elif kind == "state":
        name, kind_type = f"coach-{n}-{res.get('file') or 'state'}", "application/octet-stream"
        detail = f"{res.get('file')} ({_mib(res.get('bytes'))}) · {res.get('via') or 'slot ' + str(res.get('slot'))}"
        if res.get("warning"):
            detail += f" · {res['warning']}"
    else:
        label = res.get("disc_id") or res.get("platform") or "game"
        name, kind_type = f"coach-{n}-{label}-ram.gz", "application/gzip"
        detail = f"{_mib(res.get('length'))} at {res.get('base_hex')} · {res.get('source')}"
        if res.get("partial"):
            detail += f" · partial: {len(res.get('missing') or [])} range(s) not read"
    att = {"sha256": meta["sha256"], "name": name, "type": kind_type, "size": meta.get("size")}
    update = {"capture": base | {"state": "done", "sha256": meta["sha256"], "name": name, "size": meta.get("size"),
                                 "detail": detail}, "attachments": [att], "summary": None}
    if kind == "ram" and res.get("disc_id") == RE4:
        try:
            summary = re4_summary(store.read_artifact(meta["sha256"]) or b"")
        except Exception as e:                       # noqa: BLE001 - the dump stays attached either way
            summary, update["capture"]["detail"] = None, detail + f" · RE4 summary unavailable: {e}"[:200]
        if summary:
            ref = store.put_artifact(json.dumps(summary, indent=2).encode(), f"coach-{n}-re4-summary.json",
                                     "application/json", {"request": rid, "coach_note": n, "ram": meta["sha256"]})
            update["attachments"].append({"sha256": ref.sha256, "name": ref.name, "type": "application/json",
                                          "size": ref.size})
            update["summary"] = summary_text(summary)
    return update


def _apply(store, rid: str, mid: str, kind: str, update: dict) -> None:
    with store.lock:
        req = store.get("request", rid)
        msg = _message(req, mid)
        if msg is None or (msg["coach"]["captures"].get(kind) or {}).get("state") == "done":
            return                                   # attached already (the watcher and a status read raced)
        msg["attachments"] = (msg.get("attachments") or []) + update.get("attachments", [])
        msg["coach"]["captures"][kind] = update["capture"]
        if update.get("summary"):
            msg["coach"]["summary"] = update["summary"]
            msg["text"] = msg["text"] + "\n" + update["summary"]
        store.put("request", rid, req)
        change = {"captures": {kind: _brief(update["capture"])}}
        if update.get("summary"):
            change["summary"] = update["summary"]
        _update_entry(store, msg["coach"].get("game_id") or "", mid, change)


def reconcile(store, rid: str, mid: str) -> dict | None:
    """Attach every capture of one note whose job has ended (idempotent); the note's status, or None."""
    req = store.get("request", rid)
    msg = _message(req, mid)
    if msg is None:
        return None
    for kind, cap in (msg["coach"].get("captures") or {}).items():
        if not cap.get("job") or not (cap.get("state") == "pending" or cap.get("timed_out")):
            continue
        job = store.get("job", cap["job"]) or {}
        if job.get("state") in ("queued", "running"):
            continue
        with _busy_lock:
            if (mid, kind) in _busy:
                continue
            _busy.add((mid, kind))
        try:
            _apply(store, rid, mid, kind, _finish(store, kind, job, msg["coach"].get("note") or 0, rid))
        finally:
            with _busy_lock:
                _busy.discard((mid, kind))
    return status(store, rid, mid)


def _time_out(store, rid: str, mid: str) -> None:
    with store.lock:
        req = store.get("request", rid)
        msg = _message(req, mid)
        if msg is None:
            return
        for kind, cap in msg["coach"]["captures"].items():
            if cap.get("state") == "pending":
                job = store.get("job", cap.get("job") or "") or {}
                cap |= {"state": "failed", "timed_out": True,
                        "detail": f"no result after {WATCH_S / 60:g} min (job {job.get('state') or 'missing'})"}
        store.put("request", rid, req)
        _update_entry(store, msg["coach"].get("game_id") or "", mid,
                      {"captures": {k: _brief(v) for k, v in msg["coach"]["captures"].items()}})


def watch(store, rid: str, mid: str, *, limit_s: float = WATCH_S, poll_s: float = POLL_S, clock=time.monotonic,
          sleep=time.sleep) -> dict | None:
    """Attach the note's captures as their jobs end; give up on the rest after limit_s (a late one still attaches)."""
    end = clock() + limit_s
    while True:
        st = reconcile(store, rid, mid)
        if st is None or st["done"]:
            return st
        if clock() > end:
            _time_out(store, rid, mid)
            return status(store, rid, mid)
        sleep(poll_s)


# --- Resident Evil 4 (GameCube) ----------------------------------------------------------------------------------------
class _Ram:
    """re4_merc_bot's memory interface over a dumped MEM1."""

    def __init__(self, base: int, data: bytes):
        self.base, self.data = base, data

    def rd(self, addr: int, n: int) -> bytes:
        off = addr - self.base
        if off < 0 or off + n > len(self.data):
            raise ValueError(f"{addr:#x} is outside the dumped RAM")
        return self.data[off:off + n]


def re4_summary(blob: bytes) -> dict | None:
    """Mercenaries at the moment of a note, decoded from its RAM dump (gbox.re4_merc_bot.snapshot); None if not RE4."""
    from . import ram_dump, re4_merc_bot as R
    _meta, regions = ram_dump.load(blob)
    mem1 = next((data for r, data in regions if r.get("base") == 0x80000000), None)
    if not mem1 or mem1[:6] != RE4.encode():
        return None
    s = R.snapshot(_Ram(0x80000000, mem1))
    p = s["player"]
    leon = ganados = None
    if p:
        px, _, pz = p["pos"]
        leon = {"ptr": f"{p['ptr']:#010x}", "pos": [round(v, 1) for v in p["pos"]],
                "facing_deg": round(math.degrees(p["rot"]) % 360, 1)}
    rows = []
    for e in s["enemies"]:
        row = {"slot": e["slot"], "pos": [round(v, 1) for v in e["pos"]]}
        if p:
            dx, dz = e["pos"][0] - px, e["pos"][2] - pz
            row |= {"distance": round(math.hypot(dx, dz)),
                    "bearing_deg": round(math.degrees(R.wrap(R.heading(dx, dz) - p["rot"])), 1)}   # + = to his left
        rows.append(row)
    ganados = sorted(rows, key=lambda r: r.get("distance", math.inf))
    return {"game": "Resident Evil 4 (GameCube, G4BE08)", "decoded_from": "the note's RAM dump (MEM1 at 0x80000000) "
            "with gbox.re4_merc_bot.snapshot", "room": None if s["room"] is None else f"r{s['room']:03x}",
            "in_mercenaries": R.in_mercenaries(s), "timer_s": s["timer"], "combo": s["combo"], "leon": leon,
            "ganados_live": len(ganados), "ganados": ganados,
            "addresses": {"player_pointer": f"{R.P_PLAYER:#010x}", "global_pointer": f"{R.P_GLOBAL:#010x}",
                          "enemy_manager": f"{R.EMMGR:#010x}", "merc_timer": f"{R.MERC_TIMER:#010x}",
                          "merc_combo": f"{R.MERC + 0x28:#010x}"}}


def summary_text(s: dict) -> str:
    """One readable line: where Leon is and what is around him."""
    head = "RE4 Mercenaries" if s.get("in_mercenaries") else "RE4 (not in a Mercenaries round)"
    parts = [f"room {s.get('room') or '?'}", f"clock {s.get('timer_s')} s", f"combo {s.get('combo')}"]
    leon = s.get("leon")
    if leon:
        x, y, z = leon["pos"]
        parts.append(f"Leon at ({x:.0f}, {y:.0f}, {z:.0f}) facing {leon['facing_deg']:.0f}°")
    g = s.get("ganados") or []
    if g and "distance" in g[0]:
        b = g[0]["bearing_deg"]
        side = "ahead" if abs(b) < 10 else f"{abs(b):.0f}° to his {'left' if b > 0 else 'right'}"
        parts.append(f"{len(g)} Ganados live, nearest {g[0]['distance']} away {side}")
    else:
        parts.append(f"{len(g)} Ganados live")
    return f"[{head} at this note: " + " · ".join(parts) + "]"


# --- reads ---------------------------------------------------------------------------------------------------------------
def notes_for(store, game_id: str, limit: int = NOTES_KEPT) -> dict:
    """The game's coaching doc: ticket id / number, title and the last `limit` notes (oldest first)."""
    doc = store.get(KIND, game_id) or {"game_id": game_id, "notes": []}
    keep = max(0, min(int(limit), NOTES_KEPT))
    return doc | {"notes": (doc.get("notes") or [])[-keep:] if keep else []}


def latest(store, game_id: str, now: float | None = None) -> dict:
    """The newest note for a game (the watch panel's Coach line)."""
    now = time.time() if now is None else now
    doc = store.get(KIND, game_id) or {}
    notes = doc.get("notes") or []
    last = notes[-1] if notes else None
    return {"game_id": game_id, "title": doc.get("title"), "request_id": doc.get("request_id"),
            "number": doc.get("number"), "count": len(notes),
            "latest": None if not last else {
                "id": last.get("id"), "note": last.get("note"), "text": last.get("text"), "ts": last.get("ts"),
                "age_s": round(max(0.0, now - (last.get("ts") or now)), 1), "session_id": last.get("session_id"),
                "summary": last.get("summary"),
                "captures": {k: (v or {}).get("state") for k, v in (last.get("captures") or {}).items()}}}


def settle(store, game_id: str, last: int = NOTES_KEPT) -> int:
    """Reading the notes attaches captures whose job ended after the watcher stopped waiting (a busy PC, a server
    restart). Only notes with a capture still pending or timed out are looked at; returns how many."""
    n, since = 0, time.time() - SETTLE_S
    for x in ((store.get(KIND, game_id) or {}).get("notes") or [])[-last:]:
        caps = (x.get("captures") or {}).values()
        if x.get("request_id") and (x.get("ts") or 0) > since and any(
                (c or {}).get("state") == "pending" or (c or {}).get("timed_out") for c in caps):
            reconcile(store, x["request_id"], x["id"])
            n += 1
    return n


def _request_of(store, game_id: str, mid: str) -> str | None:
    for x in (store.get(KIND, game_id) or {}).get("notes") or []:
        if x.get("id") == mid:
            return x.get("request_id")
    rid = ticket_for(store, game_id)                  # older than the kept notes: the open ticket
    return rid if rid and _message(store.get("request", rid), mid) else None


def routes(app, store, auth, create_request, submit):
    """create_request(body, actor) -> request (server.req_create); submit(tool, input, request_id, actor) -> job dict."""

    def _game(sid: str) -> str:
        session = store.get("session", sid)
        if not session:
            raise HTTPException(404, "Session not found")
        return session.get("game_id") or ""

    @app.post("/api/sessions/{sid}/coach")
    def coach_note(sid: str, body: NoteIn, actor=Depends(auth)):
        """A coaching note for autoplay: filed on the game's coaching ticket, the moment captured on the game's PC."""
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "Type a note first")
        out = add_note(store, create_request, submit, sid, text, actor)
        if any(c.get("state") == "pending" for c in out["captures"].values()):
            _spawn(watch, store, out["request_id"], out["message_id"])
        return out

    @app.get("/api/sessions/{sid}/coach/{mid}")
    def coach_note_status(sid: str, mid: str, actor=Depends(auth)):
        rid = _request_of(store, _game(sid), mid)
        st = reconcile(store, rid, mid) if rid else None
        if st is None:
            raise HTTPException(404, "No such coaching note for this game")
        return st

    @app.get("/api/sessions/{sid}/coach")
    def coach_latest(sid: str, actor=Depends(auth)):
        gid = _game(sid)
        settle(store, gid, last=1)                   # the watch panel polls this: the newest note's late captures land
        return latest(store, gid)

    @app.get("/api/coaching/{game_id}")
    def coaching_notes(game_id: str, limit: int = NOTES_KEPT, actor=Depends(auth)):
        settle(store, game_id)
        return notes_for(store, game_id, limit)
