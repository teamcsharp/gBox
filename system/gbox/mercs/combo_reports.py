"""Combo-loss follow reports (operator 2026-11-11): every combo lost in a Mercs round files one Hermes request.

"I want G-Box to follow report in Merc mode every time the combo is lost in Merc mode." The engine feeds this one
playing tick at a time; the module keeps the previous combo and, on a fall to 0 from a positive value, posts the
evidence to the control plane's /api/requests (deduped per round and second, at most MAX_PER_ROUND per round; a
failed post is a stat and never stalls the round). The round report still carries combo_breaks for the totals.
"""
from __future__ import annotations

import math
import threading
from .follow_report_delivery import submit

MAX_PER_ROUND = 3
THREAT_CM = 600.0
_CFG = {"url": "", "token": "", "title": "", "session_id": ""}
_LOCK = threading.Lock()


def configure(url="", token="", *, title="", session_id=""):
    """The control plane and the round's provenance (the engine calls this once per run)."""
    with _LOCK:
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


def _threats(snap):
    """The living enemies within THREAT_CM of him at the loss: class, distance (cm), hp and the state word."""
    player = (snap or {}).get("player") or {}
    pos = player.get("pos")
    out = []
    if not pos:
        return out
    for enemy in (snap or {}).get("enemies") or ():
        if not isinstance(enemy, dict):
            continue
        point = enemy.get("pos")
        if not point:
            continue
        try:
            dist = math.hypot(point[0] - pos[0], point[2] - pos[2])
        except (TypeError, ValueError, IndexError):
            continue
        if dist > THREAT_CM:
            continue
        out.append((dist, enemy))
    out.sort(key=lambda row: row[0])
    return [f"{e.get('class') or 'class ?'} at {dist:.0f} cm (hp {e.get('hp')})" for dist, e in out[:6]]


def body_for(stats, snap, *, doing=None, why=None, prev=None) -> str:
    player = (snap or {}).get("player") or {}
    prev = stats.get("_combo_report_prev") if prev is None else prev
    lines = [
        "COMBO LOST - automated follow report (gBox MercMode).",
        f"Title: {_CFG.get('title') or '?'} | session: {_CFG.get('session_id') or '?'} | round: "
        f"{stats.get('round_evidence_id') or '?'}",
        f"Combo: {prev} -> 0 | kills {stats.get('kills')} | score {stats.get('score')} | clock {stats.get('timer')}",
        f"Player hp: {player.get('hp')} at {[round(v) for v in (player.get('pos') or ())] if player.get('pos') else '?'}",
        "Threats within 6 m: " + ("; ".join(_threats(snap)) or "none"),
        f"Doing: {doing or '?'} / {why or '?'}",
        "The operator's requirement: the bot must maintain the combo. The round report carries the totals "
        "(combo_breaks, combo_best); this loss is filed so the doctrine/aim/ordnance work can see it.",
    ]
    return "\n".join(lines)


def observe(stats, snap, now, *, doing=None, why=None, round_id=None):
    """One playing tick: file the loss when the combo falls to 0 from a positive value. Never raises."""
    combo = (snap or {}).get("combo") if isinstance(snap, dict) else None
    if not isinstance(combo, int) or isinstance(combo, bool):
        return None
    rid = str(round_id or stats.get("round_evidence_id") or _CFG.get("session_id") or "")
    with _LOCK:
        if stats.get("_combo_report_round") != rid:       # a new round: the count starts over
            stats["_combo_report_round"] = rid
            stats["_combo_reports"] = 0
            stats['_combo_report_prev'] = None
        prev = stats.get('_combo_report_prev')
        stats['_combo_report_prev'] = combo
        if not isinstance(prev, int) or isinstance(prev, bool) or prev <= 0 or combo != 0:
            return None
        if int(stats.get("_combo_reports") or 0) >= MAX_PER_ROUND:
            stats["combo_reports_suppressed"] = int(stats.get("combo_reports_suppressed", 0)) + 1
            return None
        if not (_CFG.get("url") and _CFG.get("token")):
            stats["combo_report_error"] = "no control plane configured"
            return None
        stats["_combo_reports"] = int(stats.get("_combo_reports") or 0) + 1
        payload = {"title": f"Combo lost in {_CFG.get('title') or 'Mercs'} (round {rid})"[:140],
                   "body": body_for(stats, snap, doing=doing, why=why, prev=prev), "source": "agent", "kind": "text",
                   "author": "agent", "automated": True,
                   "context": {"session_id": _CFG.get("session_id"), "round_id": rid, "title": _CFG.get("title"),
                               "combo_before": prev, "combo": 0}}
        config = dict(_CFG)
        kills = stats.get('kills')
    return submit(post, config, payload, stats, 'combo',
                  {'round':rid, 'combo_before':prev, 'kills':kills})
