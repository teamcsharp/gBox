"""Bot hot reload (docs/hot-update.md): a deploy that changes only Mercenaries bot logic goes live in the running worker
without restarting gbox.service, so no game, emulator, stream or MercMode warm game is closed.

Operator 2026-10-26: "Every time I look at the system, it's loading the game. Instead of playing the game, it's always
loading the game. I'm trying to reduce loading to be as short as possible to not at all." Every deploy restarted the
service, which kills every emulator and the warm pool; MercMode then cold-launches (RE5 on RPCS3: ~50 s to playing, then
the pool boots again). Most of that day's fixes (five restarts) were bot logic only. Now:

  deploy_main.sh  classify(changed files) is "reload" when every changed runtime file is a bot module (allowed()); it
                  then calls POST /api/workers/{name}/bot-reload (gbox.bot_control) instead of restarting the service,
                  which runs the worker tool bot_reload (gbox.tools) -> reload_bots() here:
    plan          the loaded bot modules whose source changed on disk since this process loaded them (LOADED: the worker's
                  build_sources, kept current here), plus every loaded module that bound names from one of them when it
                  was imported (a stale `from x import y`); such a module outside the allow-list refuses the reload
                  (restart: True). Dependency order (top-level imports of the new sources).
    stage         every new source is executed into a throwaway module object first, imports of this reload's modules
                  resolving to their staged copies: a module that does not import refuses the reload, nothing touched
    stop          each autobot on a bot playbook stops at its next tick (its run releases its inputs; released again
                  here); a round preparation still walking menus, or a bot still stopping, makes the op wait (DRAIN_S)
                  and then answer retry=True with nothing changed
    swap          importlib.reload in dependency order; the state named in KEEP (the RE5 roster and stage pick, the DJ's
                  RE4 requests, learned crossings, locks) survives with the new classes; an exception restores every module
    start         every stopped bot starts again in its session with its own AutoplayIn and its own job context (the same
                  x-gbox-parent-job), so MercMode keeps owning the run and its native round boundaries keep counting
    settle        a restarted bot that dies with an error within settle_s brings the old modules back (rollback) and the
                  bots restart on them: a reload never leaves a game without the bot it had

GATE keeps autoplay starts and round preparations (tools.autoplay) out of a reload in progress. This module is never
reloaded itself (it is not in the allow-list): a change to it, like any other runtime file, needs a service restart.
"""
from __future__ import annotations

import ast
import builtins
import hashlib
import importlib
import importlib.util
import json
import os
import sys
import threading
import time
import types
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

# --- what reloads in place ----------------------------------------------------------------------------------------------
BOT_MODULES = frozenset({
    "gbox.mercs_bot", "gbox.re4_merc_bot", "gbox.re4_threats", "gbox.re4_menus", "gbox.re4_ram_prompts",
    "gbox.re4_navmap", "gbox.re4_collision"})
BOT_PACKAGES = ("gbox.mercs",)             # the package and everything under it, except NOT_BOT
NOT_BOT = frozenset({                      # under gbox.mercs, but state or threads that outlive a bot run:
    "gbox.mercs.warm_boot",                # the MercMode warm pool's pause/resume observers (adapter-lifetime threads)
    "gbox.mercs.damage",                   # the worker-lifetime player-damage delivery thread and its file locks
    "gbox.mercs.directives",               # the chat's instant commands: an in-memory store the control plane writes
    "gbox.mercs.interventions",            # durable routes and adapter-lifetime native request consumers
    "gbox.mercs.titles.re6_switch_native",  # native mailbox owner/lock must not be replaced while a call executes
    "gbox.mercs.titles.re5_switch_native",  # same adapter-lifetime mailbox ownership as RE6
    "gbox.mercs.titles.re4_gc_native",      # Dolphin dispatcher ownership and observed life context
    "gbox.mercs.teamplay",                 # team / training intent and its evidence (mercs_team tool, tools.autoplay)
    "gbox.mercs.evidence_sync",            # federation / desktop-bridge evidence delivery threads
    "gbox.mercs.round_reports",            # control-plane routes and the Hermes queue
    "gbox.mercs.reviewer",                 # control-plane routes
    "gbox.mercs.titles.re5_eggs",          # RE5 mod supply workers started by the re5_mods tool (adapter lifetime)
    "gbox.mercs.titles.re5_live_weapon",
})
RUNTIME_PREFIXES = ("gbox/", "adapters/", "hermes/", "profiles/")   # deploy_main.sh's runtime code (a restart until now)
RUNTIME_FILES = ("gbox.toml", "pyproject.toml")
# module -> attributes whose objects survive a reload (a module may add its own RELOAD_KEEP tuple). An instance whose class
# the reload redefined becomes an instance of the new class with the old data; other objects are kept as they were.
KEEP = {
    "gbox.mercs.titles.re5_ps3": ("ROSTER", "STAGE_PICK", "_COVERAGE", "_AVOID"),
    "gbox.mercs.titles.re6_ps3": ("ROSTER", "STAGE_PICK"),
    "gbox.mercs.titles.re6_x360": ("ROSTER", "STAGE_PICK"),
    "gbox.mercs.titles.re5_controls": ("LOCK",),
    "gbox.mercs.lessons": ("_LOCK",),
    "gbox.re4_menus": ("REQUESTS",),
    "gbox.re4_ram_prompts": ("_LABEL_CACHE",),
}
DRAIN_S = 90.0          # how long a round preparation / a stopping bot may keep the reload waiting before "busy"
STOP_S = 20.0           # stopped bots end within this (bot_control.STOP_SETTLE_S), else nothing is reloaded
SETTLE_S = 5.0          # a restarted bot that dies with an error this soon brings the old modules back
GATE_WAIT_S = 15.0      # autoplay starts in flight finish their setup within this
START_WAIT_S = 50.0     # an autoplay start waits this long for a reload in progress (the autoplay tool's limit is 60 s)
LOADED: dict[str, str] = {}   # "gbox/x.py" -> sha256 of the source this process runs (worker.run: its build_sources)


class Refused(Exception):
    """A reload that did not happen. retry: try again shortly (busy); restart: only a service restart applies it."""

    def __init__(self, reason: str, module: str = "", *, retry: bool = False, restart: bool = False):
        super().__init__(reason)
        self.reason, self.module, self.retry, self.restart = reason, module, retry, restart


def allowed(name: str) -> bool:
    """A pure bot module: reloadable in place. Never adapters, server, store, tools or the warm pool."""
    if name in NOT_BOT:
        return False
    return name in BOT_MODULES or any(name == p or name.startswith(p + ".") for p in BOT_PACKAGES)


def module_of(path: str) -> str | None:
    """'gbox/mercs/x.py' -> 'gbox.mercs.x' (a package's __init__.py -> the package); None for anything else."""
    rel = str(path).replace("\\", "/").removeprefix("./").removeprefix("system/")
    if not rel.endswith(".py") or not rel.startswith("gbox/"):
        return None
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if all(p.isidentifier() for p in parts) else None


def classify(paths) -> dict:
    """deploy_main.sh: what the deployed files need. action none (no runtime code), reload (every runtime file is a bot
    module: POST /api/workers/{name}/bot-reload) or restart (anything else: gbox.service)."""
    rels = [str(p).replace("\\", "/").removeprefix("./").removeprefix("system/") for p in paths if str(p).strip()]
    runtime = [r for r in rels if r.startswith(RUNTIME_PREFIXES) or r in RUNTIME_FILES]
    bot = [r for r in runtime if (m := module_of(r)) and allowed(m)]
    other = [r for r in runtime if r not in bot]
    action = "none" if not runtime else "restart" if other else "reload"
    return {"action": action, "bot": bot, "other": other}


def track(sources: dict) -> None:
    """worker.run: the hashes of the code this process loaded (its build_sources, the same dict, kept current after a
    reload so the control plane sees which bot code runs)."""
    global LOADED
    LOADED = sources


# --- plan -------------------------------------------------------------------------------------------------------------
@dataclass
class Plan:
    names: list = field(default_factory=list)          # dependency order
    why: dict = field(default_factory=dict)
    paths: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)        # the source bytes staged (and recorded once reloaded)
    not_loaded: list = field(default_factory=list)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _source_path(mod) -> Path | None:
    f = getattr(mod, "__file__", None)
    return Path(f) if isinstance(f, str) and f.endswith(".py") and Path(f).is_file() else None


def _rel(name: str, path: Path) -> str:
    return "/".join(name.split(".")) + ("/__init__.py" if path.name == "__init__.py" else ".py")


def _package(name: str, path: Path) -> str:
    return name if path.name == "__init__.py" else name.rpartition(".")[0]


def _absolute(name: str, package: str, level: int) -> str:
    bits = package.rsplit(".", level - 1)
    if len(bits) < level:
        raise ImportError("attempted relative import beyond top-level package")
    return f"{bits[0]}.{name}" if name else bits[0]


def _resolve(node: ast.ImportFrom, package: str) -> str:
    if not node.level:
        return node.module or ""
    try:
        return _absolute(node.module or "", package, node.level)
    except ImportError:
        return ""


def _top_level(tree):
    """Statements that run at import: the module body and the bodies of top-level if / try / with (never functions)."""
    todo = list(tree.body)
    while todo:
        node = todo.pop(0)
        yield node
        if isinstance(node, (ast.If, ast.Try, ast.With)):
            todo[:0] = [*node.body, *getattr(node, "orelse", []), *getattr(node, "finalbody", []),
                        *[s for h in getattr(node, "handlers", []) for s in h.body]]


_PARSED: dict = {}                         # (path, size, mtime) -> AST, for one plan() (cleared there)


def _parsed(path: Path, needle: str = ""):
    """The module's AST, or None when its source never contains needle (checked on the text before any parse)."""
    try:
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime_ns)
        tree = _PARSED.get(key)
        if tree is None:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            if needle and needle not in text:
                return None
            tree = _PARSED[key] = ast.parse(text)
    except (OSError, SyntaxError, ValueError):
        return None
    return tree


def _binders(target: str) -> list:
    """Loaded modules that bound attributes of target when they were imported (`from target import name` at top level):
    after target reloads they would keep its old objects."""
    top, short = target.split(".")[0], target.rsplit(".", 1)[-1]
    needle = short + " import" if target != top else ""     # every `from ...<short> import` line contains it
    out = []
    for name, mod in list(sys.modules.items()):
        if mod is None or name == target or not (name == top or name.startswith(top + ".")):
            continue
        path = _source_path(mod)
        tree = _parsed(path, needle) if path is not None else None
        if tree is None:
            continue
        pkg = _package(name, path)
        for node in _top_level(tree):
            if isinstance(node, ast.ImportFrom) and _resolve(node, pkg) == target \
                    and any(a.name == "*" or f"{target}.{a.name}" not in sys.modules for a in node.names):
                out.append(name)
                break
    return out


def _order(p: Plan) -> list:
    """Dependencies first (top-level imports of the new sources among this plan's modules); ties alphabetical."""
    names = set(p.why)
    deps = {n: set() for n in names}
    for n in names:
        try:
            tree = ast.parse(p.sources[n].decode("utf-8-sig", errors="replace"))
        except SyntaxError:
            continue                                        # stage() refuses it with the real error
        pkg = _package(n, p.paths[n])
        for node in _top_level(tree):
            if isinstance(node, ast.ImportFrom):
                src = _resolve(node, pkg)
                cands = [src, *[f"{src}.{a.name}" for a in node.names]]
            elif isinstance(node, ast.Import):
                cands = [a.name for a in node.names]
            else:
                continue
            deps[n] |= {c for c in cands if c in names and c != n}
    order, done = [], set()
    while len(order) < len(names):
        ready = sorted(n for n in names - done if deps[n] <= done)
        if not ready:                                       # an import cycle: the rest alphabetically
            ready = sorted(names - done)[:1]
        order.append(ready[0])
        done.add(ready[0])
    return order


def plan(modules=(), *, allowed=allowed, registry=None) -> Plan:
    """What reloads: the named modules (each must be allowed; one not loaded is reported, it loads fresh at first use) or,
    with none named, every loaded allowed module whose source on disk differs from registry (LOADED). Plus every loaded
    module binding names from one of them since its import; such a module outside the allow-list refuses the reload."""
    importlib.invalidate_caches()                           # new files of this deploy are found
    _PARSED.clear()
    registry = LOADED if registry is None else registry
    loaded = {n: m for n, m in list(sys.modules.items())
              if m is not None and allowed(n) and _source_path(m) is not None}
    p = Plan()
    if modules:
        refused = [n for n in modules if not allowed(n)]
        if refused:
            raise Refused("not bot modules (only bot modules reload in place): " + ", ".join(sorted(refused)),
                          refused[0], restart=True)
        p.why = {n: "requested" for n in modules if n in loaded}
        p.not_loaded = sorted(n for n in modules if n not in loaded)
    else:
        for n, m in loaded.items():
            path = _source_path(m)
            want = registry.get(_rel(n, path))
            if want is not None and want != _digest(path.read_bytes()):
                p.why[n] = "changed on disk"
    todo = list(p.why)
    while todo:
        target = todo.pop()
        for importer in _binders(target):
            if importer in p.why:
                continue
            if not allowed(importer):
                raise Refused(f"{importer} bound names from {target} when it was imported and is not a bot module: a "
                              "service restart applies this change", importer, restart=True)
            p.why[importer] = f"binds names from {target}"
            todo.append(importer)
    for n in p.why:
        p.paths[n] = _source_path(sys.modules[n])
        p.sources[n] = p.paths[n].read_bytes()
    p.names = _order(p)
    return p


# --- stage: the new code imports, or nothing happens ----------------------------------------------------------------------
class _Overlay:
    """A package as staged code sees it: this reload's staged submodules first, the running package for the rest."""

    def __init__(self, module, subs):
        object.__setattr__(self, "_module", module)
        object.__setattr__(self, "_subs", subs)

    def __getattr__(self, attr):
        subs = object.__getattribute__(self, "_subs")
        return subs[attr] if attr in subs else getattr(object.__getattribute__(self, "_module"), attr)


def _staging_builtins(staged: dict) -> dict:
    real_import = builtins.__import__

    def hooked(name, globals=None, locals=None, fromlist=(), level=0):
        target = _absolute(name, (globals or {}).get("__package__") or "", level) if level else name
        if fromlist:
            if target in staged:
                return staged[target]
            subs = {f: staged[f"{target}.{f}"] for f in fromlist if f != "*" and f"{target}.{f}" in staged}
            module = real_import(name, globals, locals, fromlist, level)
            return _Overlay(module, subs) if subs else module
        return real_import(name, globals, locals, fromlist, level)
    return {**builtins.__dict__, "__import__": hooked}


def stage(p: Plan) -> dict:
    """Execute each new source into a throwaway module object, in dependency order (never into sys.modules). Raises
    Refused naming the first module that does not import; the running modules are untouched either way."""
    staged: dict = {}
    hooked = _staging_builtins(staged)
    for name in p.names:
        real, path = sys.modules[name], p.paths[name]
        package = list(real.__path__) if hasattr(real, "__path__") else None
        spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=package)
        mod = importlib.util.module_from_spec(spec)
        mod.__dict__["__builtins__"] = hooked
        try:
            exec(compile(p.sources[name], str(path), "exec", dont_inherit=True), mod.__dict__)
        except BaseException as exc:                       # noqa: BLE001 - SystemExit at import is a broken module too
            raise Refused(f"{name} does not import: {type(exc).__name__}: {exc}"[:400], name) from exc
        staged[name] = mod
    return staged


def _extend(p: Plan, new_names, allowed=allowed) -> None:
    """Bot modules a staged import loaded for the first time: they may have bound names from the old modules of this
    plan, so they reload after them."""
    for n in sorted(new_names):
        mod = sys.modules.get(n)
        path = _source_path(mod) if mod is not None else None
        if path is not None and allowed(n) and n not in p.why:
            p.why[n], p.paths[n], p.sources[n] = "first imported by this reload", path, path.read_bytes()
            p.names.append(n)


# --- swap -------------------------------------------------------------------------------------------------------------
_MISSING = object()


def _drop_bytecode(path: Path) -> None:
    """The reload compiles the source on disk, never a __pycache__ entry that a same-size rewrite within one second could
    leave looking current."""
    try:
        os.remove(importlib.util.cache_from_source(str(path)))
    except (OSError, NotImplementedError, ValueError):
        pass


def _instance(obj) -> bool:
    return hasattr(obj, "__dict__") and not isinstance(obj, (type, types.ModuleType, types.FunctionType)) \
        and type(obj).__module__ != "builtins"


def _carry(mod, snap: dict, names) -> list:
    """KEEP: the old objects back into the reloaded module. A new instance of the same class name takes the old one's
    data (the new code, the bot's state); anything else is kept as it was. Returns the objects kept as they were."""
    kept = []
    for attr in dict.fromkeys(names):
        if attr not in snap:
            continue
        old, new = snap[attr], mod.__dict__.get(attr, _MISSING)
        if new is not _MISSING and _instance(new) and _instance(old) \
                and (type(old).__module__, type(old).__qualname__) == (type(new).__module__, type(new).__qualname__):
            try:
                vars(new).update(vars(old))
                continue
            except TypeError:
                pass
        mod.__dict__[attr] = old
        kept.append(old)
    return kept


def _rebind(obj):
    """An object kept across the reload whose class was redefined becomes an instance of the new class. Returns the old
    class when it did (restore() puts it back)."""
    if not _instance(obj):
        return None
    cls = type(obj)
    mod = sys.modules.get(getattr(cls, "__module__", ""))
    new = getattr(mod, cls.__qualname__, None) if mod is not None and "." not in cls.__qualname__ else None
    if isinstance(new, type) and new is not cls:
        try:
            obj.__class__ = new
            return cls
        except TypeError:
            pass
    return None


class Swapped(list):
    """swap()'s record: [(module, old dict)] in reload order, and rebound = [(kept object, its old class)]."""
    rebound: tuple = ()


def restore(done) -> None:
    """The old module dicts back, newest first (a failed reload, or rollback after a bot died on the new code); kept
    objects get their old classes back."""
    for obj, cls in reversed(getattr(done, "rebound", ())):
        try:
            obj.__class__ = cls
        except TypeError:
            pass
    for mod, snap in reversed(done):
        extra = set(mod.__dict__) - set(snap)
        mod.__dict__.update(snap)
        for k in extra:
            mod.__dict__.pop(k, None)


def swap(p: Plan, keep=None) -> Swapped:
    """importlib.reload every planned module in order, carrying KEEP. Any exception restores all of them and raises
    Refused. Returns the record restore() undoes."""
    keep = KEEP if keep is None else keep
    done, kept = Swapped(), []
    for name in p.names:
        mod = sys.modules[name]
        snap = dict(mod.__dict__)
        _drop_bytecode(p.paths[name])
        try:
            importlib.reload(mod)
        except BaseException as exc:                       # noqa: BLE001 - every module comes back as it was
            restore([*done, (mod, snap)])
            raise Refused(f"{name} failed to reload: {type(exc).__name__}: {exc}"[:400], name) from exc
        done.append((mod, snap))
        names = (*keep.get(name, ()), *(snap.get("RELOAD_KEEP") or ()), *(mod.__dict__.get("RELOAD_KEEP") or ()))
        kept += _carry(mod, snap, names)
    done.rebound = tuple((obj, old) for obj in kept if (old := _rebind(obj)) is not None)
    return done


def commit(p: Plan, registry=None) -> None:
    """The reloaded sources become what this process runs. Existing entries only: the worker's heartbeat reads this
    same dict from another thread, and a new key mid-iteration would break it (a new file is unknown = unchanged)."""
    registry = LOADED if registry is None else registry
    for n in p.names:
        key = _rel(n, p.paths[n])
        if key in registry:
            registry[key] = _digest(p.sources[n])


# --- the gate: autoplay starts vs a reload ---------------------------------------------------------------------------------
class Gate:
    """Any number of autoplay starts / round preparations at once (tools.autoplay); a reload waits for those in flight to
    finish their setup and holds new ones back until it is done. The reload's own restarts (its thread) go through."""

    def __init__(self):
        self._cv = threading.Condition()
        self._starts = 0
        self._owner = None

    @property
    def reloading(self) -> bool:
        return self._owner is not None

    @contextmanager
    def start(self, timeout: float = START_WAIT_S):
        me = threading.get_ident()
        with self._cv:
            if self._owner not in (None, me) and not self._cv.wait_for(lambda: self._owner is None, timeout):
                raise RuntimeError("A bot reload is still running on this PC; try again in a moment.")
            self._starts += 1
        try:
            yield
        finally:
            with self._cv:
                self._starts -= 1
                self._cv.notify_all()

    @contextmanager
    def exclusive(self, timeout: float = GATE_WAIT_S):
        me = threading.get_ident()
        with self._cv:
            got = self._owner is None
            if got:
                self._owner = me
                got = self._cv.wait_for(lambda: self._starts == 0, timeout)
                if not got:
                    self._owner = None
                    self._cv.notify_all()
        try:
            yield got
        finally:
            if got:
                with self._cv:
                    self._owner = None
                    self._cv.notify_all()


GATE = Gate()


# --- the op -------------------------------------------------------------------------------------------------------------
def _result(ok: bool, t0: float, clock, **kw) -> dict:
    return {"ok": ok, "retry": False, "restart": False, "reloaded": [], "restarted": [], **kw,
            "took_s": round(clock() - t0, 2)}


def _refusal(e: Refused, t0, clock, **kw) -> dict:
    return _result(False, t0, clock, reason=e.reason, module=e.module, retry=e.retry, restart=e.restart, **kw)


def _settle(host, back, settle_s, clock, sleep):
    deadline = clock() + settle_s
    while back and clock() < deadline:
        for b in back:
            why = host.crashed(b["session_id"])
            if why:
                return f"the autobot on {b['session_id']} stopped with an error on the new code ({why})"
        sleep(0.25)
    return None


def _stop_all(host, runs, stop_s, clock) -> list:
    """Stop every run, wait for them together; returns the session ids whose thread is still alive."""
    t = clock()
    for sid, run in runs:
        host.stop(sid, run)
    return [sid for sid, run in runs if not host.join(run, max(0.0, t + stop_s - clock()))]


def _apply(host, p: Plan, *, settle_s, stop_s, keep, registry, t0, clock, sleep) -> dict:
    bots = host.bots()
    since = time.time()                                     # an operator stop / pad touch after this wins over the restart
    t_stop = clock()
    lingering = _stop_all(host, bots, stop_s, clock)
    if lingering:
        # never reload under a live bot thread: the bots that did stop get their game back with the code they had
        back = [host.start(sid, run, since) for sid, run in bots if sid not in lingering]
        for sid, run in bots:
            if sid in lingering:
                host.start_later(sid, run, since)
        return _result(False, t0, clock, retry=True, restarted=back,
                       reason=f"the autobot on {', '.join(lingering)} did not stop within {stop_s:.0f} s; nothing was "
                              "reloaded (it gets its bot back when it ends)")
    for sid, _ in bots:
        host.release(sid)
    try:
        done = swap(p, keep)
    except Refused as e:                                   # swap restored every module itself
        return _refusal(e, t0, clock, restarted=[host.start(sid, run, since) for sid, run in bots])
    lost = [sid for sid, run in bots if not host.playbook(sid)]   # (another bot playbook taking it is the new code's call)
    if lost:
        restore(done)
        return _result(False, t0, clock, module=p.names[0], restarted=[host.start(sid, run, since) for sid, run in bots],
                       reason=f"with the new code no bot playbook takes {', '.join(lost)} any more: the old bot modules "
                              "are back")
    back = [host.start(sid, run, since) for sid, run in bots]
    gap = clock() - t_stop
    died = _settle(host, [b for b in back if b.get("restarted")], settle_s, clock, sleep) if settle_s > 0 else None
    if died:
        again = host.bots()
        _stop_all(host, again, stop_s, clock)
        for sid, _ in again:
            host.release(sid)
        restore(done)
        return _result(False, t0, clock, module=p.names[0], rolled_back=True,
                       restarted=[host.start(sid, run, since) for sid, run in bots],
                       reason=f"{died}: the old bot modules are back and the bots restarted on them")
    commit(p, registry)
    return _result(True, t0, clock, reloaded=list(p.names), why=dict(p.why), restarted=back, gap_s=round(gap, 2),
                   not_loaded=p.not_loaded,
                   reason=f"{sum(bool(b.get('restarted')) for b in back)} of {len(back)} autobot(s) back in {gap:.1f} s; "
                          f"reloaded {', '.join(n.rsplit('.', 1)[-1] for n in p.names)}")


def reload_bots(host, *, modules=(), settle_s: float = SETTLE_S, allowed=allowed, registry=None, keep=None,
                drain_s: float = DRAIN_S, stop_s: float = STOP_S, clock=time.monotonic, sleep=time.sleep) -> dict:
    """The worker op (tools.bot_reload): plan, stage, then - with no round preparation running and no autostart in
    flight - stop the bots, swap, start them again and settle. host is the worker's view of its autoplay runs
    (tools._ReloadHost): bots() busy() stop() join() release() playbook() playbook_of() start() start_later() crashed().
    Returns {ok, retry, restart, reason, reloaded, restarted, ...}; never raises for a refusal."""
    t0 = clock()
    registry = LOADED if registry is None else registry
    try:
        p = plan(modules, allowed=allowed, registry=registry)
        if not p.names:
            return _result(True, t0, clock, not_loaded=p.not_loaded,
                           reason="no loaded bot module changed: nothing to reload" + (
                               f" ({', '.join(p.not_loaded)} load fresh at first use)" if p.not_loaded else ""))
        before = set(sys.modules)
        stage(p)
        _extend(p, set(sys.modules) - before, allowed)
    except Refused as e:
        return _refusal(e, t0, clock)
    deadline = clock() + drain_s
    while True:
        busy = host.busy()
        if not busy:
            with GATE.exclusive(GATE_WAIT_S) as got:
                busy = host.busy() if got else "autoplay starts are still setting up"
                if not busy:
                    return _apply(host, p, settle_s=settle_s, stop_s=stop_s, keep=keep, registry=registry, t0=t0,
                                  clock=clock, sleep=sleep)
        if clock() >= deadline:
            return _result(False, t0, clock, retry=True, reason=f"{busy}; nothing was changed: try again shortly")
        sleep(0.5)


# --- deploy_main.sh -------------------------------------------------------------------------------------------------------
def verdict(answer) -> tuple[str, str]:
    """The route's answer for deploy_main.sh: (reloaded | busy | refused | failed, one line). refused: the new bot code
    does not run (the old modules kept running; a restart would load the same code); failed: no reload happened for
    another reason (route, worker, a change only a restart applies) - the deploy falls back to the service restart."""
    if not isinstance(answer, dict) or not isinstance(answer.get("result"), dict):
        detail = answer.get("detail") if isinstance(answer, dict) else None
        return "failed", str(detail or "no answer from the bot-reload route")[:300]
    r = answer["result"]
    reason = str(r.get("reason") or "")[:300]
    if r.get("ok"):
        return "reloaded", reason
    if r.get("retry"):
        return "busy", reason
    if r.get("restart"):
        return "failed", reason
    return "refused", reason


def _say(text: str) -> None:
    """One line on stdout ending in a bare newline on every OS (deploy_main.sh reads it through $(...))."""
    sys.stdout.flush()
    buf = getattr(sys.stdout, "buffer", None)
    if buf is None:
        print(text)
        return
    buf.write(text.encode("utf-8", "replace") + b"\n")
    buf.flush()


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m gbox.hot_reload", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify", help="print none | reload | restart for deployed files (paths under system/)")
    c.add_argument("paths", nargs="*")
    c.add_argument("--json", action="store_true")
    sub.add_parser("verdict", help="read the bot-reload route's JSON answer on stdin; print '<verdict> <reason>'")
    a = ap.parse_args(argv)
    if a.cmd == "classify":
        out = classify(a.paths)
        _say(json.dumps(out) if a.json else out["action"])
        return 0
    try:
        answer = json.loads(sys.stdin.read() or "null")
    except ValueError:
        answer = None
    kind, reason = verdict(answer)
    _say(f"{kind} {reason}".strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
