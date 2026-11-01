"""Bounded MercMode controls for PineLive, dispatched through the gBox MCP service.

The HTTP facade accepts only a service bearer header. It never exposes arbitrary
MCP tools or treats a media URL token as permission to change a running game.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import math
import time
from urllib.parse import quote

from fastapi import Request

SWITCH = {"52d15709be0fda1a": "re5", "115f9cdbba115432": "re6"}
# op, label, status path, optional (min, max, step). Match the desktop's live controls.
MODS = {
    "re5": [
        ("unlimited_health", "Unlimited life", "unlimited_health", None),
        ("infinite_ammo", "Infinite ammo", "infinite_ammo", None),
        ("infinite_spray", "Infinite first aid spray", "infinite_spray", None),
        ("instant_qte", "Native QTE assist", "qte_assist.enabled", None),
        ("fire_rate", "Fire rate", "fire_rate_x", (1, 80, 1)),
        ("bullet_damage", "Bullet damage", "bullet_damage_x", (0.1, 1000, 0.1)),
        ("turn_speed", "Turning and aiming speed", "turn_speed_x", (1, 10, 0.5)),
        ("kill_time", "Time added per kill", "kill_time_on", None),
    ],
    "re6": [
        ("infinite_ammo", "Infinite ammo", "infinite_ammo", None),
        ("infinite_tablets", "Infinite tablets", "infinite_tablets", None),
        ("infinite_stamina", "Infinite stamina", "infinite_stamina", None),
        ("infinite_grenades", "Infinite grenades and remote bombs", "infinite_grenades", None),
        ("auto_qte", "QTE assist", "auto_qte", None),
        ("auto_qte_ram", "Native grab escape", "auto_qte_ram", None),
        ("kill_time", "Time added per kill", "kill_time_on", None),
        ("fire_rate", "Fire rate", "fire_rate_x", (1, 80, 0.5)),
        ("magnum_speed", "Magnum fire and recoil speed", "magnum_speed_x", (1, 6, 0.5)),
        ("throw_speed", "Grenade throw speed", "throw_speed_x", (1, 20, 0.5)),
        ("quick_attack", "Quick attack speed", "quick_attack_x", (1, 10, 0.5)),
        ("down_fire", "Fire rate while down", "down_fire_x", (1, 10, 0.5)),
    ],
}
WAITING = {"queued", "running"}
ALLOWED = {
    "status": {"session_id", "op", "job_id"},
    "set": {"session_id", "op", "control", "value"},
    "flash_now": {"session_id", "op", "request_id"},
    "magnum_quick4": {"session_id", "op", "request_id"},
    "equip_primary": {"session_id", "op", "request_id", "item"},
    "grenade_ring": {"session_id", "op", "request_id", "kind"},
    "set_infinite_ammo": {"session_id", "op", "request_id", "enabled"},
}
GRENADE_RING_KINDS = ("flash", "hand", "incendiary")
SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"session_id": {"type": "string"},
              "op": {"type": "string", "enum": list(ALLOWED), "default": "status"},
              "job_id": {"type": "string"}, "control": {"type": "string"},
              "value": {"type": ["number", "boolean"]}, "request_id": {"type": "string"},
              "enabled": {"type": "boolean"},
              "item": {"type": "integer", "minimum": 1, "maximum": 255},
              "kind": {"type": "string", "enum": list(GRENADE_RING_KINDS)}},
          "required": ["session_id"]}


def validate_request(args):
    if not isinstance(args, dict):
        raise ValueError("control request must be an object")
    op = args.get("op", "status")
    if op not in ALLOWED or set(args) - ALLOWED[op]:
        raise ValueError("unsupported live control operation or fields")
    sid = args.get("session_id")
    if not isinstance(sid, str) or not sid or len(sid) > 160 or "/" in sid:
        raise ValueError("invalid session_id")
    if op == "set" and (not isinstance(args.get("control"), str) or "value" not in args):
        raise ValueError("set needs control and value")
    if op in ("flash_now", "equip_primary", "magnum_quick4", "grenade_ring", "set_infinite_ammo"):
        import uuid
        try:
            uuid.UUID(args.get("request_id", ""))
        except (ValueError, AttributeError, TypeError):
            raise ValueError("a new UUID request_id is required for each click") from None
    if op == "equip_primary" and (type(args.get("item")) is not int or not 1 <= args["item"] <= 255):
        raise ValueError("invalid primary weapon item")
    if op == "set_infinite_ammo" and type(args.get("enabled")) is not bool:
        raise ValueError("infinite ammo needs an explicit boolean enabled value")
    if op == "grenade_ring" and "kind" in args and args["kind"] not in GRENADE_RING_KINDS:
        raise ValueError("invalid grenade ring kind")
    if "job_id" in args and (not isinstance(args["job_id"], str) or not args["job_id"] or len(args["job_id"]) > 160):
        raise ValueError("invalid job_id")
    return op


def read_path(value, path):
    for key in path.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    return value


def control_inventory(title, view, status):
    controls = []
    for op, label, field, bounds in MODS.get(title, []):
        value = read_path(status, field)
        valid = type(value) in (int, float) and math.isfinite(value) if bounds else type(value) is bool
        cap = status.get("capabilities", {}).get(op, {})
        available = valid and (title != "re5" or cap.get("available") is True)
        row = {"id": "mod." + op, "label": label, "group": "Live mods",
               "kind": "number" if bounds else "boolean", "value": value if valid else None,
               "available": bool(available)}
        if bounds:
            row.update(zip(("min", "max", "step"), bounds))
        if not available:
            row["reason"] = cap.get("reason") or "The worker has no verified value for this control."
        controls.append(row)
    for knob in view.get("knobs", []):
        if not isinstance(knob, dict) or knob.get("kind") not in ("bool", "float", "int"):
            continue
        row = {"id": "behavior." + knob["name"], "label": knob["label"], "group": knob["group"],
               "kind": "boolean" if knob["kind"] == "bool" else "number", "value": knob["value"],
               "available": True, "help": knob.get("help", ""), "saved": bool(knob.get("set"))}
        if row["kind"] == "number":
            row.update({k: knob[k] for k in ("min", "max", "step")})
            row["integer"] = knob["kind"] == "int"
        controls.append(row)
    return controls


def change_input(control, value):
    if not control.get("available"):
        raise ValueError(control.get("reason") or "control is unavailable")
    if control["kind"] == "boolean":
        if type(value) is not bool:
            raise ValueError("control needs a boolean")
    elif (type(value) not in (int, float) or not math.isfinite(value)
          or not control["min"] <= value <= control["max"]
          or control.get("integer") and not float(value).is_integer()):
        raise ValueError("control value is outside its allowed range")
    kind, key = control["id"].split(".", 1)
    if kind == "behavior":
        return {"op": "bot_logic", "values": {key: value}}
    return {"op": key, **({"on": value} if control["kind"] == "boolean"
                          else {"multiplier": value, "on": value != 1})}


class Controls:
    """One MCP-server-owned snapshot cache; all mutations stay pinned to one live run."""
    def __init__(self, get, post, sleep=asyncio.sleep, clock=time.monotonic):
        self.get, self.post, self.sleep, self.clock = get, post, sleep, clock
        self.cache, self.pending, self.locks = {}, {}, {}

    async def context(self, sid):
        # Historical session enrichment is expensive; only live rows can own this panel.
        # MercMode already supplies authoritative worker online state, avoiding
        # the large /api/workers inventory (source hashes and tool catalogs).
        sessions, rotation = await asyncio.gather(self.get("/api/sessions", include_ended="false"),
                                                  self.get("/api/mercmode"))
        row = next((s for s in sessions if s.get("session_id") == sid), None)
        if not row or row.get("state") != "running" or row.get("ended") or row.get("warm") or row.get("stopping"):
            raise ValueError("The selected session is no longer an active game. Refresh the stream controls.")
        wid = sid.split("-")[0]
        host = next((h for h in rotation.get("hosts", []) if h.get("id") == wid), None)
        run = (host or {}).get("current_run") or {}
        if (not (host or {}).get("online") or row.get("worker_online") is False
                or run.get("session_id") != sid or run.get("phase") != "playing" or run.get("game_id") != row.get("game_id")):
            raise ValueError("The active MercMode run changed or is waiting. Refresh the stream controls.")
        return {"session_id": sid, "worker_id": wid, "title": row.get("title", ""),
                "game_id": row.get("game_id"), "adapter": row.get("adapter"),
                "controls_title": SWITCH.get(row.get("game_id")) if row.get("adapter") in ("citron", "eden") else None}

    async def check_run(self, ctx):
        """Cheap handover fence; the full live-session check precedes each request."""
        rotation = await self.get("/api/mercmode")
        host = next((h for h in rotation.get("hosts", []) if h.get("id") == ctx["worker_id"]), None)
        run = (host or {}).get("current_run") or {}
        if (not (host or {}).get("online") or run.get("session_id") != ctx["session_id"]
                or run.get("game_id") != ctx["game_id"] or run.get("phase") != "playing"):
            raise ValueError("The active game changed. Refresh its controls.")

    async def brief_wait(self, job):
        # No one-second UI floor, and no long request occupies a streaming handler.
        for pause in (0.1, 0.15, 0.25):
            if job.get("state") not in WAITING:
                break
            await self.sleep(pause)
            job = await self.get("/api/jobs/" + quote(job["id"], safe=""))
        return job

    async def job(self, ctx, inp, action=None):
        sid = ctx["session_id"]
        job = await self.post("/api/jobs", {"tool": "re5_mods", "agent_use": False,
            "require_worker": ctx["worker_id"], "input": {"session_id": sid, **inp}})
        self.pending[job["id"]] = {"session_id": sid, "action": action, "at": self.clock()}
        return await self.brief_wait(job)

    def consume(self, ctx, job):
        sid, jid = ctx["session_id"], job.get("id")
        inp = job.get("input") or {}
        if (job.get("tool") != "re5_mods" or inp.get("session_id") != sid
                or job.get("require_worker", job.get("worker_id")) != ctx["worker_id"]
                or inp.get("op") not in {"live_controls", "bot_logic", *(d[0] for d in MODS.get(ctx["controls_title"], []))}):
            raise ValueError("That job does not belong to these live controls.")
        if job.get("state") in WAITING:
            return {"id": jid, "state": job["state"]}
        own = self.pending.pop(jid, {})
        if job.get("state") != "succeeded":
            raise ValueError(str(job.get("error") or "The worker could not apply these controls.")[:300])
        result = (job.get("output") or {}).get("result")
        if not isinstance(result, dict) or result.get("verified") is not True:
            raise ValueError((result or {}).get("reason") if isinstance(result, dict) else "The worker returned no verified control result.")
        old = self.cache.get(sid, {})
        view = result.get("view") or (result if isinstance(result.get("knobs"), list) else old.get("view", {}))
        status = result.get("status") or old.get("status", {})
        if not isinstance(view, dict) or not isinstance(status, dict) or view.get("title") != ctx["controls_title"]:
            raise ValueError("The worker returned settings for a different game.")
        controls = control_inventory(ctx["controls_title"], view, status)
        action = own.get("action")
        if action:
            changed = next((c for c in controls if c["id"] == action["control"]), None)
            wanted = action["value"]
            actual = changed.get("value") if changed else None
            if type(wanted) is bool:
                verified = actual is wanted
            else:
                verified = type(actual) in (int, float) and abs(actual - wanted) < 0.0001
            if not verified:
                self.cache.pop(sid, None)
                raise ValueError("The worker did not confirm the selected control value. Refresh current settings.")
        self.cache[sid] = {"view": view, "status": status, "at": self.clock()}
        return None

    async def call(self, args):
        op = validate_request(args)
        sid = args["session_id"]
        lock = self.locks.setdefault(sid, asyncio.Lock())
        async with lock:
            return await self._call(args, op, sid)

    async def _call(self, args, op, sid):
        ctx = await self.context(sid)
        intervention = await self.get(f"/api/sessions/{quote(sid, safe='')}/interventions")
        result = {"session": ctx, "session_id": sid, "worker_id": ctx["worker_id"], "title": ctx["title"],
                  "available": bool(ctx["controls_title"] or intervention.get("available") and intervention.get("capabilities")),
                  "controls": [], "interventions": intervention}
        if not ctx["controls_title"]:
            result["reason"] = "This game's worker has no live behavior sliders; native actions appear when supported."
        cached = self.cache.get(sid, {})
        result["controls"] = control_inventory(ctx["controls_title"], cached.get("view", {}), cached.get("status", {}))
        if op in ("flash_now", "equip_primary", "magnum_quick4", "grenade_ring", "set_infinite_ammo"):
            await self.check_run(ctx)  # reject a handover between the capability read and click
            body = {"op": op, "request_id": args["request_id"]}
            if op == "equip_primary":
                body["args"] = {"item": args["item"]}
            if op == "grenade_ring":
                body["args"] = {"kind": args.get("kind", "flash")}
            if op == "set_infinite_ammo":
                body["args"] = {"enabled": args["enabled"]}
            out = await self.post(f"/api/sessions/{quote(sid, safe='')}/interventions", body)
            row = out["request"]
            result["action"] = {"state": row["state"], "request": row}
            return result
        if not ctx["controls_title"]:
            if op == "set":
                raise ValueError(result["reason"])
            return result
        pending = None
        if args.get("job_id"):
            pending = self.consume(ctx, await self.get("/api/jobs/" + quote(args["job_id"], safe="")))
        # Opening/refreshing reuses a recent read, while receipt polls never create another read job.
        outstanding = next((jid for jid, p in self.pending.items() if p["session_id"] == sid), None)
        if not pending and outstanding:
            pending = self.consume(ctx, await self.get("/api/jobs/" + quote(outstanding, safe="")))
        old = self.cache.get(sid)
        if not pending and (not old or op == "status" and not args.get("job_id") and self.clock() - old["at"] > 3):
            pending = self.consume(ctx, await self.job(ctx, {"op": "live_controls"}))
        old = self.cache.get(sid, {})
        result["controls"] = control_inventory(ctx["controls_title"], old.get("view", {}), old.get("status", {}))
        if pending:
            if op == "set":
                raise ValueError("A control change is still running. Wait for its receipt before changing more settings.")
            result["pending_job"] = pending
            return result
        if op == "set":
            control = next((c for c in result["controls"] if c["id"] == args["control"]), None)
            if not control:
                raise ValueError("Unknown live control for this game.")
            inp = change_input(control, args["value"])
            await self.check_run(ctx)
            action = {"control": control["id"], "value": args["value"]}
            job = await self.job(ctx, inp, action)
            pending = self.consume(ctx, job)
            result["action"] = {"state": "pending" if pending else "confirmed", "job_id": job["id"]}
            if pending:
                result["pending_job"] = pending
            old = self.cache.get(sid, {})
            result["controls"] = control_inventory(ctx["controls_title"], old.get("view", {}), old.get("status", {}))
        # Protect even a successful late response from painting the next title's session.
        await self.check_run(ctx)
        return result


async def call_mcp(config, arguments):
    """The facade exercises the same authenticated MCP transport as external clients."""
    import httpx2
    from mcp.client import Client
    from mcp.client.streamable_http import streamable_http_client
    url = f"http://127.0.0.1:{config.api_port + 1}/mcp"
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + config.token()}, timeout=15) as http:
        async with Client(streamable_http_client(url, http_client=http), read_timeout_seconds=15) as client:
            reply = await client.call_tool("game_live_controls", arguments)
    text = "".join(block.text for block in reply.content if getattr(block, "type", "") == "text")
    data = json.loads(text)
    if reply.is_error:
        raise ValueError(data.get("error", "The live control request failed."))
    return data


def install(app, config):
    from fastapi import Depends, HTTPException, Request

    def service_auth(request: Request):
        got = request.headers.get("authorization", "")
        expected = "Bearer " + config.token()
        if not hmac.compare_digest(got.encode(), expected.encode()):
            raise HTTPException(401, "live controls require the service bearer header")

    async def invoke(arguments):
        try:
            validate_request(arguments)
            return await call_mcp(config, arguments)
        except ValueError as exc:
            raise HTTPException(409, str(exc)[:400]) from None
        except Exception:
            # No endpoint/token/transport details in a browser-facing failure.
            raise HTTPException(503, "The gBox live-control MCP service is unavailable. Try again shortly.") from None

    @app.get("/api/sessions/{sid}/live-controls", dependencies=[Depends(service_auth)])
    async def status(sid: str, job_id: str | None = None):
        return await invoke({"session_id": sid, "op": "status", **({"job_id": job_id} if job_id else {})})

    @app.post("/api/sessions/{sid}/live-controls", dependencies=[Depends(service_auth)])
    async def action(sid: str, body: dict):
        if "session_id" in body or body.get("op") == "status":
            raise HTTPException(422, "Use the selected session URL and GET for status.")
        return await invoke({"session_id": sid, **body})


def main():
    """Companion activation avoids reloading the core while games are on air."""
    import argparse
    import os
    from pathlib import Path
    from fastapi import FastAPI
    import uvicorn
    from .config import load
    parser = argparse.ArgumentParser(description='gBox bounded MCP live controls')
    parser.add_argument('--config', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    if not Path(args.config).is_file():
        parser.error('Use the existing gBox deployment configuration.')
    config = load(args.config)
    if not os.environ.get('GBOX_TOKEN') and not (config.data_dir / 'api_token').is_file():
        parser.error('The existing gBox service credential is required.')
    app = FastAPI(title='gBox live controls', docs_url=None, redoc_url=None, openapi_url=None)
    install(app, config)
    uvicorn.run(app, host=args.host, port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
