"""Build notifications: every build a worker finishes (usually the Spark) lands in the header bell tray.

The control plane posts the notification itself when a job ends (POST /api/workers/{id}/result, a job rejected at
submit, a worker that restarted under a running job), so no builder has to remember to call /api/notify:

  * a build    - a job whose result names a mod / build: result.mod, result.build.mod, a result folder under
                 <cache>/mods/<game_id>/<mod>, or a build op (use / match / cast_swap / build / export / stage ...)
                 that succeeded. Kind "build": game, mod, a thumbnail, the launch options of gbox.special_builds
                 ("Play on this PC" first, other PCs, saved moment, the Spark debugger) and a one-line summary
                 ("4/4 slots built · Sonic, Knuckles, Amy, Gamma").
  * a failure  - the same jobs failing (or answering a failure status: unsupported, needs_source, ...). Kind "error"
                 with the reason, the request it belongs to and a retry recipe when one exists.
  * a collect  - characters op=collect: "N characters collected from <game>". Kind "collect".
  * a new build folder the built-mods index finds that no job reported (a writer run outside a job): kind "build".

Launches, frames, session ops, task lists and every other job are not builds and post nothing. Detection reads the
job's input op and result fields, never a list of writers, so new builders are covered.

One notification per job. A pass that queues many jobs (special builds "Rebuild all", a showcase, one request's jobs)
does not flood the tray: jobs queued within SUBMIT_WINDOW of each other, jobs of one parent request, and same-kind
jobs finishing within GROUP_WINDOW of each other share one entry with a count and the list (items).

Thumbnail ("a moment it captured"), best first:
  1. capture  - a frame of the build running: the mod card's in-game shots / thumb (Screenshot after launch, a
                verified boot), a screenshot / capture picture in the build folder, an image artifact of the job named
                like a frame / screenshot / boot capture.
  2. fitting  - the fitting preview images the writer streamed for the replaced characters (gbox.fit_events).
  3. preview  - the build folder's own preview pictures, then the job's image artifacts (preview.png ...).
  4. donor    - the donors' collection previews (/api/characters/{slug}/preview).
  5. boxart   - the game's box art (/api/media/{game_id}/best?w=360).
No game session or emulator is started to take a picture. The tray loads GET /api/notify/{id}/thumb?i=<item>, which
re-resolves (a capture added after the build wins) and redirects to that authenticated picture URL.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

AUTO = "build"                      # notify records this module owns: {"auto": "build"}
BY = "gbox-builds"
SUBMIT_WINDOW = 10.0                # jobs queued this close together are one pass (rebuild all, showcase)
GROUP_WINDOW = 60.0                 # same-kind jobs finishing this close together share an entry
REQUEST_WINDOW = 1800.0             # one parent request's jobs share an entry while it keeps finishing jobs
BATCH_WINDOW = 6 * 3600.0           # a queued-together pass keeps collecting its jobs this long
INDEX_FRESH = 2 * 3600.0            # an index-found build folder notifies only when built this recently
REFRESH_EVERY = 30.0                # GET re-resolves a young entry's thumbnail at most this often
REFRESH_FOR = 1800.0                # ... while it is younger than this
MAX_ITEMS = 60
KEEP = 500                          # notifications kept (oldest pruned)

NOT_BUILD_TOOLS = frozenset({"launch_game", "@launch", "get_frame", "session_op", "session_swap", "scene_capture",
                             "scene_relay", "tasks", "autoplay", "recording", "video", "state_transfer", "stage_warp",
                             "pick", "pick_preview", "llm_complete", "ram_dump"})
NOT_BUILD_OPS = frozenset({"list", "get", "status", "plan", "remove", "delete", "rollback", "verify", "coverage",
                           "environments", "live_use", "overlay", "place", "unplace", "blender", "extract", "add",
                           "load_state", "save_state", "scan", "search", "read", "info", "query", "check"})
BUILD_OPS = frozenset({"use", "match", "cast_swap", "build", "rebuild", "apply", "export", "stage", "bake", "write",
                       "prepare", "swap", "enable", "make", "create", "pack", "patch", "save"})
COLLECT_OPS = frozenset({"collect"})
# with a session_id these ops build a mod; the other build ops change a running game in place (no news)
FILE_BUILD_OPS = frozenset({"use", "match", "cast_swap", "build", "rebuild", "export", "stage", "bake", "prepare", "pack"})
BUILDER_NAME = re.compile(r"(^|_)(mods?|writer|swap|export|modder|build|builder|prepare|patch)($|_)")
FAIL_STATUS = ("failed", "error", "unsupported", "missing", "not_in_collection", "blocked", "reverted", "needs_source",
               "overlay", "needs_")
NO_BUILD_STATUS = frozenset({"ready", "launched", "planned", "empty", "exists", "cached", "unchanged", "skipped",
                             "native", "listed", "removed"})
MODS_DIR = re.compile(r"[/\\]mods[/\\]([^/\\]+)[/\\]([^/\\]+)[/\\]?$")
CAPTURE_NAME = re.compile(r"screen_?shot|capture|in_?game|boot|running|^frame[._-]?\d*\.", re.I)
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")
SOURCES = ("capture", "fitting", "preview", "donor", "boxart")


# ------------------------------------------------------------------------------------------------- reading a job

def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def result_of(job: dict) -> dict:
    """The job's result dict: output.result when the tool wraps it (most do), else the output itself."""
    out = _d(job.get("output"))
    return out["result"] if isinstance(out.get("result"), dict) else out


def mod_of(res: dict) -> tuple[str, str]:
    """(game_id or '', mod) a result names, or ('', '')."""
    for v in (res.get("mod"), _d(res.get("build")).get("mod"), res.get("mod_name"), res.get("built_mod")):
        if _s(v):
            return _s(res.get("game_id")), _s(v)
    for k in ("mod_dir", "dir", "path", "folder"):
        m = MODS_DIR.search(_s(res.get(k)).rstrip("/\\") + "/") if _s(res.get(k)) else None
        if m:
            return m[1], m[2]
    return "", ""


def game_of(job: dict, res: dict) -> str:
    inp = _d(job.get("input"))
    g = inp.get("game")
    for v in (res.get("game_id"), inp.get("game_id"), inp.get("target_game"), _d(g).get("game_id"),
              _d(res.get("game")).get("game_id")):
        if _s(v):
            return _s(v)
    return ""


def status_of(res: dict) -> str:
    return _s(res.get("status")).lower()


def failed_status(res: dict) -> bool:
    st = status_of(res)
    return (any(st.startswith(f) for f in FAIL_STATUS) or res.get("ok") is False
            or (bool(res.get("error")) and not mod_of(res)[1]))


def classify(job: dict) -> str | None:
    """'build' | 'error' | 'collect' | None (not a build, nothing to say)."""
    tool, inp = str(job.get("tool") or ""), _d(job.get("input"))
    op = _s(inp.get("op")).lower()
    state = str(job.get("state") or "")
    if tool in NOT_BUILD_TOOLS or tool.startswith("session") or op in NOT_BUILD_OPS:
        return None
    if inp.get("plan_only"):
        return None
    if state in ("cancelled",) or str(job.get("error") or "").startswith("cancelled by the operator"):
        return None                                          # the operator stopped it: no news
    res = result_of(job)
    if op in COLLECT_OPS or (not op and isinstance(res.get("collected"), int) and isinstance(res.get("total"), int)):
        if state == "succeeded" and not failed_status(res):
            return "collect"
        return "error" if state in ("succeeded", "failed", "invalid", "rejected") else None
    attempt = op in BUILD_OPS or (not op and bool(BUILDER_NAME.search(tool)))
    if inp.get("session_id") and op not in FILE_BUILD_OPS:
        attempt = False                                      # a live change to a running game, not a build
    names = bool(mod_of(res)[1])
    if state == "succeeded":
        if failed_status(res):
            return "error" if (attempt or names) else None
        if status_of(res) in NO_BUILD_STATUS:
            return None
        return "build" if names or (attempt and res and not inp.get("session_id")) else None
    if state in ("failed", "invalid", "rejected"):
        return "error" if attempt else None
    return None


def _label_of_char(v) -> str:
    return _s(v.get("donor") or v.get("character") or v.get("name")) if isinstance(v, dict) else _s(v)


def summary_of(job: dict, res: dict, kind: str) -> str:
    """One line: '4/4 slots built · Sonic, Knuckles, Amy, Gamma', 'Kane → player', '12 characters collected' ..."""
    inp = _d(job.get("input"))
    if kind == "collect":
        n, total = res.get("collected"), res.get("total")
        names = [_s(e.get("name") or e.get("slug")) for e in res.get("entries") or [] if isinstance(e, dict)
                 and (e.get("verified") or e.get("status") not in ("failed",))]
        head = (f"{n}/{total} collected" if isinstance(total, int) and n != total else f"{n} collected") \
            if isinstance(n, int) else "collected"
        return head + (" · " + ", ".join(x for x in names[:6] if x) + (" …" if len(names) > 6 else "") if names else "")
    if kind == "error":
        why = _s(job.get("error")) or _s(res.get("message")) or _s(res.get("reason")) or _s(res.get("error")) \
            or status_of(res) or "the build did not finish"
        return why[:400]
    rows = [r for r in res.get("report") or [] if isinstance(r, dict) and r.get("status") != "skipped"]
    if rows:                                                 # a cast build: the per-slot report
        built = [r for r in rows if r.get("status") == "built"]
        other = {}
        for r in rows:
            if r.get("status") != "built":
                other[str(r.get("status") or "?")] = other.get(str(r.get("status") or "?"), 0) + 1
        names = [_label_of_char(r) for r in built if _label_of_char(r)]
        text = f"{len(built)}/{len(rows)} slots built" + "".join(f", {v} {k}" for k, v in sorted(other.items()))
        return text + (" · " + ", ".join(names[:8]) + (" …" if len(names) > 8 else "") if names else "")
    who = _s(res.get("character")) or _s(inp.get("character"))
    pairs = [p for p in inp.get("pairs") or [] if isinstance(p, dict) and p.get("character")]
    if pairs:
        return ", ".join(f"{p['character']} → {p.get('slot') or '?'}" for p in pairs[:6])[:300]
    if who:
        slot = _s(res.get("slot")) or _s(inp.get("slot")) or "player"
        return f"{who} → {slot}"
    msg = _s(res.get("message")) or _s(res.get("note"))
    if msg:
        return msg[:300]
    files = res.get("files")
    if isinstance(files, (list, dict)) and files:
        return f"{len(files)} file{'s' if len(files) != 1 else ''} changed"
    return f"built by {job.get('tool')}" + (f" {inp.get('op')}" if inp.get("op") else "")


def donors_of(job: dict, res: dict) -> list[str]:
    """Collection slugs the build put in (cast rows, use's character, pairs, assignments)."""
    inp, out = _d(job.get("input")), []
    for r in res.get("report") or []:
        if isinstance(r, dict) and r.get("status") in ("built", "partial") and _s(r.get("character")):
            out.append(_s(r["character"]))
    for v in (res.get("slug"), inp.get("character")):
        if _s(v):
            out.append(_s(v))
    for k in ("pairs", "assignments"):
        for p in inp.get(k) or []:
            if isinstance(p, dict) and _s(p.get("character")):
                out.append(_s(p["character"]))
    if isinstance(res.get("entries"), list):                 # collect: the characters that came out
        out += [_s(e.get("slug")) for e in res["entries"] if isinstance(e, dict) and e.get("verified") and _s(e.get("slug"))]
    seen, uniq = set(), []
    for s in out:
        if s not in seen and "/" not in s and "\\" not in s and s not in (".", ".."):
            seen.add(s)
            uniq.append(s)
    return uniq[:12]


def fitting_previews(job: dict) -> list[str]:
    """The fitting record's preview pictures (finished models first); snapshots are GLB, not pictures."""
    fit = _d(job.get("fitting"))
    models = _d(fit.get("models"))
    rows = [models[k] for k in fit.get("order") or [] if isinstance(models.get(k), dict)]
    rows.sort(key=lambda m: 0 if m.get("state") == "done" else 1)
    return [m["preview"] for m in rows if _s(m.get("preview")).startswith("/api/")
            and _s(m.get("preview")).split("?")[0].lower().endswith(IMAGE_EXT)]


def retry_of(job: dict) -> dict | None:
    """The call that builds it again (characters: the special-builds recipe shape, never launching), or None."""
    tool, inp = str(job.get("tool") or ""), dict(_d(job.get("input")))
    if not tool or tool in NOT_BUILD_TOOLS:
        return None
    if tool == "characters" and inp.get("op") == "collect" and (inp.get("game_id") or inp.get("game")):
        return {"tool": "characters", "input": {"op": "collect", "game_id": inp.get("game_id") or inp.get("game")},
                "require_os": "linux"}
    if tool == "characters":
        from . import special_builds
        try:
            call = special_builds.sanitize({"tool": "characters", "input": inp})
        except ValueError:
            return None
        op = call["input"]["op"]                             # the recipe shape: the fields that op uses, set
        return {"tool": "characters", "input": special_builds._clean(op, call["input"]), "require_os": "linux"}
    if inp.get("session_id"):                                # bound to a game session that may be gone
        return None
    return {"tool": tool, "input": inp, **({"require_os": job["require_os"]} if job.get("require_os") else {})}


# ------------------------------------------------------------------------------------------------- thumbnails

def thumb_options(facts: dict) -> list[tuple[str, str]]:
    """[(source, url)] best first. facts: game_id, mod, shots (sha256s: card thumb first), folder_images (names),
    artifacts ([{sha256, name, media_type}]), fitting (preview URLs), donors (slugs with a collection preview)."""
    gid, mod = _s(facts.get("game_id")), _s(facts.get("mod"))
    built = (lambda n: f"/api/mods/built/{gid}/{mod}/image/{n}") if gid and mod else None
    imgs = [a for a in facts.get("artifacts") or [] if isinstance(a, dict) and _s(a.get("sha256"))
            and (a.get("media_type") in IMAGE_TYPES or _s(a.get("name")).lower().endswith(IMAGE_EXT))]
    folder = [n for n in facts.get("folder_images") or [] if _s(n)]
    out = []
    out += [("capture", f"/api/artifacts/{s}") for s in facts.get("shots") or [] if _s(s)]
    if built:
        out += [("capture", built(n)) for n in folder if CAPTURE_NAME.search(n.rsplit("/", 1)[-1])]
    out += [("capture", f"/api/artifacts/{a['sha256']}") for a in imgs if CAPTURE_NAME.search(_s(a.get("name")))]
    out += [("fitting", u) for u in facts.get("fitting") or [] if _s(u)]
    if built:
        out += [("preview", built(n)) for n in folder if not CAPTURE_NAME.search(n.rsplit("/", 1)[-1])]
    out += [("preview", f"/api/artifacts/{a['sha256']}") for a in imgs if not CAPTURE_NAME.search(_s(a.get("name")))]
    out += [("donor", f"/api/characters/{s}/preview") for s in facts.get("donors") or [] if _s(s)]
    if gid:
        out.append(("boxart", f"/api/media/{gid}/best?w=360"))
    return out


# ------------------------------------------------------------------------------------------------- the notifier

class Notifier:
    """Posts and groups the build notifications. deps: index() -> built_mods.Index | None, workers() -> [worker +
    online], library() -> Path | None (the character collection)."""

    def __init__(self, store, config=None, *, index=None, workers=None, library=None, clock=time.time):
        self.store, self.config = store, config
        self.index = index or (lambda: None)
        self.workers = workers or (lambda: [])
        self.library = library or (lambda: None)
        self.clock = clock
        self.lock = threading.RLock()
        self.baseline: set[str] | None = None               # the index's build keys already known
        self._resolved: dict[str, float] = {}               # nid -> last thumbnail refresh

    # -- facts about one build
    def _index_rec(self, gid: str, mod: str) -> dict | None:
        idx = self.index()
        if idx is None or not mod:
            return None
        try:
            with idx.lock:
                if gid:
                    return idx.recs.get(f"{gid}/{mod}")
                hits = [r for r in idx.recs.values() if r.get("name") == mod and not r.get("staged")]
            return max(hits, key=lambda r: r.get("marker_mtime") or 0) if hits else None
        except Exception:                                    # noqa: BLE001 - facts are a convenience
            return None

    def _card(self, gid: str, mod: str) -> dict | None:
        if not mod:
            return None
        try:
            from .built_mods import card_mod
            cards = [c for c in self.store.all("mod") if card_mod(c) == mod and (not gid or c.get("game_id") in (gid, None, ""))]
        except Exception:                                    # noqa: BLE001
            return None
        return max(cards, key=lambda c: c.get("ts") or 0) if cards else None

    def _has_preview(self, slug: str) -> bool:
        lib = self.library()
        try:
            return bool(lib) and (Path(lib) / slug / "preview.png").is_file()
        except OSError:
            return False

    def _catalog(self, gid: str) -> dict:
        try:
            return self.store.catalog_get(gid) or {} if gid else {}
        except Exception:                                    # noqa: BLE001
            return {}

    def resolve(self, item: dict, job: dict | None = None) -> dict:
        """Fill the item's mod title, saved-moment slot, thumbnail source + URL from what exists now."""
        gid, mod = item.get("game_id") or "", item.get("mod") or ""
        rec = self._index_rec(gid, mod)
        if rec and not gid:
            gid = item["game_id"] = rec.get("game_id") or ""
        card = self._card(gid, mod)
        meta = _d((rec or {}).get("meta"))
        shots = [s for s in [*(card or {}).get("shots", [])] if s]
        if card and card.get("thumb"):
            shots = [card["thumb"], *[s for s in shots if s != card["thumb"]]]
        donors = [s for s in (item.get("donors") or []) if self._has_preview(s)]
        donors += [d["slug"] for d in (rec or {}).get("donor_previews") or [] if d.get("slug") not in donors]
        if job is not None:
            item["_artifacts"] = self._artifacts(job)
            item["_fitting"] = fitting_previews(job)
        facts = {"game_id": gid, "mod": mod, "shots": shots, "folder_images": (rec or {}).get("images") or [],
                 "artifacts": item.get("_artifacts") or [], "fitting": item.get("_fitting") or [], "donors": donors}
        opts = thumb_options(facts)
        src, url = opts[0] if opts else ("", "")
        if mod and not item.get("mod_title"):
            item["mod_title"] = _s(meta.get("title")) or _s((card or {}).get("title")) or ""
        cat = self._catalog(gid)
        if cat.get("title") and not item.get("game_title"):
            item["game_title"] = cat["title"]
        item.update(thumbnail_source=src, thumbnail_target=url, state_slot=(card or {}).get("state_slot"),
                    card_id=(card or {}).get("id") or "", verified=bool((card or {}).get("verified")
                                                                          or any(meta.get(k) is True for k in ("verified", "verified_in_game", "gameplay_verified"))))
        return item

    def _artifacts(self, job: dict) -> list[dict]:
        try:
            rc = self.store.get("receipt", job.get("receipt_id") or "") or {}
        except Exception:                                    # noqa: BLE001
            return []
        return [{"sha256": a.get("sha256"), "name": a.get("name"), "media_type": a.get("media_type")}
                for a in rc.get("artifacts") or [] if isinstance(a, dict)][:12]

    def _pcs(self) -> list[dict]:
        try:
            return sorted(({"name": w.get("name"), "os": w.get("os")} for w in self.workers()
                           if w.get("online") and w.get("name")), key=lambda w: str(w["name"]).lower())
        except Exception:                                    # noqa: BLE001
            return []

    def launch_for(self, item: dict, pcs: list[dict] | None = None) -> list[dict]:
        if item.get("kind") != "build" or not item.get("mod") or not item.get("game_id"):
            return []
        from .special_builds import launch_options
        return launch_options({"game_id": item["game_id"], "name": item["mod"], "state_slot": item.get("state_slot")},
                              self._pcs() if pcs is None else pcs)

    # -- items
    def item_for(self, job: dict, kind: str) -> dict:
        res, inp = result_of(job), _d(job.get("input"))
        gid_r, mod = mod_of(res)
        gid = gid_r or game_of(job, res)
        if kind != "build":
            mod = mod if kind == "error" else ""
        wid = job.get("worker_id") or ""
        node = ""
        if wid:
            try:
                node = (self.store.get("worker", wid) or {}).get("name") or ""
            except Exception:                                # noqa: BLE001
                node = ""
        request = _d(res.get("request")).get("id") or job.get("parent_request_id") or ""
        item = {"kind": kind, "job_id": job.get("id") or "", "tool": job.get("tool") or "", "op": _s(inp.get("op")),
                "game_id": gid, "game_title": _s(res.get("game")) if isinstance(res.get("game"), str) else "",
                "mod": mod, "mod_title": "", "summary": summary_of(job, res, kind), "node": node,
                "status": status_of(res) or str(job.get("state") or ""), "created": job.get("created") or 0,
                "finished": job.get("finished") or self.clock(), "request_id": request, "donors": donors_of(job, res)}
        if kind == "collect":
            item["collected"], item["total"] = res.get("collected"), res.get("total")
        if kind == "error":
            item["error"] = item["summary"]
            item["retry"] = retry_of(job)
        self.resolve(item, job)
        item["launch"] = self.launch_for(item)
        return item

    # -- the records
    def _recent(self, now: float) -> list[dict]:
        try:
            notes = [n for n in self.store.all("notify") if n.get("auto") == AUTO]
        except Exception:                                    # noqa: BLE001
            return []
        return sorted((n for n in notes if now - (n.get("updated") or n.get("ts") or 0) < BATCH_WINDOW),
                      key=lambda n: -(n.get("updated") or n.get("ts") or 0))

    def _group_of(self, item: dict, notes: list[dict], now: float) -> tuple[dict | None, int | None]:
        """(entry, index of the item it replaces) or (entry, None) to append, or (None, None) for a new entry."""
        jid, gid, mod = item.get("job_id"), item.get("game_id"), item.get("mod")
        for n in notes:                                      # the same job again (a result delivered twice)
            for i, it in enumerate(n.get("items") or []):
                if jid and it.get("job_id") == jid:
                    return n, i
        for n in notes:                                      # the index saw the folder first: the job's item replaces it
            for i, it in enumerate(n.get("items") or []):
                if (mod and not it.get("job_id") and it.get("mod") == mod and it.get("game_id") == gid
                        and now - (n.get("updated") or 0) < 3600):
                    return n, i
        req, created = item.get("request_id"), item.get("created") or 0
        for n in notes:
            age = now - (n.get("updated") or n.get("ts") or 0)
            g = _d(n.get("group"))
            if req and req in (g.get("requests") or []) and age < REQUEST_WINDOW:
                return n, None
            if created and any(abs(created - c) <= SUBMIT_WINDOW for c in g.get("created") or []) and age < BATCH_WINDOW:
                return n, None
        for n in notes:
            age = now - (n.get("updated") or n.get("ts") or 0)
            if age < GROUP_WINDOW and all(it.get("kind") == item["kind"] for it in n.get("items") or []):
                return n, None
        return None, None

    def add(self, item: dict) -> dict:
        """Post the item: into the entry it belongs to (same job, same pass, same request, same minute) or a new one."""
        with self.lock:
            now = self.clock()
            entry, at = self._group_of(item, self._recent(now), now)
            if entry is None:
                entry = {"id": uuid.uuid4().hex[:12], "auto": AUTO, "by": BY, "ts": now, "first": now, "items": [],
                         "group": {"requests": [], "created": []}, "session_id": ""}
            items = list(entry.get("items") or [])
            if at is not None:
                items[at] = item
            else:
                items.append(item)
            entry["items"] = items[-MAX_ITEMS:]
            g = _d(entry.get("group"))
            if item.get("request_id") and item["request_id"] not in g.setdefault("requests", []):
                g["requests"].append(item["request_id"])
            if item.get("created"):
                g.setdefault("created", []).append(item["created"])
                g["created"] = g["created"][-MAX_ITEMS:]
            entry["group"] = g
            entry.update(updated=now, ts=now, read=False)
            entry |= headline(entry)
            self.store.put("notify", entry["id"], entry)
            self._prune()
            return entry

    def _prune(self):
        try:
            rows = self.store.db.execute("SELECT id, json_extract(body,'$.ts') FROM docs WHERE kind='notify'").fetchall()
        except Exception:                                    # noqa: BLE001 - another store: leave it
            return
        if len(rows) <= KEEP:
            return
        for nid, _ts in sorted(rows, key=lambda r: -(r[1] or 0))[KEEP:]:
            self.store.delete("notify", nid)

    # -- hooks
    def job_ended(self, job: dict) -> dict | None:
        """The control plane's hook when a job reaches a final state. Never raises."""
        try:
            kind = classify(job)
            if not kind:
                return None
            idx = self.index()
            if idx is not None and kind == "build":
                try:
                    idx.ask()                                # the new folder joins the gallery soon
                except Exception:                            # noqa: BLE001
                    pass
            return self.add(self.item_for(job, kind))
        except Exception as exc:                             # noqa: BLE001 - a notification never fails a job
            try:
                self.store.audit("gbox-auto", "notify.build_failed", str(job.get("id") or ""), {"error": str(exc)[:300]})
            except Exception:                                # noqa: BLE001
                pass
            return None

    def index_changed(self, records: list[dict]) -> list[dict]:
        """A built-mods index pass changed: build folders no job reported become notifications (fresh ones only)."""
        keys = {f"{r.get('game_id')}/{r.get('name')}": r for r in records if r.get("name") and r.get("game_id")}
        with self.lock:
            if self.baseline is None:                        # the first pass of a cold index: everything is old news
                self.baseline = set(keys)
                return []
            new = [keys[k] for k in sorted(set(keys) - self.baseline)]
            self.baseline = set(keys)
        if not new:
            return []
        now = self.clock()
        try:
            busy = [j for j in self.store.jobs(states=("queued", "running"))]
        except Exception:                                    # noqa: BLE001
            busy = []
        known = {(it.get("game_id"), it.get("mod")) for n in self._recent(now) for it in n.get("items") or []}
        out = []
        for r in new:
            meta = _d(r.get("meta"))
            built = meta.get("built") if isinstance(meta.get("built"), (int, float)) else r.get("marker_mtime") or 0
            gid, mod = r["game_id"], r["name"]
            if now - float(built or 0) > INDEX_FRESH or (gid, mod) in known:
                continue
            if any(game_of(j, {}) == gid and classify(dict(j, state="succeeded", output={"result": {"mod": mod}})) == "build"
                   for j in busy):
                continue                                     # its job is still running: the job reports it
            item = {"kind": "build", "job_id": "", "tool": "", "op": "", "game_id": gid, "game_title": "", "mod": mod,
                    "mod_title": "", "node": "", "status": "built", "created": 0, "finished": float(built or now),
                    "request_id": "", "donors": [], "summary": index_summary(meta, mod), "source": "index"}
            self.resolve(item)
            item["launch"] = self.launch_for(item)
            out.append(self.add(item))
        return out

    def watch(self, index):
        """Hook the built-mods index: keep its own on_change, then report new folders."""
        prev = index.on_change
        if self.baseline is None and getattr(index, "scanned_at", 0):
            with index.lock:
                self.baseline = set(index.recs)

        def on_change(records):
            if prev:
                prev(records)
            try:
                self.index_changed(records)
            except Exception:                                # noqa: BLE001
                pass
        index.on_change = on_change

    # -- reading
    def decorate(self, notes: list[dict]) -> list[dict]:
        """GET /api/notify: launch options for the PCs online now, and young entries' thumbnails re-resolved (a capture
        that arrived after the build replaces the preview)."""
        pcs = names = None
        now = self.clock()
        for n in notes:
            if n.get("auto") != AUTO:
                continue
            pcs = self._pcs() if pcs is None else pcs
            if names is None:
                try:
                    from .built_mods import display_names
                    names = display_names(self.store)
                except Exception:                                # noqa: BLE001 - a name is a convenience
                    names = {}
            changed = False
            if now - (n.get("updated") or 0) < REFRESH_FOR and now - self._resolved.get(n["id"], 0) > REFRESH_EVERY:
                self._resolved[n["id"]] = now
                for it in n.get("items") or []:
                    before = (it.get("thumbnail_target"), it.get("state_slot"), it.get("mod_title"))
                    self.resolve(it)
                    if it.get("kind") == "error" and not it.get("request_id"):
                        it["request_id"] = self._failure_request(it.get("job_id")) or ""
                    changed |= before != (it.get("thumbnail_target"), it.get("state_slot"), it.get("mod_title"))
            for it in n.get("items") or []:
                it["launch"] = self.launch_for(it, pcs)
            if changed:
                n |= headline(n)
                self.store.put("notify", n["id"], n)
            for i, it in enumerate(n.get("items") or []):
                it["thumbnail"] = f"/api/notify/{n['id']}/thumb?i={i}&v={_v(it)}"
            # the operator's name for a build (#1656: Mods card / Builds rename) wins in the tray, old entries too;
            # shown only (the stored entry keeps the writer's title, so clearing the name restores it)
            renamed = False
            for it in n.get("items") or []:
                named = names.get(f"{it.get('game_id')}/{it.get('mod')}") if it.get("mod") else None
                if named and it.get("mod_title") != named:
                    it["mod_title"], renamed = named, True
            n |= headline(n, keep_text=not renamed)
        return notes

    def _failure_request(self, job_id: str) -> str:
        if not job_id:
            return ""
        try:
            row = self.store.db.execute("SELECT id FROM docs WHERE kind='request' AND "
                                        "json_extract(body,'$.context.job_id')=? LIMIT 1", (job_id,)).fetchone()
            return row[0] if row else ""
        except Exception:                                    # noqa: BLE001
            return ""

    def thumb_url(self, nid: str, i: int) -> str | None:
        n = self.store.get("notify", nid)
        if not n:
            return None
        items = n.get("items") or []
        if not items:
            return None
        it = items[max(0, min(i, len(items) - 1))]
        try:
            self.resolve(it)
        except Exception:                                    # noqa: BLE001
            pass
        return it.get("thumbnail_target") or None


def _v(it: dict) -> str:
    """A cache key for the thumbnail URL: changes when a better picture is found."""
    import hashlib
    return hashlib.sha1(str(it.get("thumbnail_target") or "").encode()).hexdigest()[:8]


def index_summary(meta: dict, mod: str) -> str:
    try:
        from .built_mods import changes_of
        rows = changes_of(meta)
    except Exception:                                        # noqa: BLE001
        rows = []
    if rows and isinstance(meta.get("cast"), list):
        built = [r for r in rows if r.get("status") == "built"]
        names = [r["donor"] for r in built if r.get("donor")]
        return f"{len(built)}/{len(rows)} slots built" + (" · " + ", ".join(names[:8]) if names else "")
    if rows:
        return "; ".join(f"{r.get('donor') or '?'} → {r.get('slot') or '?'}" for r in rows)[:300]
    return f"new build folder {mod}"


def headline(entry: dict, keep_text: bool = False) -> dict:
    """The entry's own title / text / kind and the primary item's fields at the top level (older clients show those)."""
    items = entry.get("items") or []
    if not items:
        return {}
    ok = [i for i in items if i.get("kind") == "build"]
    bad = [i for i in items if i.get("kind") == "error"]
    col = [i for i in items if i.get("kind") == "collect"]
    first = (ok or col or bad)[0]
    kind = "build" if ok else "collect" if col and not bad else "error" if bad and not col else "collect"

    def name(i):
        return i.get("mod_title") or i.get("mod") or (f"{i.get('tool')} {i.get('op')}".strip() if i.get("tool") else "build")

    def game(i):
        return i.get("game_title") or i.get("game_id") or ""
    if len(items) == 1:
        i = items[0]
        if i["kind"] == "build":
            title = f"{name(i)} is ready"
            text = " · ".join(x for x in (game(i), i.get("summary")) if x)
        elif i["kind"] == "collect":
            n = i.get("collected")
            title = (f"{n} character{'s' if n != 1 else ''} collected from {game(i) or 'the game'}" if isinstance(n, int)
                     else f"Characters collected from {game(i) or 'the game'}")
            text = i.get("summary") or ""
        elif i.get("op") == "collect":
            title = f"Collecting characters failed: {game(i) or 'the game'}"
            text = i.get("error") or i.get("summary") or ""
        else:
            title = f"Build failed: {name(i)}" + (f" ({game(i)})" if game(i) and game(i) not in name(i) else "")
            text = i.get("error") or i.get("summary") or ""
    else:
        parts = []
        if ok:
            parts.append(f"{len(ok)} build{'s' if len(ok) != 1 else ''} ready")
        if col:
            parts.append(f"{len(col)} collection{'s' if len(col) != 1 else ''} finished")
        if bad:
            parts.append(f"{len(bad)} failed")
        title = ", ".join(parts)
        text = " · ".join(name(i) for i in items[:5]) + (f" · +{len(items) - 5} more" if len(items) > 5 else "")
    out = {"kind": kind, "count": len(items), "game_id": first.get("game_id") or "", "game_title": first.get("game_title") or "",
           "mod": first.get("mod") if first.get("kind") == "build" else "", "mod_title": first.get("mod_title") or "",
           "job_id": first.get("job_id") or "", "summary": first.get("summary") or "",
           "thumbnail": f"/api/notify/{entry.get('id')}/thumb?i={items.index(first)}&v={_v(first)}",
           "thumbnail_source": first.get("thumbnail_source") or "", "launch": first.get("launch") or [],
           **({"error": bad[0].get("error") or "", "retry": bad[0].get("retry")} if bad else {}),
           **({"request_id": first.get("request_id")} if first.get("request_id") else {})}
    if not keep_text:
        out |= {"title": title, "text": text}
    return out


# ------------------------------------------------------------------------------------------------- routes

def routes(app, store, auth, notifier: Notifier):
    @app.get("/api/notify/{nid}/thumb")
    def notify_thumb(nid: str, request: Request, i: int = 0, actor=Depends(auth)):
        """The notification's picture (best source now: a frame of the build running > fitting preview > build
        preview > donor preview > box art): a redirect to that authenticated URL, keeping this request's token."""
        url = notifier.thumb_url(nid, i)
        if not url:
            raise HTTPException(404, "no picture for this notification")
        tok = request.query_params.get("token")
        if tok:
            from urllib.parse import quote
            url += ("&" if "?" in url else "?") + "token=" + quote(tok, safe="")
        return RedirectResponse(url, status_code=307, headers={"cache-control": "private, max-age=60"})

    @app.post("/api/notify/read_all")
    def notify_read_all(actor=Depends(auth)):
        n = 0
        for x in store.all("notify"):
            if not x.get("read"):
                store.put("notify", x["id"], x | {"read": True})
                n += 1
        return {"ok": True, "marked": n}

    return notify_thumb, notify_read_all
