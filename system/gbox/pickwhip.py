"""Pick whip glue (docs/live-picker.md): the thin backend the desktop app and the web viewer share.

Two pieces:

* Pause hold.  While the operator uses the pick whip (eyedropper, right-click character menu) the game stays paused, so
  the frozen frame and the RAM the picker reads describe the same moment.  POST /api/pickwhip/{sid}/hold
  {"op": "pause" | "renew" | "release", "holder": "<client id>", "ttl_s": 20} keeps a lease per client.  The game is
  resumed when the last holder releases, or by the watchdog when every lease has expired (the window closed, the
  renderer crashed, the PC went to sleep).  A game the operator had already paused stays paused: the hold only resumes
  what it paused itself.

* pick_name.  A tool loop on a local model (the Spark's Ollama, the model chosen in the app header) that names what the
  pick whip points at.  The model may call pick_preview and pick_identify itself (submitted as ordinary jobs) and answers
  with report_pick.  Cloud endpoints (llm_endpoints with an api_key_env) are used only when the operator allowed it and
  no local model answered.  With no model at all the answer falls back to the evidence (entity class / model mapping),
  so the pick whip never depends on an LLM.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Callable

from pydantic import BaseModel

from .registry import tool

HOLD_TTL_S = 20.0                 # a client renews every few seconds; three missed renewals and the game resumes
HOLD_MAX_TTL_S = 120.0
WATCHDOG_S = 1.0


# ---------------------------------------------------------------------------------------------------------------- holds

class Holds:
    """Pause leases per session: {sid: {"owned": we paused it, "holders": {holder: expires_at}}}. Thread-safe, no I/O."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self._h: dict[str, dict] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _ttl(ttl: float | None) -> float:
        try:
            t = float(ttl if ttl is not None else HOLD_TTL_S)
        except (TypeError, ValueError):
            t = HOLD_TTL_S
        return max(2.0, min(HOLD_MAX_TTL_S, t))

    def get(self, sid: str) -> dict | None:
        with self._lock:
            r = self._h.get(sid)
            return {"owned": r["owned"], "holders": dict(r["holders"])} if r else None

    def acquire(self, sid: str, holder: str, ttl: float | None, already_paused: bool | None) -> dict:
        """Add a holder. Returns {"pause": True} when this is the first holder and the game must be paused now."""
        now = self.clock()
        with self._lock:
            r = self._h.get(sid)
            first = r is None
            if first:
                r = self._h[sid] = {"owned": not already_paused, "holders": {}}
            r["holders"][holder] = now + self._ttl(ttl)
            return {"pause": first and r["owned"], "owned": r["owned"], "holders": len(r["holders"])}

    def renew(self, sid: str, holder: str, ttl: float | None) -> bool:
        now = self.clock()
        with self._lock:
            r = self._h.get(sid)
            if not r or holder not in r["holders"]:
                return False
            r["holders"][holder] = now + self._ttl(ttl)
            return True

    def release(self, sid: str, holder: str) -> dict:
        """Drop a holder. {"resume": True} when it was the last one and the hold had paused the game."""
        with self._lock:
            r = self._h.get(sid)
            if not r:
                return {"resume": False, "holders": 0}
            r["holders"].pop(holder, None)
            if r["holders"]:
                return {"resume": False, "holders": len(r["holders"])}
            del self._h[sid]
            return {"resume": r["owned"], "holders": 0}

    def drop(self, sid: str) -> None:
        with self._lock:
            self._h.pop(sid, None)

    def expired(self) -> list[tuple[str, bool]]:
        """Expire stale holders; [(sid, resume?)] for every session whose last holder just went away."""
        now = self.clock()
        out = []
        with self._lock:
            for sid in list(self._h):
                r = self._h[sid]
                r["holders"] = {h: t for h, t in r["holders"].items() if t > now}
                if not r["holders"]:
                    del self._h[sid]
                    out.append((sid, r["owned"]))
        return out

    def snapshot(self) -> dict:
        now = self.clock()
        with self._lock:
            return {sid: {"owned": r["owned"], "holders": {h: round(t - now, 1) for h, t in r["holders"].items()}}
                    for sid, r in self._h.items()}


def runtime_paused(info) -> bool | None:
    """Pause state from a session 'info' answer (same reading as clients/web/viz/session-pause.js); None = unknown."""
    rt = (info or {}).get("runtime", info) if isinstance(info, dict) else None
    if not isinstance(rt, dict):
        return None
    if isinstance(rt.get("paused"), bool):
        return rt["paused"]
    st = str(rt.get("state") or "").upper()
    if st == "PAUSED":
        return True
    if st in ("PLAYING", "RUNNING"):
        return False
    return None


class HoldIn(BaseModel):
    op: str = "pause"                 # pause | renew | release
    holder: str = "app"               # one id per client window (desktop shell, web viewer tab)
    ttl_s: float | None = None


def register(app, auth, store, *, rpc: Callable[[str, str], dict], submit_op: Callable[[str, str], object],
             holds: Holds | None = None, watchdog: bool = True):
    """Routes on the control plane (server.create_app). rpc(sid, op) asks the live session (raises when it can't);
    submit_op(sid, op) queues a session_op job (the fallback for sessions without the live channel)."""
    from fastapi import Depends, HTTPException

    H = holds or Holds()
    app.state.pickwhip_holds = H

    def set_paused(sid: str, op: str, live: bool = True) -> str:
        try:
            if not live:
                raise RuntimeError("no live session channel")
            rpc(sid, op)
            return "rpc"
        except Exception:                                     # noqa: BLE001 - older workers: the job queue does it
            try:
                submit_op(sid, op)
                return "job"
            except Exception as e:                            # noqa: BLE001
                return f"failed: {e}"

    def running(sid: str) -> bool:
        s = store.get("session", sid)
        return bool(s) and s.get("state") == "running"

    started: list = []

    def start_watchdog():                                     # lazily, with the first hold: nothing runs until the pick whip is used
        if not watchdog or started:
            return
        started.append(True)

        def loop():
            while True:
                time.sleep(WATCHDOG_S)
                try:
                    tick()
                except Exception:                             # noqa: BLE001 - the watchdog never dies
                    pass
        threading.Thread(target=loop, name="pickwhip-watchdog", daemon=True).start()

    @app.post("/api/pickwhip/{sid}/hold")
    def pickwhip_hold(sid: str, h: HoldIn, actor=Depends(auth)):
        """Pause the game while the pick whip is open; resumed on release or by the watchdog when the lease expires."""
        if h.op == "pause":
            start_watchdog()
            if not running(sid):
                raise HTTPException(409, "this game session is not running")
            already, live = None, True
            if H.get(sid) is None:
                try:
                    already = runtime_paused(rpc(sid, "info"))
                except Exception:                             # noqa: BLE001 - no live channel: assume it is playing
                    live = False
            r = H.acquire(sid, h.holder, h.ttl_s, already)
            via = set_paused(sid, "pause", live) if r["pause"] else ""
            store.audit(actor, "pickwhip.pause", sid, {"holder": h.holder, "owned": r["owned"], "via": via})
            return {"paused": True, "owned": r["owned"], "holders": r["holders"], "via": via,
                    "ttl_s": Holds._ttl(h.ttl_s)}
        if h.op == "renew":
            return {"ok": H.renew(sid, h.holder, h.ttl_s)}
        if h.op == "release":
            r = H.release(sid, h.holder)
            via = set_paused(sid, "resume") if r["resume"] and running(sid) else ""
            if r["resume"]:
                store.audit(actor, "pickwhip.resume", sid, {"holder": h.holder, "via": via})
            return {"resumed": bool(r["resume"]), "holders": r["holders"], "via": via}
        raise HTTPException(422, "op must be pause, renew or release")

    @app.get("/api/pickwhip/holds")
    def pickwhip_holds(actor=Depends(auth)):
        return H.snapshot()

    def tick():
        for sid, resume in H.expired():
            if resume and running(sid):
                via = set_paused(sid, "resume")
                store.audit("gbox-watchdog", "pickwhip.resume", sid, {"why": "hold expired", "via": via})

    app.state.pickwhip_tick = tick
    return H


# ------------------------------------------------------------------------------------------------------------ pick_name

PICK_TOOLS = ("pick_preview", "pick_identify")

SYSTEM = ("You name the thing a player pointed at in a running video game. You get evidence from gBox's live picker "
          "(entity class, kind, RAM pointer, model mapping, reverse-engineering notes) and sometimes a crop of the frame. "
          "Call pick_identify (deeper: model, RAM, Ghidra/REA evidence, slot) or pick_preview (fast: entity under the point) "
          "when the evidence is thin. Then call report_pick exactly once. Use a character's proper name only when the "
          "evidence or the picture makes it clear; otherwise describe it (\"soldier in green fatigues\"). Never invent RAM "
          "addresses or model files.")

TOOL_SPECS = [
    {"type": "function", "function": {"name": "pick_preview", "description": "Fast: the entity under a point of the game picture "
     "(class, kind, RAM pointer, world position, model mapping).",
     "parameters": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}}}}},
    {"type": "function", "function": {"name": "pick_identify", "description": "Deeper identification of the entity under a point: "
     "model, RAM addresses, Ghidra/REA evidence, the character slot it fills.",
     "parameters": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}}}}},
    {"type": "function", "function": {"name": "report_pick", "description": "Final answer: what the picked thing is.",
     "parameters": {"type": "object", "required": ["name", "kind"], "properties": {
         "name": {"type": "string", "description": "short specific name, or a description of what is seen"},
         "kind": {"type": "string", "enum": ["player", "character", "enemy", "npc", "vehicle", "weapon", "item", "object", "scenery"]},
         "model": {"type": "string", "description": "model / mesh name from the evidence, if any"},
         "slot": {"type": "string", "description": "the character slot it fills (player, enemy_3, ...), if known"},
         "confidence": {"type": "number", "description": "0..1"},
         "why": {"type": "string", "description": "one sentence: which evidence"}}}}},
]


class Route(BaseModel):
    name: str
    url: str
    model: str
    local: bool = True
    key_env: str | None = None


def llm_routes(config, model: str = "", allow_cloud: bool = False, image: bool = False) -> list[Route]:
    """Local first: the requested model (the app header's choice) on the agent's Ollama, then every llm_endpoints entry
    that needs no API key. Cloud (an api_key_env whose variable is set) only with allow_cloud."""
    want = "" if (model or "").strip().lower() in ("", "auto") else model.strip()
    agent = getattr(config, "agent", None) or {}
    eps = list(getattr(config, "llm_endpoints", None) or [])
    out: list[Route] = []
    seen = set()

    def add(r: Route):
        k = (r.url.rstrip("/"), r.model)
        if r.model and k not in seen:
            seen.add(k)
            out.append(r)
    local_eps = [e for e in eps if not e.api_key_env]
    if agent.get("llm_url"):
        add(Route(name="agent", url=agent["llm_url"],
                  model=want or (agent.get("vision_model") if image else "") or (local_eps[0].model if local_eps else agent.get("model", ""))))
    for e in local_eps:
        if want:
            add(Route(name=e.name, url=e.url, model=want))
        add(Route(name=e.name, url=e.url, model=e.model))
    if allow_cloud:
        for e in eps:
            if e.api_key_env and os.environ.get(e.api_key_env):
                add(Route(name=e.name, url=e.url, model=e.model, local=False, key_env=e.api_key_env))
    return out


def evidence_name(evidence: dict) -> dict:
    """The answer without any model: the picker's own words."""
    ev = evidence or {}
    ent = ev.get("entity") if isinstance(ev.get("entity"), dict) else None
    p = ent or ev.get("picked") or {}
    model = ev.get("model")
    if isinstance(model, dict):
        model = model.get("name") or model.get("file") or ""
    elif isinstance(model, (list, tuple)):
        model = " / ".join(str(m) for m in model if m)
    name = ev.get("name") or p.get("name") or p.get("class") or p.get("kind") or ""
    return {"name": str(name or "unknown"), "kind": str(p.get("kind") or ev.get("kind") or "object"),
            "model": str(model or ""), "slot": str(ev.get("slot") or p.get("slot") or ""),
            "confidence": 0.3 if name else 0.0, "why": "picker evidence (no model answered)" if name else "nothing identified"}


def _short(v, n: int = 2500) -> str:
    s = json.dumps(v, default=str, separators=(",", ":"))
    return s if len(s) <= n else s[:n] + "…"


def _answer_from_text(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    return d if isinstance(d, dict) and d.get("name") else None


def name_pick(inp, routes: list[Route], post: Callable[[Route, dict], dict], run_tool: Callable[[str, dict], dict],
              progress: Callable[[float, str], None] = lambda p, m: None) -> dict:
    """The tool loop. post(route, body) -> OpenAI chat.completions JSON; run_tool(name, args) -> the tool's result."""
    evidence = dict(inp.evidence or {})
    user = [{"type": "text", "text": "Picked at x=%.3f, y=%.3f of the game picture. Evidence so far: %s"
             % (inp.x, inp.y, _short(evidence) if evidence else "none yet")}]
    if inp.image_b64:
        user.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + inp.image_b64}})
    steps: list[dict] = []
    tried = []
    for i, r in enumerate(routes):
        where = "local" if r.local else "cloud"
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user if inp.image_b64 else user[0]["text"]}]
        progress(10 + i * 5, f"asking {r.model} ({where}, {r.name})")
        try:
            for step in range(max(1, inp.max_steps)):
                body = {"model": r.model, "temperature": 0, "messages": msgs, "tools": TOOL_SPECS}
                res = post(r, body)
                msg = ((res.get("choices") or [{}])[0]).get("message") or {}
                calls = msg.get("tool_calls") or []
                if not calls:
                    ans = _answer_from_text(msg.get("content") or "")
                    if ans:
                        return _done(ans, r, steps, evidence, progress)
                    msgs.append({"role": "assistant", "content": msg.get("content") or ""})
                    msgs.append({"role": "user", "content": "Call report_pick now."})
                    continue
                msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
                for c in calls:
                    fn = (c.get("function") or {})
                    name = fn.get("name") or ""
                    try:
                        args = json.loads(fn.get("arguments") or "{}") if isinstance(fn.get("arguments"), str) else (fn.get("arguments") or {})
                    except ValueError:
                        args = {}
                    if name == "report_pick":
                        return _done(args, r, steps, evidence, progress)
                    if name in PICK_TOOLS:
                        x, y = float(args.get("x", inp.x)), float(args.get("y", inp.y))
                        progress(30 + step * 15, f"{r.model} calls {name}({x:.2f}, {y:.2f})")
                        try:
                            out = run_tool(name, {"x": x, "y": y})
                        except Exception as e:                # noqa: BLE001 - the model hears why
                            out = {"error": str(e)[:300]}
                        if isinstance(out, dict) and not out.get("error"):
                            evidence.setdefault(name, out)
                        steps.append({"tool": name, "x": x, "y": y, "ok": not (isinstance(out, dict) and out.get("error"))})
                        progress(35 + step * 15, f"{name}: " + (str(out.get("error")) if isinstance(out, dict) and out.get("error")
                                                                else _short(out, 160)))
                        content = _short(out)
                    else:
                        content = json.dumps({"error": f"unknown tool {name}"})
                    msgs.append({"role": "tool", "tool_call_id": c.get("id") or name, "name": name, "content": content})
            tried.append(f"{r.name}/{r.model}: no report_pick after {inp.max_steps} steps")
        except Exception as e:                                # noqa: BLE001 - next route
            tried.append(f"{r.name}/{r.model}: {str(e)[:160]}")
            progress(12 + i * 5, f"{r.model} unavailable: {str(e)[:120]}")
    out = evidence_name(evidence.get("pick_identify") or evidence.get("pick_preview") or evidence)
    progress(95, f"no model answered; using the picker's evidence: {out['name']}")
    return out | {"route": "evidence", "endpoint": "", "llm_model": "", "steps": steps, "tried": tried}


def _done(ans: dict, r: Route, steps: list, evidence: dict, progress) -> dict:
    base = evidence_name(evidence.get("pick_identify") or evidence.get("pick_preview") or evidence)
    out = {k: (ans.get(k) if ans.get(k) not in (None, "") else base[k]) for k in ("name", "kind", "model", "slot", "confidence", "why")}
    try:
        out["confidence"] = max(0.0, min(1.0, float(out["confidence"])))
    except (TypeError, ValueError):
        out["confidence"] = 0.5
    progress(95, f"{r.model} ({'local' if r.local else 'cloud'}): {out['name']}")
    return out | {"route": "local" if r.local else "cloud", "endpoint": r.name, "llm_model": r.model, "steps": steps}


class PickNameIn(BaseModel):
    target_session: str = ""          # the game session; not session_id: naming runs next to the LLM, not on the gaming PC
    x: float = 0.5                    # the pick, 0..1 across / down the game window
    y: float = 0.5
    window_aspect: float = 4 / 3
    evidence: dict = {}               # what the client already has (pick_preview / pick_identify result)
    image_b64: str = ""               # optional crop around the pick (vision-capable models look at it)
    model: str = ""                   # the app header's model; "" / "auto" = the local default
    allow_cloud: bool = False         # cloud only when the operator enabled it AND no local model answered
    max_steps: int = 4


class PickNameOut(BaseModel):
    result: dict


@tool("pick_name", "1.0", PickNameIn, PickNameOut, capabilities=["llm"], timeout_s=240)
def pick_name(inp: PickNameIn, ctx):
    """Pick whip naming on a local model: what is at this point of the game? The model may call pick_preview /
    pick_identify (as jobs on the session's PC) and answers with report_pick; no model -> the picker's own evidence."""
    import httpx

    def post(r: Route, body: dict) -> dict:
        headers = {"Authorization": f"Bearer {os.environ[r.key_env]}"} if r.key_env else {}
        res = httpx.post(f"{r.url.rstrip('/')}/chat/completions", json=body, headers=headers, timeout=90)
        res.raise_for_status()
        return res.json()

    def run_tool(name: str, args: dict) -> dict:
        if not inp.target_session or not ctx.server:
            return {"error": "no game session to look at"}
        sid = inp.target_session
        r = httpx.post(f"{ctx.server}/api/jobs", headers=ctx.headers, timeout=30, json={
            "tool": name, "input": {"session_id": sid, "x": args["x"], "y": args["y"], "window_aspect": inp.window_aspect},
            "require_worker": sid.rsplit("-", 1)[0]})
        if r.status_code == 404:
            return {"error": f"{name} is not available on this gBox yet"}
        if r.status_code >= 400:
            return {"error": f"{name}: {r.status_code} {r.text[:200]}"}
        j = r.json()
        t0 = time.time()
        while j.get("state") in ("queued", "running") and time.time() - t0 < 60:
            time.sleep(0.4)
            j = httpx.get(f"{ctx.server}/api/jobs/{j['id']}", headers=ctx.headers, timeout=30).json()
        if j.get("state") != "succeeded":
            return {"error": f"{name}: {j.get('error') or j.get('state')}"}
        return (j.get("output") or {}).get("result") or j.get("output") or {}

    routes = llm_routes(ctx.config, inp.model, inp.allow_cloud, bool(inp.image_b64))
    ctx.progress(5, "naming the pick: " + (", ".join(f"{r.model} ({'local' if r.local else 'cloud'})" for r in routes[:3]) or "no model configured"))
    return {"result": name_pick(inp, routes, post, run_tool, ctx.progress)}
