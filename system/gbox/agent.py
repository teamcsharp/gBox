"""G-Box chat agent: a local LLM (Spark Ollama, OpenAI-compatible tool calling) that operates G-Box for the operator.

The agent never touches internals directly: every action goes through G-Box's own authenticated API (jobs with receipts,
session RPC, clipboard), so it is audited exactly like the operator's clicks. Web research uses the Spark's SearXNG.
"""
import base64
import html
import json
import re
import struct
import threading
import time
import zlib

import httpx

from .models import new_id

SYSTEM = """You are G-Box, an assistant that operates a game laboratory for its operator (who owns these games) in real time.
You can search the web, find and launch games, inspect and edit live emulator memory, extract sprites/tiles to Blender,
and run Ghidra analyses. Use tools; don't guess facts you can look up or measure.

How to work:
- Understand the request in the operator's words. If it's about a specific game, use the session context or search_games.
- Cheats like "infinite lives/health/money": web_search for the game's GameShark/Action Replay/Pro Action Replay codes or a RAM map,
  convert the code to an address (e.g. N64/GameCube GameShark 80XXXXXX YY = 8-bit write of YY at 0x80XXXXXX, 81XXXXXX YYYY = 16-bit;
  NES Game Genie needs decoding, Pro Action Replay 7EXXXXYY = SNES WRAM 0x7EXXXX), read_memory there to sanity-check the current value,
  then freeze_memory to hold it. If no code is found, use memory_snapshot + memory_filter (e.g. lives: snapshot, lose a life, filter "dec",
  then "eq" with the shown value) and freeze the surviving address. Tell the operator what you changed and how to undo it.
- Sprites/graphics: extract_tiles from the ROM (cartridge systems) with the right format (nes, gb, snes, md, lin8, one); it lands on the
  G-Box clipboard so the operator presses Ctrl+Shift+V in Blender. Try several offsets/formats if the first looks like noise.
- Reverse engineering: ghidra_scripts to find a script, run_tool("ghidra_script"/"analyze_binary", ...) to run it.
- "Put me on <stage/world/level>", "play as <character>", "skip to <boss>": DO IT, don't explain how the operator could.
  Playbook, in order, until it works: (1) web_search the game's RAM map / level-select or debug code / "level ID list"
  (datacrystal.tcrf.net, tcrf.net, smwcentral.net, gamehacking.org, speedrun wikis), web_fetch the page for exact addresses and IDs;
  (2) read_memory those addresses to confirm the live values match (current level/world/character); (3) write_memory the target
  level/world/character ID (plus any "unlocked/cleared" flags and the transition/load trigger, e.g. set the level number and force
  a level reload or death/exit); freeze_memory if the game keeps overwriting it; (4) look_at_screen to verify you got there;
  (5) if no map exists, find it yourself: memory_snapshot, have the operator (or you via the level change) move, memory_filter chg/same,
  or run_tool ghidra_script/analyze_binary on the ROM to find the level-load routine and its table, or patch a debug/level-select
  code from a GameShark/Game Genie/Action Replay list. Keep trying alternatives; only stop after verifying on screen.
- Whenever you need the operator to pick or clarify something (which game, which approach, which option), call ask_user with
  2-6 short concrete options instead of writing a numbered list; the operator clicks one. Don't ask when a sensible default exists.
- Be concise. Report what you actually did and observed (addresses, values, job ids), never claim success you didn't verify."""


def _png(width: int, height: int, rgba: bytes) -> bytes:
    raw = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


# tile decoders: bytes/tile, colours, decode(bytes, offset) -> 64 palette indices (same formats as the Inspect view)
def _bits(b, o, rows):
    return [((b[o + rows(y)[0]] >> (7 - x)) & 1) | (((b[o + rows(y)[1]] >> (7 - x)) & 1) << 1) for y in range(8) for x in range(8)]

TILE = {
    "nes": (16, 4, lambda b, o: _bits(b, o, lambda y: (y, y + 8))),
    "gb": (16, 4, lambda b, o: _bits(b, o, lambda y: (2 * y, 2 * y + 1))),
    "snes": (32, 16, lambda b, o: [p | (q << 2) for p, q in zip(_bits(b, o, lambda y: (2 * y, 2 * y + 1)), _bits(b, o + 16, lambda y: (2 * y, 2 * y + 1)))]),
    "md": (32, 16, lambda b, o: [v for i in range(32) for v in (b[o + i] >> 4, b[o + i] & 15)]),
    "lin8": (64, 256, lambda b, o: list(b[o:o + 64])),
    "one": (8, 2, lambda b, o: [(b[o + y] >> (7 - x)) & 1 for y in range(8) for x in range(8)]),
}


def tiles_png(data: bytes, fmt: str, count: int, cols: int = 16, scale: int = 1) -> bytes:
    per, ncol, dec = TILE[fmt]
    count = min(count, len(data) // per)
    rows = max(1, (count + cols - 1) // cols)
    w, h = cols * 8, rows * 8
    px = bytearray(w * h * 4)
    for t in range(count):
        tx, ty = (t % cols) * 8, (t // cols) * 8
        for i, v in enumerate(dec(data, t * per)):
            g = v if ncol == 256 else round(v * 255 / (ncol - 1))
            o = ((ty + i // 8) * w + tx + i % 8) * 4
            px[o:o + 4] = bytes((g, g, g, 255 if v else 0))            # colour 0 transparent (sprite background)
    if scale > 1:
        big = bytearray(w * scale * h * scale * 4)
        for y in range(h * scale):
            for x in range(w * scale):
                s = ((y // scale) * w + x // scale) * 4
                d = (y * w * scale + x) * 4
                big[d:d + 4] = px[s:s + 4]
        px, w, h = big, w * scale, h * scale
    return _png(w, h, bytes(px))


def tool_specs() -> list[dict]:
    def fn(name, desc, props, req=()):
        return {"type": "function", "function": {"name": name, "description": desc,
                "parameters": {"type": "object", "properties": props, "required": list(req)}}}
    s, i, b = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
    return [
        fn("web_search", "Search the web (SearXNG). Use for cheat codes, RAM maps, game facts, tool docs.", {"query": s, "n": i}, ["query"]),
        fn("web_fetch", "Fetch a web page as plain text (first ~6000 chars).", {"url": s}, ["url"]),
        fn("search_games", "Search the G-Box library (63k games).", {"query": s, "platform": s}, ["query"]),
        fn("launch_game", "Launch a game. where='local' runs natively on the operator's PC (default), 'spark' streams from the DGX Spark.",
           {"game_id": s, "where": s}, ["game_id"]),
        fn("list_sessions", "List running game sessions.", {}),
        fn("session_info", "Platform, core, ROM and runtime state of a running session.", {"session_id": s}, ["session_id"]),
        fn("read_memory", "Read live emulator memory (hex). Native addresses work (e.g. 0x8C000000 Dreamcast, 0x80000000 N64/GameCube).",
           {"session_id": s, "address": s, "length": i}, ["session_id", "address"]),
        fn("write_memory", "Write bytes once (audited, previous value kept for rollback).", {"session_id": s, "address": s, "hex_bytes": s},
           ["session_id", "address", "hex_bytes"]),
        fn("freeze_memory", "Hold bytes at an address (infinite lives/health...). enabled=false releases it.",
           {"session_id": s, "address": s, "hex_bytes": s, "enabled": b}, ["session_id", "address", "hex_bytes"]),
        fn("memory_snapshot", "Snapshot a RAM range for a cheat search (span <= 1 MiB).", {"session_id": s, "base": s, "span": i}, ["session_id"]),
        fn("memory_filter", "Filter the last snapshot's candidates vs memory now: op eq|neq|chg|same|inc|dec, value hex for eq/neq.",
           {"session_id": s, "op": s, "value": s}, ["session_id", "op"]),
        fn("extract_tiles", "Decode tiles/sprites from the ROM (source=rom) or RAM and put a PNG on the G-Box clipboard for Blender.",
           {"session_id": s, "source": s, "offset": s, "format": s, "count": i}, ["session_id", "offset", "format"]),
        fn("look_at_screen", "Capture the game screen and describe it with a vision model (what's on screen, menus, HUD values).",
           {"session_id": s, "question": s}, ["session_id"]),
        fn("ask_user", "Ask the operator a multiple-choice question; they click an option (their answer arrives as the next message). Ends your turn.",
           {"question": s, "options": {"type": "array", "items": s}}, ["question", "options"]),
        fn("ghidra_scripts", "Search the installed Ghidra scripts (311) by keyword.", {"query": s}, ["query"]),
        fn("run_tool", "Run any G-Box typed tool as an audited job, e.g. ghidra_script, analyze_binary, get_frame, hash_game.",
           {"name": s, "input": {"type": "object"}}, ["name", "input"]),
    ]


class Agent:
    def __init__(self, api_base: str, token: str, llm_url: str, model: str, searx_url: str, vision_model: str | None = None):
        self.api = httpx.Client(base_url=api_base, headers={"authorization": f"Bearer {token}", "x-gbox-actor": "gbox-agent"}, timeout=120)
        self.llm_url, self.model, self.searx, self.vision = llm_url.rstrip("/"), model, searx_url.rstrip("/"), vision_model
        self.snapshots: dict[str, dict] = {}
        self.game: str | None = None                           # title of the live game; pins web searches to it

    # --- tool implementations (all through the public API) ---
    def _job(self, tool, inp, node=None, limit=900):
        body = {"tool": tool, "input": inp}
        if node:
            body["require_os"] = node
        j = self.api.post("/api/jobs", json=body).json()
        t = time.time()
        while j.get("state") in ("queued", "running") and time.time() - t < limit:
            time.sleep(0.7)
            j = self.api.get(f"/api/jobs/{j['id']}").json()
        return j

    def _rpc(self, sid, op, args=None):
        r = self.api.post(f"/api/sessions/{sid}/rpc", json={"op": op, "args": args or {}}, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(r.text[:300])
        return r.json()

    @staticmethod
    def _addr(a) -> int:
        return int(str(a), 16) if isinstance(a, str) and not str(a).isdigit() else int(a)

    def web_search(self, query, n=5):
        if self.game and not all(w in query.lower() for w in self.game.lower().split()[:4]):
            query = f'"{self.game}" {query}'                    # small models drift to other games; keep searches on the live one
        r = httpx.get(f"{self.searx}/search", params={"q": query, "format": "json", "categories": "general",
                                                       "safesearch": 1, "language": "en"}, timeout=30).json()
        return [{"title": x.get("title"), "url": x.get("url"), "snippet": (x.get("content") or "")[:300]} for x in r.get("results", [])[:max(1, min(n, 10))]]

    def web_fetch(self, url):
        r = httpx.get(url, timeout=30, follow_redirects=True, headers={"user-agent": "Mozilla/5.0 G-Box"})
        t = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", r.text)
        t = html.unescape(re.sub(r"<[^>]+>", " ", t))
        return re.sub(r"\s+", " ", t).strip()[:6000]

    def search_games(self, query, platform=""):
        items = self.api.get("/api/catalog/best", params={"q": query, "limit": 12}).json()
        if platform:
            items = [g for g in items if g.get("platform") == platform] or items
        return {"best_first": True, "games": [{k: g.get(k) for k in ("game_id", "title", "system", "platform", "core", "year")} for g in items[:10]]}

    def launch_game(self, game_id, where="local"):
        node = {"spark": "linux", "local": self.local_worker or "auto"}.get(where, where)
        r = self.api.post(f"/api/games/{game_id}/launch", params={"node": node}).json()
        t = time.time()
        while r.get("state") in ("queued", "running") and time.time() - t < 900:
            time.sleep(1)
            r = self.api.get(f"/api/jobs/{r['id']}").json()
        if r["state"] != "succeeded":
            return {"error": r.get("error"), "state": r["state"]}
        g = self.api.get(f"/api/catalog/{game_id}").json()
        self.launched = getattr(self, "launched", []) + [(game_id, g.get("title"))]
        return {"session_id": r["output"]["session_id"], "adapter": r["output"]["adapter"], "native_window": r["output"]["detail"].get("local_window")}

    def list_sessions(self):
        return [{k: s.get(k) for k in ("session_id", "title", "adapter")} for s in self.api.get("/api/sessions").json() if s.get("state") == "running"]

    def session_info(self, session_id):
        return self._rpc(session_id, "info")

    def read_memory(self, session_id, address, length=64):
        a = self._addr(address)
        h = self._rpc(session_id, "read_memory", {"address": a, "length": max(1, min(int(length), 512))})
        b = bytes.fromhex(h)
        return {"address": hex(a), "hex": " ".join(f"{x:02X}" for x in b)}

    def write_memory(self, session_id, address, hex_bytes):
        j = self._job("write_memory", {"session_id": session_id, "address": self._addr(address), "hex_bytes": hex_bytes.replace(" ", "")})
        return {"state": j["state"], "error": j.get("error"), "result": (j.get("output") or {}).get("result"), "receipt": j.get("receipt_id")}

    def freeze_memory(self, session_id, address, hex_bytes, enabled=True):
        j = self._job("freeze_memory", {"session_id": session_id, "address": self._addr(address), "hex_bytes": hex_bytes.replace(" ", ""),
                                        "enabled": enabled})
        return {"state": j["state"], "error": j.get("error"), "result": j.get("output"), "receipt": j.get("receipt_id")}

    def _read_span(self, sid, base, span):
        out = bytearray()
        for o in range(0, span, 65536):
            out += bytes.fromhex(self._rpc(sid, "read_memory", {"address": base + o, "length": min(65536, span - o)}))
        return bytes(out)

    def memory_snapshot(self, session_id, base="0", span=65536):
        base, span = self._addr(base), max(16, min(int(span), 1 << 20))
        self.snapshots[session_id] = {"base": base, "data": self._read_span(session_id, base, span), "cands": None}
        return {"base": hex(base), "span": span, "note": "now change the value in-game, then memory_filter"}

    def memory_filter(self, session_id, op, value=None):
        snap = self.snapshots.get(session_id)
        if not snap:
            return {"error": "take a memory_snapshot first"}
        now = self._read_span(session_id, snap["base"], len(snap["data"]))
        v = int(value, 16) if value not in (None, "") else None
        test = {"eq": lambda a, b: b == v, "neq": lambda a, b: b != v, "chg": lambda a, b: a != b, "same": lambda a, b: a == b,
                "inc": lambda a, b: b > a, "dec": lambda a, b: b < a}[op]
        pool = snap["cands"] if snap["cands"] is not None else range(len(now))
        snap["cands"] = [i for i in pool if test(snap["data"][i], now[i])]
        snap["data"] = now
        return {"candidates": len(snap["cands"]),
                "first": [{"address": hex(snap["base"] + i), "value": f"{now[i]:02X}"} for i in snap["cands"][:30]]}

    def extract_tiles(self, session_id, offset, format, source="rom", count=256):
        if format not in TILE:
            return {"error": f"format must be one of {list(TILE)}"}
        per = TILE[format][0]
        n = max(1, min(int(count), 1024))
        off = self._addr(offset)
        if source == "rom":
            data = bytes.fromhex(self._rpc(session_id, "read_rom", {"offset": off, "length": per * n})["hex"])
        else:
            data = self._read_span(session_id, off, per * n)
        png = tiles_png(data, format, n, scale=1)
        item = self.api.post("/api/clipboard", json={"kind": "image", "name": f"tiles_{source}_{off:X}_{format}",
                                                     "b64": base64.b64encode(png).decode(),
                                                     "meta": {"session": session_id, "source": source, "offset": off, "format": format}}).json()
        return {"tiles": len(data) // per, "png_bytes": len(png), "clipboard_seq": item.get("seq"), "artifact": item.get("sha256"),
                "next": "Operator: Ctrl+Shift+V in Blender pastes it."}

    def look_at_screen(self, session_id, question="Describe what is on screen."):
        j = self._job("get_frame", {"session_id": session_id})
        if j["state"] != "succeeded":
            return {"error": j.get("error") or "frame capture failed (native local windows can't be captured yet)"}
        sha = self.api.get(f"/api/receipts/{j['receipt_id']}").json()["artifacts"][0]["sha256"]
        png = self.api.get(f"/api/artifacts/{sha}").content
        if not self.vision:
            return {"frame": sha, "mean_luma": j["output"].get("mean_luma")}
        r = httpx.post(f"{self.llm_url}/chat/completions", timeout=300, json={"model": self.vision, "messages": [{"role": "user", "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}]}).json()
        return {"frame": sha, "description": r["choices"][0]["message"]["content"][:2000]}

    def ghidra_scripts(self, query):
        q = query.lower()
        ss = self.api.get("/api/registry", timeout=120).json()["ghidra"]["scripts"]
        return [{k: x[k] for k in ("name", "category", "description")} for x in ss if q in (x["name"] + x["category"] + x["description"]).lower()][:25]

    def run_tool(self, name, input):
        j = self._job(name, input)
        return {"state": j["state"], "error": j.get("error"), "output": j.get("output"), "receipt": j.get("receipt_id")}

    # --- conversation loop ---
    def run(self, messages: list[dict], emit, context: dict, max_steps: int = 40) -> dict:
        """messages: OpenAI-style history (mutated). emit(event) streams steps to the UI. Returns usage totals."""
        self.local_worker = context.get("local_worker")
        tools, usage, used = tool_specs(), {"in": 0, "out": 0}, {}
        if context.get("voice"):
            messages.append({"role": "system", "content": "Voice conversation: answer in 1-3 short spoken sentences, no markdown, "
                             "no lists or addresses read aloud unless asked; the sidebar shows tool details and images."})
        self.game = None
        if sid := context.get("session_id"):                   # full live-game context: title, platform, core, ROM, runtime
            try:
                info = self.session_info(sid)
            except Exception as e:
                info = {"title": context.get("game_title"), "error": str(e)}
            self.game = re.sub(r"\s*[\(\[].*?[\)\]]", "", info.get("title") or context.get("game_title") or "").strip() or None
            messages.append({"role": "system", "content": f"LIVE GAME (session_id={sid}) - the operator means this game unless they name "
                             f"another: {json.dumps(info, default=str)[:2500]}. Every web_search must name '{self.game}' and its platform. "
                             "Use read_memory / look_at_screen on this session for current state, read_rom/run_tool for the ROM itself."})
        for _ in range(max_steps):
            r = httpx.post(f"{self.llm_url}/chat/completions", timeout=600,
                           json={"model": self.model, "messages": messages, "tools": tools, "temperature": 0.2}).json()
            if "choices" not in r:
                raise RuntimeError(f"LLM error: {json.dumps(r)[:300]}")
            u = r.get("usage") or {}
            usage["in"] += u.get("prompt_tokens", 0)
            usage["out"] += u.get("completion_tokens", 0)
            m = r["choices"][0]["message"]
            calls = m.get("tool_calls") or []
            messages.append({"role": "assistant", "content": m.get("content") or "", **({"tool_calls": calls} if calls else {})})
            if not calls:
                emit({"type": "assistant", "text": re.sub(r"(?s)<think>.*?</think>", "", m.get("content") or "").strip()})
                return {"usage": usage, "tools": used}
            for c in calls:
                name = c["function"]["name"]
                if name == "ask_user":                              # questionnaire: show clickable options, wait for the click
                    try:
                        a = json.loads(c["function"].get("arguments") or "{}")
                    except ValueError:
                        a = {}
                    opts = [str(o) for o in a.get("options") or []][:8]
                    emit({"type": "choices", "question": a.get("question", ""), "options": opts})
                    messages.append({"role": "tool", "tool_call_id": c.get("id", name), "content": "asked; the operator's choice is the next message"})
                    return {"usage": usage, "tools": used}
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except ValueError:
                    args = {}
                emit({"type": "tool_call", "name": name, "args": args})
                used[name] = used.get(name, 0) + 1
                try:
                    if name not in {t["function"]["name"] for t in tools}:
                        raise ValueError(f"unknown tool {name}")
                    result = getattr(self, name)(**args)
                except Exception as e:
                    result = {"error": f"{type(e).__name__}: {e}"}
                text = json.dumps(result, default=str)
                emit({"type": "tool_result", "name": name, "text": text[:4000]})
                if isinstance(result, dict):                        # images for the live sidebar
                    for key, cap in (("frame", "screen capture"), ("artifact", "extracted")):
                        if result.get(key):
                            emit({"type": "media", "sha": result[key], "caption": f"{name}: {cap}"})
                messages.append({"role": "tool", "tool_call_id": c.get("id", name), "content": text[:6000]})
        emit({"type": "assistant", "text": "(stopped: step limit reached — ask me to continue)"})
        return {"usage": usage, "tools": used}


class ChatHub:
    """Conversations live on the control plane; each user turn runs the agent in a background thread."""
    def __init__(self, store, make_agent):
        self.store, self.make_agent, self.lock = store, make_agent, threading.Lock()

    def get(self, cid: str) -> dict:
        return self.store.get("chat", cid) or {"id": cid, "events": [], "messages": [{"role": "system", "content": SYSTEM}], "busy": False,
                                               "title": "", "model": None, "games": [], "created": time.time(), "updated": time.time()}

    def list(self) -> list[dict]:
        out = [{k: c.get(k) for k in ("id", "title", "model", "games", "created", "updated", "busy")} | {"turns": sum(e["type"] == "user" for e in c["events"])}
               for c in self.store.all("chat")]
        return sorted(out, key=lambda c: c.get("updated") or 0, reverse=True)

    def _remember_game(self, c: dict, gid: str | None, title: str | None):
        if gid and gid not in [g["game_id"] for g in c["games"]]:
            c["games"].append({"game_id": gid, "title": title or gid})

    def post(self, cid: str, text: str, context: dict, api_requests, model: str | None = None) -> dict:
        with self.lock:
            c = self.get(cid)
            if model:
                c["model"] = model
            c["title"] = c.get("title") or text.splitlines()[0][:80]
            c["updated"] = time.time()
            self._remember_game(c, context.get("game_id"), context.get("game_title"))
            if c["busy"]:
                raise RuntimeError("the agent is still working on the previous request")
            ctx_line = f"\n[context: {json.dumps(context)}]" if context else ""
            c["messages"].append({"role": "user", "content": text + ctx_line})
            c["events"].append({"type": "user", "text": text, "ts": time.time()})
            c["busy"] = True
            self.store.put("chat", cid, c)
        threading.Thread(target=self._turn, args=(cid, text, context, api_requests), daemon=True).start()
        return c

    def _turn(self, cid, text, context, api_requests):
        c, t0 = self.get(cid), time.time()
        req = api_requests("create", {"title": text.splitlines()[0][:100], "body": text, "source": "gbox-chat", "kind": "text", "context": context})

        def emit(ev):
            with self.lock:
                cur = self.get(cid)
                cur["events"].append(ev | {"ts": time.time()})
                self.store.put("chat", cid, cur)
        try:
            agent = self.make_agent(c.get("model"))
            res = agent.run(c["messages"], emit, context)
            launched = [a for a in getattr(agent, "launched", [])]
            status, note = "done", ""
        except Exception as e:
            emit({"type": "error", "text": f"{type(e).__name__}: {e}"})
            res, status, note = {"usage": {"in": 0, "out": 0}, "tools": {}}, "blocked", str(e)
        with self.lock:
            cur = self.get(cid)
            cur["messages"], cur["busy"], cur["updated"] = c["messages"], False, time.time()
            for gid, title in (launched if "launched" in locals() else []):
                self._remember_game(cur, gid, title)
            self.store.put("chat", cid, cur)
        if req:
            api_requests("metrics", {"id": req, "tokens_in": res["usage"]["in"], "tokens_out": res["usage"]["out"],
                                     "tools": res["tools"], "duration_s": round(time.time() - t0, 1)})
            api_requests("status", {"id": req, "status": status, "note": note})
