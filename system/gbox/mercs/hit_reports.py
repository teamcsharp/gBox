"""Player-hurt follow reports (operator 2026-11-11): every time the player is hurt, file one Hermes request.

"I'm watching the bot just stand here and let people wind up and do their animations to hit them. And that shouldn't be
happening." The engine feeds this one playing tick at a time; when its hit counter rises (the driver's hits_taken) the
module posts the evidence to /api/requests: the hp before/after, the attackers (the wind-up/near ones the core tracks:
class, distance, state, eta), what the bot was doing/why, the clock and position. Deduped per hit, at most
MAX_PER_ROUND per round; a failed post is a stat and never stalls the round.
"""
from __future__ import annotations

import threading
import time

MAX_PER_ROUND = 6
_CFG = {"url": "", "token": "", "title": "", "session_id": ""}
_LOCK = threading.Lock()


def configure(url="", token="", *, title="", session_id=""):
    _CFG.update(url=str(url or "").rstrip("/"), token=str(token or ""), title=str(title or ""),
                session_id=str(session_id or ""))


def post(url, token, payload):
    """The one HTTP call (monkeypatchable in tests)."""
    import httpx
    headers = {"Authorization": "Bearer " + token, "x-gbox-actor": "agent", "Content-Type": "application/json"}
    with httpx.Client(timeout=10.0) as client:
        response = client.post(url + "/api/requests", headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


def _attackers(rows):
    out = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        out.append(f"{row.get('kind') or 'class ?'} at {row.get('dist')} cm, state {row.get('state')}, "
                   f"eta {row.get('eta')}, act {row.get('act')}")
    return out


def body_for(stats, snap, hp_before, hp_after, attackers, doing=None, why=None) -> str:
    player = (snap or {}).get("player") or {}
    pos = player.get("pos") or ()
    lines = [
        "PLAYER HURT - automated follow report (gBox MercMode).",
        f"Title: {_CFG.get('title') or '?'} | session: {_CFG.get('session_id') or '?'} | round: "
        f"{stats.get('round_evidence_id') or '?'}",
        f"hp {hp_before} -> {hp_after} | hits_taken {stats.get('hits_taken')} | clock {stats.get('timer')}",
        f"Position: {[round(v) for v in pos] if pos else '?'}",
        "Attackers: " + ("; ".join(_attackers(attackers)) or "none tracked"),
        f"Doing: {doing or '?'} / {why or '?'}",
        "The operator: the bot must detect who is about to attack and counter/prevent it (not stand through the "
        "wind-up). This hit is filed so the threat-response work can see it; the round report carries the totals.",
    ]
    return "\n".join(lines)


def _hit_count(stats):
    """The hurt counter the title keeps: the damage observer's player_damage_events (RE5/RE6) first, then the
    driver's hits_taken (the RE4 playbook's own). None when neither is a number."""
    for key in ("player_damage_events", "hits_taken"):
        value = stats.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def observe(stats, snap, now, *, attackers=None, doing=None, why=None, round_id=None):
    """One playing tick: file a report when the hurt counter rises. Never raises.

    The counter and its baseline are per round (`round_evidence_id`): a new round's count starts over, so its first
    hit is a hit (the earlier version kept the old round's baseline and silently skipped the new round's early
    hits).
    """
    taken = _hit_count(stats)
    player = (snap or {}).get("player") or {}
    hp = player.get("hp")
    hp_before = stats.get("_hit_report_hp")
    stats["_hit_report_hp"] = hp
    rid = str(round_id or stats.get("round_evidence_id") or _CFG.get("session_id") or "")
    with _LOCK:
        if stats.get("_hit_report_round") != rid:
            stats["_hit_report_round"] = rid
            stats["_hit_reports"] = 0
            stats["_hit_report_taken"] = None         # the new round's first hit is a hit, not a baseline
        prev = stats.get("_hit_report_taken")
        stats["_hit_report_taken"] = taken
        if not isinstance(taken, int) or taken <= 0:
            return None
        if isinstance(prev, int) and taken <= prev:   # no new hit on this tick
            return None
        if int(stats.get("_hit_reports") or 0) >= MAX_PER_ROUND:
            stats["hit_reports_suppressed"] = int(stats.get("hit_reports_suppressed", 0)) + 1
            return None
        if not (_CFG.get("url") and _CFG.get("token")):
            stats["hit_report_error"] = "no control plane configured"
            return None
        stats["_hit_reports"] = int(stats.get("_hit_reports") or 0) + 1
        payload = {"title": f"Player hurt in {_CFG.get('title') or 'Mercs'} (round {rid})"[:140],
                   "body": body_for(stats, snap, hp_before, hp, attackers, doing=doing, why=why),
                   "source": "agent", "kind": "text", "author": "agent", "automated": True,
                   "context": {"session_id": _CFG.get("session_id"), "round_id": rid, "title": _CFG.get("title"),
                               "hp_before": hp_before, "hp_after": hp, "hits_taken": taken}}
        try:
            reply = post(_CFG["url"], _CFG["token"], payload)
        except Exception as exc:                         # noqa: BLE001 - a failed report never stalls the round
            stats["hit_report_error"] = f"{type(exc).__name__}: {exc}"[:200]
            stats["hit_report_failures"] = int(stats.get("hit_report_failures", 0)) + 1
            return None
        stats["hit_reports"] = int(stats.get("hit_reports", 0)) + 1
        stats["hit_report_last"] = {"at": round(time.time(), 1), "request": (reply or {}).get("id"),
                                    "round": rid, "hp_before": hp_before, "hp_after": hp}
        return stats["hit_report_last"]
