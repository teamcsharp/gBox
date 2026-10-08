"""MCP server: drive gBox from Claude Desktop / Claude Code / other agents.

Every registry tool is exposed as job_<name> (runs as a gBox job, returns its output), plus conveniences
(library, launch, sessions, memory peek, the gBox chat agent, KB, recipes) and two resources.
stdio by default; serve_http() puts the same server on streamable HTTP behind the control plane's bearer token.
"""
import asyncio
import hmac
import json
import time

import httpx
import mcp_types as T
from mcp.server.lowlevel import Server

S, I, B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
ADDR = {"type": ["string", "integer"], "description": "hex string (0x80001234) or integer"}
PREFIX = "job_"                                   # registry tools; unprefixed names are the conveniences below


def obj(props, req=()):
    return {"type": "object", "properties": props, "required": list(req)}


CONVENIENCE = {
    "list_games": ("Search the game library (title words). Returns game_id, title, platform, system, core.",
                   obj({"query": S, "platform": S, "limit": I}, ["query"])),
    "launch_game": ("Launch a library game. node: auto | windows | linux | <worker name>. debug=true runs it on the Spark "
                    "under a full-debugger emulator. Returns the launch job (its output has the session_id).",
                    obj({"game_id": S, "node": S, "debug": B}, ["game_id"])),
    "list_sessions": ("Game sessions (session_id, title, adapter, state, last_frame_age). Live ones only unless include_ended.",
                      obj({"include_ended": B})),
    "read_memory": ("Read live emulator memory of a running session (hex dump). Native addresses work "
                    "(0x8C000000 Dreamcast, 0x80000000 N64/GameCube).", obj({"session_id": S, "address": ADDR, "length": I},
                                                                             ["session_id", "address"])),
    "ask_gbox": ("Hand a natural-language request to gBox's own agent (it can launch, mod, cheat, search memory, read the KB). "
                 "session_id gives it the live game; chat_id continues a conversation. Returns its final answer and tool calls.",
                 obj({"text": S, "session_id": S, "chat_id": S, "timeout_s": I}, ["text"])),
    "kb_search": ("Search gBox's knowledge base (wiki pages, learned facts, memory maps), optionally scoped to a game title.",
                  obj({"query": S, "game": S, "k": I}, ["query"])),
    "list_recipes": ("Learned tool recipes: verified step sequences gBox's agent saved and can replay.", obj({})),
}
RESOURCES = {"gbox://sessions": ("sessions", "Live game sessions"), "gbox://games": ("games", "Game library (first 500 + total)")}


def build(base_url: str, token: str) -> Server:
    api = httpx.AsyncClient(base_url=base_url, headers={"authorization": f"Bearer {token}", "x-gbox-actor": "mcp"}, timeout=60)
    registry: dict[str, dict] = {}

    async def get(path, **params):
        r = await api.get(path, params=params)
        r.raise_for_status()
        return r.json()

    async def post(path, body=None, **params):
        r = await api.post(path, json=body, params=params)
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code}: {r.text[:500]}")
        return r.json()

    async def wait_job(job, timeout):
        t0 = time.time()
        while job.get("state") in ("queued", "running") and time.time() - t0 < timeout:
            await asyncio.sleep(1)
            job = await get(f"/api/jobs/{job['id']}")
        return {k: job.get(k) for k in ("id", "tool", "state", "worker_id", "output", "error")}

    async def sessions(include_ended=False):
        return [s for s in await get("/api/sessions") if include_ended or not s.get("ended")]

    async def ask(text, session_id="", chat_id="", timeout_s=600):
        cid = chat_id or (await post("/api/chat"))["id"]
        start = (await get(f"/api/chat/{cid}", after=0))["count"]
        await post(f"/api/chat/{cid}/messages", {"text": text, "context": {"session_id": session_id} if session_id else {}})
        t0 = time.time()
        while (c := await get(f"/api/chat/{cid}", after=start))["busy"] and time.time() - t0 < timeout_s:
            await asyncio.sleep(1.5)
        ev = c["events"]
        calls = [{"name": e["name"], "args": e.get("args")} for e in ev if e["type"] == "tool_call"]
        results = [e.get("text", "") for e in ev if e["type"] == "tool_result"]   # emitted in call order
        for c_, r in zip(calls, results):
            c_["result"] = r[:2000]
        answers = [e["text"] for e in ev if e["type"] == "assistant"]
        return {"chat_id": cid, "busy": c["busy"], "answer": answers[-1] if answers else None, "tool_calls": calls,
                "errors": [e["text"] for e in ev if e["type"] == "error"],
                "choices": [{"question": e["question"], "options": e["options"]} for e in ev if e["type"] == "choices"]}

    async def convenience(name, a):
        if name == "list_games":
            games = await get("/api/catalog/best", q=a["query"], limit=a.get("limit", 20))
            if a.get("platform"):
                games = [g for g in games if g.get("platform") == a["platform"]]
            return [{k: g.get(k) for k in ("game_id", "title", "platform", "system", "core", "playable")} for g in games]
        if name == "launch_game":
            job = await post(f"/api/games/{a['game_id']}/launch", node=a.get("node", "auto"), debug=str(a.get("debug", False)).lower())
            return await wait_job(job, 300)
        if name == "list_sessions":
            return await sessions(a.get("include_ended", False))
        if name == "read_memory":
            addr = a["address"] if isinstance(a["address"], int) else int(str(a["address"]), 0)
            h = await post(f"/api/sessions/{a['session_id']}/rpc", {"op": "read_memory",
                                                                    "args": {"address": addr, "length": max(1, min(int(a.get("length", 64)), 4096))}})
            return {"address": hex(addr), "hex": " ".join(h[i:i + 2] for i in range(0, len(h), 2)).upper()}
        if name == "ask_gbox":
            return await ask(a["text"], a.get("session_id", ""), a.get("chat_id", ""), a.get("timeout_s", 600))
        if name == "kb_search":
            return await get("/api/kb/search", q=a["query"], game=a.get("game", ""), k=a.get("k", 6))
        if name == "list_recipes":
            return await get("/api/recipes")

    async def list_tools(ctx, params):
        registry.clear()
        registry.update({t["name"]: t for t in (await get("/api/registry"))["tools"]})
        tools = [T.Tool(name=n, description=d, input_schema=s) for n, (d, s) in CONVENIENCE.items()]
        for t in registry.values():
            schema = dict(t.get("input_schema") or obj({"input": {"type": "object"}}))
            if t["name"].startswith("rea_"):
                # A transport envelope preserves strict/union upstream schemas;
                # routing fields must not be injected into their input contract.
                schema = obj({"input": schema}, ["input"])
            schema["properties"] = schema.get("properties", {}) | {
                "require_os": {"type": "string", "enum": ["windows", "linux"]},
                "require_worker": {"type": "string", "description": "Pin stateful analysis to the worker_id returned by its first job."},
                "parent_request_id": {"type": "string", "description": "Attribute automated work to its original operator request."}}
            workers = ", ".join(t.get("workers") or []) or "no online worker"
            tools.append(T.Tool(name=PREFIX + t["name"], input_schema=schema,
                                description=f"{t['description']} [gBox job; workers: {workers}; session_id routes it to that session's worker]"))
        return T.ListToolsResult(tools=tools)

    async def call_tool(ctx, params):
        name, a = params.name, dict(params.arguments or {})
        try:
            if name in CONVENIENCE:
                out, ok = await convenience(name, a), True
            elif name.startswith(PREFIX):
                tool = name[len(PREFIX):]
                if not registry:
                    await list_tools(ctx, None)
                info = registry.get(tool) or {}
                ros = a.pop("require_os", None)
                worker = a.pop("require_worker", None)
                parent = a.pop("parent_request_id", None)
                generic = tool.startswith("rea_") or not (info.get("input_schema") or {}).get("properties")
                body = {"tool": tool, "input": a.get("input", {}) if generic else a}
                if ros:
                    body["require_os"] = ros
                if worker:
                    body["require_worker"] = worker
                if parent:
                    body["parent_request_id"] = parent
                if sid := body["input"].get("session_id"):     # sessions live on the worker that launched them
                    body["require_worker"] = sid.split("-")[0]
                out = await wait_job(await post("/api/jobs", body), (info.get("timeout_s") or 300) + 60)
                ok = out["state"] == "succeeded"
            else:
                raise ValueError(f"unknown tool {name}")
        except Exception as e:
            out, ok = {"error": f"{type(e).__name__}: {e}"}, False
        text = json.dumps(out, indent=1, default=str)
        return T.CallToolResult(content=[T.TextContent(text=text[:200_000])], is_error=not ok)

    async def list_resources(ctx, params):
        return T.ListResourcesResult(resources=[T.Resource(uri=u, name=n, description=d, mime_type="application/json")
                                                for u, (n, d) in RESOURCES.items()])

    async def read_resource(ctx, params):
        u = str(params.uri)
        data = await sessions() if u == "gbox://sessions" else await get("/api/catalog", limit=500) if u == "gbox://games" else None
        if data is None:
            raise ValueError(f"unknown resource {u}")
        return T.ReadResourceResult(contents=[T.TextResourceContents(uri=u, mime_type="application/json", text=json.dumps(data, default=str))])

    return Server("gbox", version="0.1.0", instructions="gBox game laboratory: library, launches, live sessions, memory, mods, "
                  "and its own agent (ask_gbox). Registry tools are job_<name>.",
                  on_list_tools=list_tools, on_call_tool=call_tool, on_list_resources=list_resources, on_read_resource=read_resource)


def serve_stdio(base_url: str, token: str):
    from mcp.server.stdio import stdio_server
    srv = build(base_url, token)

    async def main():
        async with stdio_server() as (r, w):
            await srv.run(r, w, srv.create_initialization_options())
    asyncio.run(main())


def serve_http(base_url: str, token: str, host: str, port: int):
    """Streamable HTTP at http://host:port/mcp; same bearer token as the control plane."""
    import uvicorn
    app = build(base_url, token).streamable_http_app(host=host)

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            got = dict(scope["headers"]).get(b"authorization", b"").decode().removeprefix("Bearer ")
            if not hmac.compare_digest(got.encode(), token.encode()):
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"bad token"})
                return
        await app(scope, receive, send)
    uvicorn.run(guarded, host=host, port=port, log_level="warning")
