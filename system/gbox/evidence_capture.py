"""evidence_capture: diagnostic session screenshots for pull requests (docs/pr-evidence.md).

A PR needs independently reviewed gameplay evidence. This tool executes a recipe and preserves screenshots
for that review without touching the operator's play; capture success does not verify the game or modification:

  1. node       an idle node that may run agent tests: a Windows worker nobody used for IDLE_MIN_S seconds (ticked
                for background testing in the Tasks menu, no jobs running), else the Spark - and never a node with
                any running game (the operator's or another agent's: launch_game would close it). node="<name>" pins
                it, with the same refusals. One evidence capture runs at a time (the server refuses a second).
  2. session    launch_game with the mod (agent_use: 2% volume on Windows), labelled owner=agent ("shown dimmed").
  3. recipe     the recipe's moment (a saved state: an exported artifact, or a slot on the node that saved it) and
                the recipe's steps after it (inputs that make the game load its models again from the modded disc -
                a state holds the models that were in RAM when it was saved), or the boot input steps when there is
                no moment. Steps are pad presses, waits, a few session-scoped tools (zelda_oot goto, mgs_vr ...) and
                inline shots.
  4. shots      get_frame (or scene_capture) at {at_s} after recipe steps finish or right {after_inputs} step k.
  5. stock      compare_stock: the same recipe on the unmodded game, then a before/after picture per shot label.
  6. close      the tool's own session is stopped whatever happened, and only that one. If someone starts using the
                node (input on that PC, a game started there), the capture stops its session and reports "yielded".

Frames are artifacts (sha256 ids), marked "session screenshot" until gameplay is independently verified. The recipes (per game_id: moment, steps,
shots, which camera shows the replaced characters) live in gbox/evidence_recipes.json; a moment the operator
records later (POST /api/evidence/moments) overrides the seed. Everything that talks to the control plane is
injected (run_job, workers, sessions, labels, operator_active, ...), so the flow is tested without a server or an
emulator (tests/test_evidence_capture.py).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import BaseModel, Field

from .registry import Unsupported, tool

TOOL = "evidence_capture"
RECIPES_FILE = Path(__file__).with_name("evidence_recipes.json")
IDLE_MIN_S = 300.0                  # a Windows PC is "idle" when nobody touched it for this long
LAUNCH_WAIT_S = 900.0
BOOT_SETTLE_S = 6.0                 # same as session_swap / scene_relay: let the core boot before loading a state
LOAD_SETTLE_S = 2.0
DARK_LUMA = 3.0                     # get_frame mean_luma at or below this: a black frame (loading / not drawing)
MAX_STEPS = 200
MAX_SHOTS = 16
MAX_WAIT_S = 120.0                  # one step's wait
STEP_TOOLS = {                      # session-scoped tools a recipe step may call (session_id is filled in)
    "zelda_oot": {"goto", "state", "skip_deku_tree"},
    "mgs_vr": {"status", "complete", "unlock_all", "stages"},
    "stage_warp": {"warp", "stages", "games"},
    "session_op": {"load_state", "pause", "resume", "step_frames", "reset"},
}
MOMENT_KINDS = ("artifact", "slot", "mod_card", "recorded", "none")


class EvidenceError(RuntimeError):
    """The capture could not run or was stopped; the message says why. No operator session is ever touched."""


class Yielded(EvidenceError):
    """Someone started using the node mid-capture: the tool stopped its own session and gave the node back."""


# ------------------------------------------------------------------------------------------------ the contract

class Shot(BaseModel):
    label: str
    at_s: float | None = None              # seconds after the recipe steps finish
    after_inputs: int | str | None = None  # right after step k (0-based) or the step labelled so
    kind: str = "frame"                    # frame (get_frame PNG) | scene (scene_capture GLB, Examine 3D)


class InputStep(BaseModel):
    press: list[str] = []                  # pad buttons held together: a b x y start select up down left right l r z ...
    hold_s: float = 0.12
    wait_s: float = 0.5                    # after the release (or alone: a pure wait)
    repeat: int = 1
    tool: str = ""                         # a session-scoped tool instead of a press (STEP_TOOLS)
    input: dict = {}
    shot: str = ""                         # an inline shot with this label after the step
    label: str = ""


class EvidenceIn(BaseModel):
    game_id: str
    mod: str = ""                          # "" = the stock game
    node: str = "auto"                     # auto | a worker name/id | windows | linux
    inputs: list[InputStep] | None = None  # None = the recipe's steps
    load_moment: dict | str | None = None  # None = the recipe's moment; "none" = boot; {"artifact": sha} |
                                           # {"slot": n, "worker": name} | {"mod_card": id} | "recorded"
    shots: list[Shot] = []                 # [] = the recipe's shots
    compare_stock: bool = False            # also the unmodded game, and a before/after picture per shot label
    recipe: str = ""                       # a named variant of the game's recipe ("" = its default)
    boot_s: float | None = None            # None = the recipe's (seconds after launch before the moment / steps)
    debug: bool = False                    # launch_game debug=True: a debugger emulator (Linux) or Cxbx's full kernel log


class EvidenceOut(BaseModel):
    game_id: str
    mod: str = ""
    recipe: str = ""
    worker: str = ""
    runs: list[dict] = []                  # [{variant: mod|stock, session_id, reached, frames, stopped, notes}]
    frames: list[dict] = []                # [{run, label, sha256, url, kind: "session screenshot", width, height, mean_luma}]
    pairs: list[dict] = []                 # [{label, stock, mod, composite}] (compare_stock)
    artifacts: list[str] = []              # every PNG this capture made (frames + composites)
    notes: list[str] = []


@tool(TOOL, "1.1", EvidenceIn, EvidenceOut, capabilities=["video", "runtime", "evidence"], timeout_s=3600,
      artifacts=["frame.png", "pair.png"], validation="frames are get_frame PNG artifacts; composites PNG")
def evidence_capture(inp: EvidenceIn, ctx):
    """Diagnostic PR screenshots: launch an agent-owned test session on an idle node, execute the saved-moment/input
    recipe, capture images and optional stock/mod pairs, then stop that session. Gameplay needs independent review.
    Runs inside the control plane (POST /api/jobs tool=evidence_capture); never on a worker."""
    raise Unsupported("evidence_capture runs inside the control plane: POST /api/jobs {tool: evidence_capture}")


# ------------------------------------------------------------------------------------------------ recipes

def load_recipes(path: Path | None = None) -> dict:
    """gbox/evidence_recipes.json -> {game_id: recipe}; every recipe is checked (see check_recipe)."""
    raw = json.loads(Path(path or RECIPES_FILE).read_text(encoding="utf-8"))
    games = raw.get("games") if isinstance(raw, dict) else None
    if not isinstance(games, dict):
        raise ValueError("evidence recipes: top-level {games: {game_id: recipe}} expected")
    for gid, r in games.items():
        problems = check_recipe(r)
        if problems:
            raise ValueError(f"evidence recipe {gid}: " + "; ".join(problems))
    return games


def check_recipe(r: dict) -> list[str]:
    out = []
    if not isinstance(r, dict):
        return ["not an object"]
    if r.get("status") not in ("ready", "unverified", "needs_state", "todo"):
        out.append("status must be ready | unverified | needs_state | todo")
    variants = {"": r, **{k: v for k, v in (r.get("variants") or {}).items()}}
    for name, v in variants.items():
        where = f"variant {name}: " if name else ""
        m = v.get("moment")
        if m is not None and not (isinstance(m, dict) and m.get("kind") in MOMENT_KINDS):
            out.append(f"{where}moment.kind must be one of {MOMENT_KINDS}")
        if isinstance(m, dict) and m.get("kind") == "artifact" and not _is_sha(m.get("artifact")):
            out.append(f"{where}moment.artifact must be a sha256")
        for key in ("steps", "after_moment"):
            for k, s in enumerate(v.get(key) or []):
                try:
                    st = InputStep.model_validate(s)
                except Exception as e:                     # noqa: BLE001
                    out.append(f"{where}{key}[{k}]: {e}")
                    continue
                if st.tool and (st.tool not in STEP_TOOLS or st.input.get("op") not in STEP_TOOLS[st.tool]):
                    out.append(f"{where}{key}[{k}]: tool {st.tool} op {st.input.get('op')} is not allowed in a recipe")
        for k, s in enumerate(v.get("shots") or []):
            try:
                Shot.model_validate(s)
            except Exception as e:                         # noqa: BLE001
                out.append(f"{where}shots[{k}]: {e}")
    return out


def _is_sha(v) -> bool:
    return isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v)


def recipe_for(game_id: str, variant: str = "", recipes: dict | None = None, recorded: dict | None = None) -> dict:
    """The game's recipe (a named variant overrides the base fields); a moment the operator recorded for the game
    (POST /api/evidence/moments) replaces the seed's moment. Unknown game: an empty boot recipe."""
    recipes = load_recipes() if recipes is None else recipes
    base = dict(recipes.get(game_id) or {"status": "todo", "title": game_id, "steps": [], "shots": []})
    if variant:
        if variant not in (base.get("variants") or {}):
            raise EvidenceError(f"recipe {game_id} has no variant {variant!r} "
                                f"(has: {', '.join(base.get('variants') or {}) or 'none'})")
        base = {**base, **base["variants"][variant]}
    base.pop("variants", None)
    if recorded and recorded.get("artifact"):
        base["moment"] = {"kind": "artifact", "artifact": recorded["artifact"],
                          "label": recorded.get("label") or "recorded gameplay moment", "recorded": True}
        if recorded.get("after_moment") is not None:
            base["after_moment"] = recorded["after_moment"]
    return base


# ------------------------------------------------------------------------------------------------ where it runs

def required_os(game: dict) -> str | None:
    """The only worker OS that can run this game's platform, or None when either OS can.

    Mirrors adapters.for_game's Windows-only guards: cxbx (Xbox), RPCS3 (PS3), Xenia
    (Xbox 360) and Yuzu (Switch) raise ToolUnavailable on a Linux worker, so an evidence
    capture must never fall through to Linux for them."""
    from .xbox import is_xbox_game
    g = game or {}
    if is_xbox_game(g):
        return "windows"
    if g.get("platform") in ("ps3", "xbox360", "switch"):
        return "windows"
    if (g.get("launch") or {}).get("kind") == "savemgo_bundle":
        return "windows"
    return None


def pick_node(node: str, workers: list[dict], live_sessions: list[dict], *, needs: set[str],
              prefer_os: list[str] | None = None, required_os: str | None = None,
              worker_of=lambda s: s.split("-")[0],
              idle_min_s: float = IDLE_MIN_S, running_jobs: dict | None = None) -> dict:
    """The worker the test session runs on. Never one with any running game (the operator's above all: launch_game
    keeps one game per node and would close it), never an unticked or busy one, a Windows PC only when nobody has
    touched it for idle_min_s (auto). Raises EvidenceError listing why each candidate was refused."""
    running_jobs = running_jobs or {}
    live = [s for s in live_sessions if s.get("state") == "running" and s.get("session_id")]
    why: list[str] = []

    def refuse(w: dict, explicit: bool) -> str | None:
        name = w.get("name") or w.get("id")
        if required_os and w.get("os") != required_os:
            return f"{name} is {w.get('os') or 'unknown-OS'}; this game needs a {required_os} worker"
        if not w.get("online"):
            return f"{name} is offline"
        missing = needs - set(w.get("tools") or [])
        if missing:
            return f"{name} can't run {', '.join(sorted(missing))}"
        if w.get("background_testing") is False:
            return f"{name} is unticked for background testing (Tasks menu)"
        games = [s for s in live if worker_of(s["session_id"]) == w.get("id")]
        if games:
            g = games[0]
            return f"{name} is running {g.get('title') or g.get('game_id') or 'a game'} ({g['session_id']})"
        busy = running_jobs.get(w.get("id"), 0) or w.get("active_jobs") or 0
        if busy:
            return f"{name} is busy with {busy} job(s) (evidence captures run at low priority)"
        if w.get('admission', {}).get('allowed') is False:
            return f"{name}: {w['admission'].get('reason') or 'background admission deferred'}"
        if w.get("os") == "windows":
            idle = w.get("idle_seconds")
            if idle is None and not explicit:
                return f"{name} reports no input idle time (can't tell whether someone is using it)"
            if idle is not None and idle < idle_min_s:
                return f"{name} was used {int(idle)} s ago (needs {int(idle_min_s)} s idle)"
        return None

    node = (node or "auto").strip()
    if node not in ("auto", "", "windows", "linux"):
        w = next((w for w in workers if node.lower() in (str(w.get("name", "")).lower(), str(w.get("id", "")).lower())),
                 None)
        if w is None:
            raise EvidenceError(f"no gBox worker named {node}")
        reason = refuse(w, True)
        if reason:
            raise EvidenceError(f"Can't capture on {node}: {reason}. Nothing was started.")
        return w
    if required_os and node in ("windows", "linux") and node != required_os:
        raise EvidenceError(f"Can't capture on {node}: this game needs a {required_os} worker. Nothing was started.")
    oses = [required_os] if required_os else ([node] if node in ("windows", "linux") else (prefer_os or ["windows", "linux"]))
    for os_ in oses:
        cands = [w for w in workers if w.get("os") == os_]
        ok = []
        for w in cands:
            reason = refuse(w, False)
            (why.append(reason) if reason else ok.append(w))
        if ok:
            return max(ok, key=lambda w: w.get("idle_seconds") or 0)   # the longest-idle PC first
    raise EvidenceError("No idle node can run an evidence capture right now: " + ("; ".join(why) or
                        f"no {'/'.join(oses)} worker is registered") + ". Nothing was started.")


# ------------------------------------------------------------------------------------------------ the capture

def resolve_moment(moment, *, mod_card=None) -> dict | None:
    """load_moment / recipe moment -> {"artifact": sha} | {"slot": n, "worker": w} | None (boot)."""
    if moment in (None, "", "none") or (isinstance(moment, dict) and moment.get("kind") == "none"):
        return None
    if isinstance(moment, str):
        if _is_sha(moment):
            return {"artifact": moment}
        raise EvidenceError(f"load_moment {moment!r}: give an artifact sha256, {{slot, worker}}, {{mod_card}} or 'none'")
    m = dict(moment)
    kind = m.get("kind") or ("artifact" if m.get("artifact") else "slot" if m.get("slot") is not None
                             else "mod_card" if m.get("mod_card") else "")
    if kind in ("artifact", "recorded"):
        if not _is_sha(m.get("artifact")):
            raise EvidenceError("the moment's artifact is not a sha256 state export")
        return {"artifact": m["artifact"], "label": m.get("label", "")}
    if kind == "slot":
        return {"slot": int(m["slot"]), "worker": m.get("worker") or "", "label": m.get("label", "")}
    if kind == "mod_card":
        card = mod_card(m["mod_card"]) if mod_card else None
        if not card or card.get("state_slot") is None:
            raise EvidenceError(f"mod card {m['mod_card']} links no saved moment (state_slot)")
        return {"slot": int(card["state_slot"]), "worker": card.get("worker") or (card.get("session_id") or "").split("-")[0],
                "label": f"mod card {card.get('title') or m['mod_card']}"}
    raise EvidenceError(f"unknown moment {moment!r}")


def run(inp: EvidenceIn, game: dict, *, run_job, workers, live_sessions, recipes=None, recorded=None, label=None,
        end_session=None, put_artifact=None, read_artifact=None, operator_active=None, mod_card=None,
        running_jobs=None, say=None, should_stop=None, worker_of=lambda s: s.split("-")[0], sleep=time.sleep,
        clock=time.monotonic) -> dict:
    """The capture (module docstring). run_job(tool, input, worker_id, wait, progress=None) -> job output (raises on
    failure); operator_active(worker) -> a reason string when someone started using that node, else None."""
    say = say or (lambda pct, msg: None)
    stopped_by = should_stop or (lambda: False)
    recipes = load_recipes() if recipes is None else recipes
    recipe = recipe_for(inp.game_id, inp.recipe, recipes, recorded)
    steps_boot = [InputStep.model_validate(s) for s in (inp.inputs if inp.inputs is not None else recipe.get("steps") or [])]
    moment_src = inp.load_moment if inp.load_moment is not None else recipe.get("moment")
    if inp.load_moment == "recorded":
        moment_src = recipe.get("moment") if (recipe.get("moment") or {}).get("recorded") else None
        if moment_src is None:
            raise EvidenceError(f"no recorded gameplay moment for {inp.game_id}: record one with POST /api/evidence/moments")
    moment = resolve_moment(moment_src, mod_card=mod_card)
    steps_after = [InputStep.model_validate(s) for s in (recipe.get("after_moment") or [])] if moment else []
    if inp.inputs is not None and moment:
        steps_after = steps_boot                         # explicit inputs run after the explicit moment
    shots = [Shot.model_validate(s) if not isinstance(s, Shot) else s for s in (inp.shots or recipe.get("shots") or [])]
    if len(steps_boot) > MAX_STEPS or len(steps_after) > MAX_STEPS or len(shots) > MAX_SHOTS:
        raise EvidenceError(f"at most {MAX_STEPS} steps and {MAX_SHOTS} shots per capture")
    for st in steps_boot + steps_after:
        if st.tool and (st.tool not in STEP_TOOLS or st.input.get("op") not in STEP_TOOLS[st.tool]):
            raise EvidenceError(f"step tool {st.tool} op {st.input.get('op')} is not allowed (allowed: {STEP_TOOLS})")
    if not shots and not any(s.shot for s in steps_boot + steps_after):
        shots = [Shot(label="gameplay", at_s=2.0)]
    needs = {"launch_game", "get_frame", "session_op"}
    if moment and moment.get("artifact"):
        needs.add("state_transfer")
    if any(s.kind == "scene" for s in shots):
        needs.add("scene_capture")
    needs |= {s.tool for s in steps_boot + steps_after if s.tool}
    node = inp.node
    if moment and moment.get("slot") is not None and moment.get("worker") and node in ("auto", ""):
        node = moment["worker"]                          # a slot lives on the node that saved it
    w = pick_node(node, workers(), live_sessions(), needs=needs, prefer_os=recipe.get("prefer_os"),
                  required_os=required_os(game),
                  worker_of=worker_of, running_jobs=running_jobs() if callable(running_jobs) else running_jobs)
    wid, wname = w["id"], w.get("name") or w["id"]
    title = game.get("title") or inp.game_id
    out = {"game_id": inp.game_id, "mod": inp.mod, "recipe": inp.recipe or "default", "worker": wname, "runs": [],
           "frames": [], "pairs": [], "artifacts": [], "notes": []}
    if inp.game_id not in recipes:
        out["notes"].append(f"no evidence recipe for {inp.game_id} (gbox/evidence_recipes.json): the frames show "
                            "wherever the given inputs lead")
    elif recipe.get("status") in ("needs_state", "todo") and not moment and inp.inputs is None:
        out["notes"].append(f"recipe status {recipe.get('status')}: {recipe.get('todo') or 'no verified way to gameplay yet'}")
    variants = [("mod", inp.mod)] + ([("stock", "")] if inp.compare_stock and inp.mod else [])
    if inp.compare_stock and not inp.mod:
        out["notes"].append("compare_stock ignored: no mod given (this run is already the stock game)")
    for k, (variant, mod) in enumerate(variants):
        span = (5 + 90 * k / len(variants), 90 / len(variants))
        run_rec = _capture_once(variant, mod, game, title, w, moment, steps_boot, steps_after, shots, recipe, inp,
                                run_job=run_job, label=label, end_session=end_session, operator_active=operator_active,
                                say=lambda p, m, s=span, v=variant: say(s[0] + s[1] * p / 100, f"[{v}] {m}"),
                                stopped_by=stopped_by, sleep=sleep, clock=clock)
        out["runs"].append(run_rec)
        for f in run_rec["frames"]:
            out["frames"].append(f | {"run": variant})
            out["artifacts"].append(f["sha256"])
        if run_rec.get("error"):
            out["notes"].append(f"{variant}: {run_rec['error']}")
            if run_rec.get("yielded"):
                break
    if inp.compare_stock and inp.mod and put_artifact and read_artifact:
        from . import evidence_render as ER
        by = {r["variant"]: {f["label"]: f for f in r["frames"] if f.get("kind") == "session screenshot"} for r in out["runs"]}
        for lab, mf in (by.get("mod") or {}).items():
            sf = (by.get("stock") or {}).get(lab)
            if not sf:
                continue
            try:
                png = ER.before_after(read_artifact(sf["sha256"]), read_artifact(mf["sha256"]),
                                      f"{title}: {lab}. Left: stock game; right: {inp.mod}. Same recipe, same node "
                                      f"({wname}). Gameplay and modification not verified.", kind="session screenshot", before_title="Stock",
                                      after_title=f"Mod: {inp.mod}")
                sha = put_artifact(png, f"evidence-{_slug(lab)}.png", "image/png",
                                   {"evidence": TOOL, "game": inp.game_id, "mod": inp.mod, "label": lab,
                                     "kind": "session screenshot", "gameplay_verified": False})
                out["pairs"].append({"label": lab, "stock": sf["sha256"], "mod": mf["sha256"], "composite": sha,
                                     "url": f"/api/artifacts/{sha}", "kind": "session screenshot", "gameplay_verified": False})
                out["artifacts"].append(sha)
            except Exception as e:                        # noqa: BLE001 - a missing pair never loses the frames
                out["notes"].append(f"pair {lab}: {e}")
    if not out["frames"]:
        errs = "; ".join(r.get("error") or "" for r in out["runs"] if r.get("error"))
        raise (Yielded if any(r.get("yielded") for r in out["runs"]) else EvidenceError)(
            f"no frame was captured on {wname}: {errs or 'the session gave no picture'}")
    say(100, f"{len(out['frames'])} frame(s) captured on {wname}; test session(s) stopped")
    return out


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "shot"


def _capture_once(variant, mod, game, title, w, moment, steps_boot, steps_after, shots, recipe, inp, *, run_job,
                  label, end_session, operator_active, say, stopped_by, sleep, clock) -> dict:
    wid, wname = w["id"], w.get("name") or w["id"]
    rec = {"variant": variant, "mod": mod, "session_id": "", "reached": "", "frames": [], "stopped": False,
           "notes": ["Screenshots and completed recipe steps do not verify gameplay or the requested modification."],
           "gameplay_verified": False, "steps_done": 0}

    def guard():
        if stopped_by():
            raise EvidenceError("cancelled by the operator")
        why = operator_active(w) if operator_active else None
        if why:
            raise Yielded(f"yielded: {why}")

    def shoot(lab: str, kind: str = "frame"):
        guard()
        if kind == "scene":
            cap = run_job("scene_capture", {"session_id": nsid, "frames": 2}, wid, 900)
            rec["frames"].append({"label": lab, "sha256": cap.get("glb"), "kind": "scene capture (GLB)",
                                  "url": f"/api/artifacts/{cap.get('glb')}"})
            return
        fr = run_job("get_frame", {"session_id": nsid}, wid, 45)
        f = {"label": lab, "sha256": fr["sha256"], "url": f"/api/artifacts/{fr['sha256']}", "kind": "session screenshot", "gameplay_verified": False,
             "width": fr.get("width"), "height": fr.get("height"), "mean_luma": fr.get("mean_luma"),
             "covered": fr.get("covered", 0), "capture_source": fr.get("capture_source"),
             "capture_occlusion": fr.get("capture_occlusion", "unknown"), "t": round(clock() - t_launch, 1)}
        if f["mean_luma"] is not None and f["mean_luma"] <= DARK_LUMA:
            f["dark"] = True
            rec["notes"].append(f"{lab}: the frame is black (loading or not drawing)")
        rec["frames"].append(f)

    def do_step(st: InputStep, k: int):
        guard()
        if st.tool:
            run_job(st.tool, {**st.input, "session_id": nsid}, wid, 120)
        elif st.press:
            for _ in range(max(1, min(int(st.repeat), 50))):
                ev = [{"key": b, "down": True} for b in st.press]
                run_job("session_op", {"session_id": nsid, "op": "send_input", "args": {"events": ev}}, wid, 30)
                sleep(max(0.03, min(st.hold_s, 5.0)))
                ev = [{"key": b, "down": False} for b in st.press]
                run_job("session_op", {"session_id": nsid, "op": "send_input", "args": {"events": ev}}, wid, 30)
                if st.repeat > 1:
                    sleep(max(0.05, min(st.wait_s, MAX_WAIT_S)))
        if st.wait_s and not (st.press and st.repeat > 1):
            sleep(max(0.0, min(st.wait_s, MAX_WAIT_S)))
        rec["steps_done"] = k + 1
        if st.shot:
            shoot(st.shot)
        for s in shots:
            if s.after_inputs is not None and (s.after_inputs == k or (st.label and s.after_inputs == st.label)):
                shoot(s.label, s.kind)

    nsid, t_launch = "", clock()
    say(2, f"Starting {title} ({mod or 'stock'}) on {wname} as an agent test session")
    try:
        guard()
        launched = run_job("launch_game", {"game": game, "mod": mod, "debug": bool(inp.debug)}, wid, LAUNCH_WAIT_S)
        nsid = launched["session_id"]
        rec["session_id"], rec["adapter"] = nsid, launched.get("adapter")
        t_launch = clock()
        if label:
            try:
                label(nsid, {"label": f"Evidence capture: {title} ({mod or 'stock'})", "owner": "agent"})
            except Exception:                             # noqa: BLE001
                pass
        boot = inp.boot_s if inp.boot_s is not None else float(recipe.get("boot_s") or BOOT_SETTLE_S)
        sleep(max(0.0, min(boot, 180.0)))
        steps = steps_boot
        if moment:
            guard()
            say(20, f"Loading the moment ({moment.get('label') or 'saved state'})")
            if moment.get("artifact"):
                res = run_job("state_transfer", {"session_id": nsid, "op": "import", "artifact": moment["artifact"]},
                              wid, 120).get("result") or {}
                if res.get("load_verified") is False:
                    rec["notes"].append("state import requested but the emulator did not confirm the load")
            else:
                run_job("session_op", {"session_id": nsid, "op": "load_state", "args": {"slot": moment["slot"]}}, wid, 60)
            sleep(LOAD_SETTLE_S)
            rec["reached"] = "moment"
            steps = steps_after
        else:
            rec["reached"] = "boot"
        say(35, f"{len(steps)} input step(s) in the capture recipe")
        for k, st in enumerate(steps):
            do_step(st, k)
        if steps:
            rec["reached"] += "+steps"
        t0 = clock()
        timed = sorted((s for s in shots if s.after_inputs is None), key=lambda s: s.at_s or 0.0)
        for s in timed:
            wait = (s.at_s or 0.0) - (clock() - t0)
            if wait > 0:
                sleep(min(wait, MAX_WAIT_S))
            say(80, f"Capturing {s.label}")
            shoot(s.label, s.kind)
    except Yielded as e:
        rec["error"], rec["yielded"] = str(e), True
    except EvidenceError as e:
        rec["error"] = str(e)
    except Exception as e:                                # noqa: BLE001 - reported, the session is still closed
        rec["error"] = f"{type(e).__name__}: {str(getattr(e, 'detail', None) or e)[:300]}"
    finally:
        if nsid:
            say(96, "Stopping the test session")
            try:
                run_job("session_op", {"session_id": nsid, "op": "stop_game", "args": {}}, wid, 60)
                rec["stopped"] = True
            except Exception as e:                        # noqa: BLE001
                rec["notes"].append(f"stop_game: {e}")
            if end_session:
                try:
                    end_session(nsid)
                    rec["stopped"] = True
                except Exception:                         # noqa: BLE001
                    pass
    return rec
