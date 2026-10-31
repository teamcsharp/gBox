"""MCP server: drive gBox from Claude Desktop / Claude Code / other agents.

Every registry tool is exposed as job_<name> (runs as a gBox job, returns its output), plus conveniences
(library, launch, sessions, memory peek, the gBox chat agent, KB, recipes) and two resources.
stdio by default; serve_http() puts the same server on streamable HTTP behind the control plane's bearer token.
"""
import asyncio
import base64
import hmac
import json
import os
import time

import httpx
import mcp_types as T
from mcp.server.lowlevel import Server

from . import hermes_merges, hermes_tasks
from . import mcp_bot_controls as BC
from . import merc_live_controls as LC
from .mercs import directives as bot_directives

READY_LIMIT = 25        # ready_to_verify entries list_requests returns (#1308)
S, I, B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
ADDR = {"type": ["string", "integer"], "description": "hex string (0x80001234) or integer"}
PREFIX = "job_"                                   # registry tools; unprefixed names are the conveniences below
JOB_WAIT_SECONDS = 25  # Return a durable job ID before the agent's MCP watchdog fires.


def obj(props, req=()):
    return {"type": "object", "properties": props, "required": list(req)}


def _job_input_defaults(value, schema):
    """Compare omitted fields with the declared defaults the HTTP validator stores."""
    if not isinstance(value, dict):
        return value
    properties = schema.get('properties', {}) if isinstance(schema, dict) else {}
    defaults = {key: field['default'] for key, field in properties.items()
                if isinstance(field, dict) and 'default' in field}
    return defaults | value


def _generic_job_body(arguments, schema):
    """Recover misplaced routing metadata only when the tool schema proves it is not tool input."""
    body = {k: arguments[k] for k in ('tool', 'input', 'require_os', 'require_worker', 'parent_request_id')
            if k in arguments}
    body['input'] = dict(body.get('input') or {})
    properties = schema.get('properties') if isinstance(schema, dict) else None
    if isinstance(properties, dict) and schema.get('type') == 'object':
        for key in ('require_os', 'require_worker', 'parent_request_id'):
            if key not in body['input'] or key in properties:
                continue
            value = body['input'].pop(key)
            if key in body and body[key] != value:
                raise ValueError(f'Conflicting {key}; put one routing value beside tool and input.')
            body[key] = value
    body['agent_use'] = True
    if sid := body['input'].get('session_id'):
        body['require_worker'] = sid.split('-')[0]
    return body


METRIC_FIELDS = {
    "model": S, "provider": S, "system": S, "tokens_in": I, "tokens_out": I,
    # SDK token metadata also contains strings, nested objects and null costs.
    "tokens_detail": {"type": "object", "additionalProperties": True},
    "tools": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0},
              "description": "Tool name -> exact nonnegative integer call count. Omit unknown counts; do not use estimates or descriptive strings."},
    "files_changed": {"type": "array", "items": S}, "turns": I,
    "duration_s": {"type": "number"},
}


SOLVER_FIELDS = {
    "service": {"type": "string", "minLength": 1, "maxLength": 80},
    "model": {"type": "string", "maxLength": 160},
    "system": {"type": "string", "maxLength": 80},
    "verified_by": {"type": "string", "maxLength": 80,
                    "description": "Short reviewer identity, at most 80 characters. Put test details in verification or note."},
    "verification": {"type": "string", "minLength": 1, "maxLength": 2000,
                     "description": "Actual acceptance evidence, at most 2000 characters. Put longer evidence in note or reply_request."},
    "run_id": {"type": ["string", "null"], "maxLength": 80},
}


def _request_status(arguments):
    """Check solver credit against the HTTP contract without truncating evidence."""
    payload = {"status": arguments["status"], "note": arguments.get("note", "")}
    solver = arguments.get("solved_by")
    if solver is None:
        return payload
    if not isinstance(solver, dict):
        raise ValueError("solved_by must be an object")
    if payload["status"] != "done":
        raise ValueError("solved_by is only valid for done after the full request is verified; "
                         "keep partial results in note or reply_request")
    for name, schema in SOLVER_FIELDS.items():
        if name not in solver and name not in ("service", "verification"):
            continue
        value = solver.get(name)
        if name == "run_id" and value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"solved_by.{name} must be a string")
        if len(value) < schema.get("minLength", 0):
            raise ValueError(f"solved_by.{name} must not be empty")
        if len(value) > schema["maxLength"]:
            destination = "verification (up to 2000 characters) or note" if name == "verified_by" else "note or reply_request"
            raise ValueError(f"solved_by.{name} exceeds {schema['maxLength']} characters; "
                             f"use a concise value and preserve the full evidence in {destination}")
    payload["solved_by"] = solver
    return payload


def _request_metrics(arguments):
    """Merge supported flat/nested forms, rejecting invalid counters before HTTP."""
    nested = arguments.get("metrics", {})
    if not isinstance(nested, dict):
        raise ValueError("metrics must be an object")
    for source, prefix in ((arguments, ""), (nested, "metrics.")):
        if "tools" not in source:
            continue
        tools = source["tools"]
        if not isinstance(tools, dict):
            raise ValueError(f"{prefix}tools must be an object of exact nonnegative integer call counts")
        for name, count in tools.items():
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError(f"{prefix}tools.{name} must be an exact nonnegative integer call count; "
                                 "omit unavailable counts instead of estimating")
    metrics = {k: v for k, v in arguments.items() if k not in ("request_id", "metrics")}
    metrics.update(nested)
    return metrics


def _request_receipt(report, request_id):
    """Keep the mutation acknowledgement without re-feeding request history."""
    return {"ok": True, "request_id": request_id, "id": report.get("id", request_id),
            "number": report.get("number"), "status": report.get("status")}


CONVENIENCE = {
    "prepare_task_workspace": ("Create or reuse an isolated Git worktree for this inbox request. Edit the returned workdir, preserving earlier patches. Never edit the shared runtime source concurrently.",
                               obj({'request_id': S}, ['request_id'])),
    "publish_task_changes": ("Validate explicit files in this request's Git workspace, commit, push and create or update a draft GitHub PR. Python changes require focused tests. Returns real commit and PR URL and posts them to the report. This does not close the ticket or deploy to a PC.",
                             obj({'request_id': S, 'title': S, 'files': {'type': 'array', 'items': S},
                                  'tests': {'type': 'array', 'items': S}}, ['request_id', 'title', 'files'])),
    "get_dispatch_feedback": ("Read durable failure lessons and model cooldowns from actual Hermes executions. Use these to change the next attempt, not repeat a failed step.", obj({})),
    "get_game_work_queue": ("Read the persistent favorite and requested-game character-replacement queue. Supply any game_id for an engineering plan with stage-specific reader/writer checks and reusable playbooks, plus existing exact-build checkpoints. Reading an unqueued game does not enqueue it or imply support. A completed agent run is not game readiness.", obj({"game_id": S})),
    "record_game_work": ("Checkpoint the assigned favorite game's inventory, analysis, reader, writer or native gameplay verification. Verified stages require stored artifact hashes and the same owned-source hash; runtime also requires an actual gameplay image. Partial/blocked checkpoints preserve the next step.",
                         obj({"game_id": S, "request_id": S, "stage": {"type": "string", "enum": ["inventory", "analysis", "reader", "writer", "runtime"]},
                              "status": {"type": "string", "enum": ["partial", "verified", "blocked"]}, "note": S,
                              "source_sha256": S, "artifacts": {"type": "array", "items": S}, "next_step": S},
                             ["game_id", "request_id", "stage", "status", "note"])),
    "list_tasks": ("List active gBox jobs and actual Hermes runs, including names, run IDs, progress and token usage. Check this before starting inbox work so you do not duplicate another active investigation. include_finished also returns recent terminal runs; a completed run does not prove its inbox request was solved.",
                   obj({"include_finished": B})),
    "list_requests": ("List actionable inbox requests in a compact page, newest first. Recurring review check-ins are hidden unless include_recurring=true; autoplay coaching tickets (live notes for the agents watching a bot demo) are hidden unless include_coaching=true or source=coach. A request marked hermes_capped has had 3 inbox runs in a row with no new operator message: choose another actionable request unless none exists. A request marked hermes_on_main (also listed in ready_to_verify across the whole inbox) already has its published fix on main: verify its acceptance live and close it, or post the exact remaining gap, before starting new work.",
                      obj({"status": S, "source": S, "limit": I, "offset": I, "include_recurring": B, "include_coaching": B})),
    "get_build_feedback": ("Read durable operator reports and image references for a game, including repair findings and exact revisions that later characters builds must acknowledge. Use read_request_artifact with request_id/sha256 to inspect images.",
                           obj({"game_id":S}, ["game_id"])),
    "get_request": ("Read an inbox request, including the operator's full instructions, replies, image and attachment references, and metrics.",
                    obj({"request_id": S}, ["request_id"])),
    "read_request_artifact": ("Read an image or text attachment belonging to an inbox request. Images are returned as image content.",
                              obj({"request_id": S, "sha256": S}, ["request_id", "sha256"])),
    "reply_request": ("Post an agent reply to an inbox request. Use one tool call at a time. State the tested outcome and remaining limitations. text, body, and message are accepted aliases. Returns a compact receipt with the posted message; use get_request for full history.",
                      obj({"request_id": S, "text": S, "body": S, "message": S, "task_step": {"type": "object"}}, ["request_id"])),
    "capture_request_screenshot": ("Capture a real frame from a live game session and attach it to an inbox report, with action, attempt, result, and status. Do this after meaningful visual milestones and verification.",
                                   obj({"request_id": S, "session_id": S, "text": S, "task_step": {"type": "object"}},
                                       ["request_id", "session_id", "text"])),
    "set_request_status": ("Set an inbox request status. Use done only after its full operator request is verified; otherwise keep in_progress. Solver credit is for done only: verified_by is a short reviewer identity (80 characters), verification holds acceptance evidence (2000 characters), and note or reply_request holds longer details.",
                          obj({"request_id": S, "status": {"type": "string", "enum": ["open", "in_progress", "done", "blocked"]},
                               "note": S, "solved_by": obj(SOLVER_FIELDS, ["service", "verification"])}, ["request_id", "status"])),
    "record_request_metrics": ("Record actual, non-duplicated agent token and tool usage on an inbox request. Use one tool call at a time. Fields may be flat or under metrics. tools values must be exact nonnegative integer call counts; omit unavailable counts. Use zero token counts with tokens_detail.token_count_unavailable when exact tokens are unavailable. Returns a compact receipt with stored metrics; use get_request for full history.",
                               obj({"request_id": S, **METRIC_FIELDS,
                                    "metrics": obj(METRIC_FIELDS)}, ["request_id"])),
    "list_games": ("Search the game library (title words). Returns game_id, title, platform, system, core.",
                   obj({"query": S, "platform": S, "limit": I}, ["query"])),
    "list_workers": ("List all gBox computers, online state, idle time, current agent jobs, and available tools.", obj({})),
    "get_broadcast_feeds": ("Discover the current program and every gBox gameplay feed on all PCs, including stable session/PC URLs that follow game restarts, frame rate, freshness, resolution and media formats. Pine Box should relay these gameplay feeds; MJPEG is video only, MPEG-TS/HLS include the isolated emulator audio when available. Read only; never changes the on-air program.", obj({})),
    "get_broadcast_status": ("Read the live broadcast encoders, frame progress, restarts, connected viewers and emulator audio availability. Use this to diagnose lag or silence without interrupting gameplay.", obj({})),
    "select_idle_worker": ("Choose the Windows PC the operator is not using, for a specified tool. Pin later jobs to its returned id.",
                           obj({"tool": S})),
    "capture_worker_screen": ("Capture the other PC's entire desktop as an image. Optionally attach the screenshot and a task step to an inbox request.",
                              obj({"worker": S, "request_id": S, "text": S, "task_step": {"type": "object"},
                                   "region": {"type": "array", "items": I, "minItems": 4, "maxItems": 4}})),
    "list_favorites": ("List favorited games, including ROMs queued for background model collection.", obj({"limit": I})),
    "game_roster": ("Show a game's native model reader, character roster, and background collection job state.",
                    obj({"game_id": S}, ["game_id"])),
    "favorite_unlocks": ("Read or publish evidence-backed unlock metadata for this exact active favorite request. "
                         "Never starts a game or applies a control. Existing server validation rejects incomplete profiles/receipts.",
                         obj({"game_id": S, "request_id": S, "op": {"type":"string", "enum":[
                             "status", "native_profile", "unlock_profile", "manifest", "verify"]},
                              "build": S, "body": {"type":"object"}}, ["game_id", "request_id"])),
    "start_job": ("Dispatch any gBox registry tool as a background job and return its ID immediately. Use require_worker=idle to choose the other Windows PC, then pin later work to its worker_id.",
                  obj({"tool": S, "input": {"type": "object"}, "require_os": S, "require_worker": S,
                       "parent_request_id": S}, ["tool", "input"])),
    "get_job": ("Read a background gBox job's state, progress, result, and error.", obj({"job_id": S}, ["job_id"])),
    "launch_game": ("Launch a library game. node: idle | auto | windows | linux | <worker name>. idle chooses the other Windows PC; debug=true runs on the Spark "
                    "under a full-debugger emulator. Returns the launch job (its output has the session_id).",
                    obj({"game_id": S, "node": S, "debug": B}, ["game_id"])),
    "get_session_observers": ("Read a session's passive gameplay observations, visible actors, changes, native model collection and repair request IDs, plus goals: what each session agent is trying to do, the evidence it still needs, how the operator can help, what to do if they cannot (if_unavailable) and what blocks it; cannot_help says when a character swap/pick test cannot run because none of the game's characters are collected yet. Hypotheses are not verified game mechanics.", obj({"session_id": S}, ["session_id"])),
    "list_sessions": ("Game sessions (session_id, title, adapter, state, last_frame_age). Live ones only unless include_ended.",
                      obj({"include_ended": B})),
    # The Mercenaries autobot and the RAM mods as first-class tools (operator 2026-10-26, request #3889)
    "bot_sessions": ("The running game sessions, each with its PC (host) and the Mercenaries autobot's live summary from the autoplay "
                     "telemetry (running, phase, screen, rounds, kills, directive and directive_status, mines cadence, team role) and "
                     "which mod tool the game takes (mod_tool: re5_mods for Resident Evil 5, re_mods for Resident Evil 4). Use it to "
                     "find the session_id for bot_directive, game_mod and bot_strategy. Read only.", obj({})),
    "bot_directive": ("An instant command for the session's Mercenaries autobot (RE4 and RE5; acted on within a second; every normal "
                      "safeguard stays in force, the command only changes what the bot decides). command: fight (standing 15 s: fight the "
                      "foes in sight instead of standing there), next_area (one-shot: leave this goal for the next time bonus / area), "
                      "explore (15 s: reset the route and cover more of the level), hunt (20 s: seek, find and dispatch the enemies), "
                      "score (20 s: build the combo), repetitive (8 s: drop the repeated action, back off, go forward), mine (RE5 one-shot: "
                      "plant one proximity bomb at the next safe spot, then leave it; needs game_mod op=mines on), mine_trail (RE5 standing "
                      "45 s: drop a mine, move at least 6 m on, repeat while leaving the area; the mine controller still decides every "
                      "placement), missing (one-shot: adjust the aim for this weapon). RE4 has no mines: mine / mine_trail report that. Or "
                      "text: free words matched to a command (\"drop landmines while fleeing\" -> mine_trail, \"go to the next time "
                      "bonus\" -> next_area); unmatched text is an error, nothing is sent. hold_s (0 .. 600) overrides how long a standing "
                      "mode lasts. Returns the stored directive row; bot_sessions shows directive_status as the bot acts.",
                      obj({"session_id": S, "command": {"type": "string", "enum": list(bot_directives.COMMANDS)}, "text": S,
                           "hold_s": {"type": "number", "minimum": 0, "maximum": 600}}, ["session_id"])),
    "game_live_controls": ("Read or adjust the selected active MercMode run through its bounded live control inventory. "
                           "status returns current mod sliders, behavior knobs and native flash/weapon capabilities. "
                           "set takes a control ID from that inventory and a bounded value. Native clicks require a fresh UUID. "
                           "A pending_job must be polled with status/job_id, never resubmitted. Operator actions preserve playback audio.", LC.SCHEMA),
    "live_run_map": ("Read the current Mercenaries map and stream session on a computer. Follows title changes and ignores warmed/preparing sessions. "
                     "Pass worker name/id, or a session_id on that computer. Returns current tactical data and a relative live-map page for viewer/PiP embedding. "
                     "Call again to refresh; the page follows the active run automatically.",
                     obj({"worker":S,"session_id":S})),
    "game_intervention": ("Viewer/operator native intervention for the active stream. op=status returns available capabilities and recent receipts. "
                          "op=flash_now creates and detonates a native flash at the player's position without inventory, input or weapon changes. "
                          "op=equip_primary uses a weapon item ID offered in status.options.weapons to replace the main weapon now, "
                          "with a two-minute bot swap lock and a preference for the current match. "
                          "op=magnum_quick4 equips a loaded magnum and performs four observed quick shots on supported RE6 only; "
                          "an interrupted or unobserved action stops with a partial/uncertain receipt and is never replayed. "
                          "op=grenade_ring (RE5 Switch) spawns ten grenades in a ring that blooms out from the player and detonates "
                          "them; kind selects the grenade (flash, the default and the only verified type; hand and incendiary are "
                          "refused with a reason until verified). Provide a new UUID request_id for each click; reuse that UUID only "
                          "when retrying that same request. "
                          "Queued does not mean detonated: poll status until confirmed or an explicit failure. "
                          "Unsupported title/build/resources are reported without substituting a grenade throw.",
                          obj({"session_id": S, "op": {"type":"string", "enum":["status", "flash_now", "equip_primary", "magnum_quick4", "grenade_ring"]},
                               "request_id": S, "item": {"type":"integer", "minimum":1, "maximum":255},
                               "kind": {"type":"string", "enum":["flash", "hand", "incendiary"]}}, ["session_id", "op"])),
    "game_mod": ("Apply one live RAM mod to the session's game on its own PC and wait for the read-back. The tool follows the game: "
                 "re5_mods (Resident Evil 5 Gold, PS3) or re_mods (Resident Evil 4, GameCube / Wii); game_mod_ops lists every op with "
                 "its params, allowed values and when it takes effect. params holds that tool's own fields only (RE5: multiplier, on, "
                 "mode, character, stage, weapon, only; RE4: item, count, target, on, seconds, threshold, character, items, fire_rate, "
                 "damage, reset, multiplier, melee_only, kind, force, direction, speed, seed, guns); any other field is rejected rather "
                 "than silently dropped. Examples: RE5 weapon_override {weapon: 0x1A, only: true}; RE5 fire_rate {multiplier: 80}; RE5 "
                 "mines {on: true, multiplier: 30}; RE4 random_loadout {character: \"all\", damage: 99.9}; RE4 spawn_multiplier {count: 3}. "
                 "Returns the job (output.result carries verified and the tool's status); a job still running after 25 s comes back "
                 "with its id for get_job. Writes to the operator's live game: use it for what the operator asked.",
                 obj({"session_id": S, "op": S, "params": {"type": "object"}, "tool": {"type": "string", "enum": list(BC.MOD_TOOLS)}},
                     ["session_id", "op"])),
    "game_mod_ops": ("The ops game_mod accepts for the session's game (or for tool=re5_mods | re_mods without a session): each op's "
                     "params with allowed values, its effect, when it takes effect (now / next round / next menu) and whether the tool "
                     "retains it as the operator's setting for the session.",
                     obj({"session_id": S, "tool": {"type": "string", "enum": list(BC.MOD_TOOLS)}})),
    "bot_strategy": ("Change what the bot plays with for the rest of the session. settings.mods: [{op, ...params}] of the ops the "
                     "title's tool retains as the operator's setting, which the bot's round hooks then apply instead of their package "
                     "defaults (RE5: fire_rate, turn_speed, bullet_damage, infinite_ammo, unlimited_health, kill_time, infinite_spray, "
                     "instant_qte, mines, rotten_egg_only, weapon_override; RE4: unlimited_health, infinite_ammo, combo_freeze, "
                     "merc_timer_freeze, grenade_safe, merc_time_bonus, combo_time, aim_turn_speed, spawn_multiplier, random_loadout, "
                     "merc_loadout, mercenaries_unlock; an RE4 operator loadout also makes the bot skip its own per-round random draw). "
                     "settings.mercmode: {enabled, titles [re4|re5|re6], rounds_per_title 1..20, presentation_priority, keep_warm 0..2, "
                     "queue, preferred_editions} for the session's PC (POST /api/mercmode; host defaults to that PC). settings.team "
                     "(RE5 / RE6): {role solo_p1|teammate_p2|observe_human, training_profile assisted|unmodified_evaluation, "
                     "auto_reduce_mods, selected_route_id} (mercs_team configure). With empty settings it returns the options, the PC's "
                     "current MercMode settings and what is NOT settable at runtime (the RE5 Policy constants such as "
                     "critical_radius_cm / boss_delay_combo, the RE4 package radii, the profile's playing_ops).",
                     obj({"session_id": S, "settings": {"type": "object"}}, ["session_id"])),
    "spawn_enemies": ("NOT available yet: spawning chosen enemies (or waves) at a stage's spawn points has no verified spawn address in "
                      "Resident Evil 4 or 5; RE4's spawn_multiplier only clones the enemies the game spawns itself. The tool sends no "
                      "input and returns {supported: false, reason, ticket} where ticket is the number of the open inbox request "
                      "tracking the work (null when none is filed), so callers can follow it there.",
                      obj({"session_id": S, "enemy": S, "count": I, "spawn_point": S})),
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

    async def live_control_post(path, body):
        # These bounded calls come from the operator's live panel. The core marks
        # actor=mcp jobs as agent work even when agent_use is false (audio ducking).
        r = await api.post(path, json=body, headers={"x-gbox-actor": "pine-live-controls"})
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code}: {r.text[:500]}")
        return r.json()

    live_controls = LC.Controls(get, live_control_post)

    async def _capped_requests(rows=None):
        """Open tickets the inbox job has taken STREAK_CAP runs in a row (#1300 gap 3).

        Advisory only: any failure returns {} so listing requests never breaks."""
        try:
            runs = (await get('/api/tasks', hermes_limit=20)).get('hermes') or []
            if not hermes_tasks.ticket_streaks(runs):
                return {}
            if rows is None:
                rows = await get('/api/requests', status='open,in_progress')
            last = {r['id']: max([m.get('ts') or 0 for m in r.get('messages') or []
                                  if m.get('author') == 'operator'] or [0.0]) for r in rows}
            return {rid: s for rid, s in hermes_tasks.ticket_streaks(runs, last).items() if rid in last}
        except Exception:
            return {}

    def _on_main_requests(rows):
        """Listed tickets whose published branch is fully on main (#1308); {} on any error."""
        try:
            listed = {r["id"] for r in rows}
            return {rid: sha for rid, sha in hermes_merges.on_main_requests().items() if rid in listed}
        except Exception:
            return {}

    async def wait_job(job, timeout):
        async def poll():
            nonlocal job
            while job.get('state') in ('queued', 'running'):
                await asyncio.sleep(1)
                job = await get(f"/api/jobs/{job['id']}")
        if timeout > 0:
            try:
                await asyncio.wait_for(poll(), timeout=timeout)
            except asyncio.TimeoutError:
                pass  # Retain the last durable state even if an HTTP poll stalls.
        out = {k: job.get(k) for k in ("id", "tool", "state", "worker_id", "output", "error")}
        if out['state'] in ('queued', 'running'):
            out['next_action'] = 'Use get_job with this id; do not submit this operation again. If the worker is unavailable, preserve the job and continue source work.'
        return out

    async def select_background_worker(tool):
        protected = os.environ.get('GBOX_OPERATOR_WORKER')
        assigned = os.environ.get('GBOX_TEST_WORKER')
        if not protected:
            return await get('/api/workers/idle', tool=tool)
        candidates = [w for w in await get('/api/workers') if w.get('online') and w.get('os') == 'windows'
                      and protected not in (w.get('id'), w.get('name')) and tool in w.get('tools', [])
                      and w.get('background_testing', True)                       # unticked in the Tasks menu (#1383)
                      and ((assigned and assigned in (w.get('id'), w.get('name'))) or
                           (not assigned and w.get('idle_seconds') is not None and w['idle_seconds'] >= 60))
                      and w.get('active_jobs', 0) < 4]
        if not candidates:
            raise RuntimeError('No idle test worker is available outside the protected operator PC. Continue source work.')
        chosen = max(candidates, key=lambda w: w.get('idle_seconds') or 0)
        if tool == 'launch_game' and any((s.get('session_id') or '').startswith(chosen['id'] + '-')
                                        for s in await sessions()):
            raise RuntimeError('The test PC already has a live game; preserve it and continue source work.')
        return chosen | {'operator_worker_id': protected, 'selection': 'configured test PC' if assigned else 'protected operator PC excluded'}

    async def start_background(body):
        if body['tool'] not in registry:
            registry.update({t['name']: t for t in (await get('/api/registry'))['tools']})
        schema = registry.get(body['tool'], {}).get('input_schema') or {}
        if body.get('require_worker') in ('idle', 'other'):
            body = body | {'require_worker': (await select_background_worker(body['tool']))['id']}
        target = body.get('require_worker')
        worker = None
        if target and target not in ('idle', 'other'):
            workers = await get('/api/workers')
            worker = next((w for w in workers if target in (w.get('id'), w.get('name'))), None)
            from .job_routing import conflict
            if why := conflict(body.get('require_os'), worker):
                raise ValueError(why)
        # Retrying an MCP call must not multiply model swaps on the same session.
        active = await get('/api/jobs', state='queued,running', limit=100)
        for job in active:
            if (job.get('tool') == body['tool']
                    and _job_input_defaults(job.get('input', {}), schema)
                    == _job_input_defaults(body.get('input', {}), schema)
                    and job.get('require_worker') == body.get('require_worker')
                    and job.get('require_os') == body.get('require_os')
                    and job.get('parent_request_id') == body.get('parent_request_id')):
                return job | {'deduplicated': True}
        if target and target not in ('idle', 'other'):
            if not worker or not worker.get('online'):
                raise RuntimeError('Target worker is unavailable. Do not enqueue more requests for it; use an idle worker or continue source work.')
            if worker.get('active_jobs', 0) >= 4:
                raise RuntimeError('Target worker is saturated. Read existing jobs instead of dispatching another operation.')
        return await post('/api/jobs', body)

    async def sessions(include_ended=False):
        return [s for s in await get("/api/sessions") if include_ended or not s.get("ended")]

    async def live_session(sid):
        """The running session row for sid; a clear error (not a worker rejection minutes later) for anything else."""
        row = next((s for s in await get("/api/sessions") if s.get("session_id") == sid), None)
        if row is None:
            raise ValueError(f"unknown session {sid}; bot_sessions lists the live ones")
        if row.get("state") != "running":
            raise ValueError(f"session {sid} is {row.get('state')}, not running; bot_sessions lists the live ones")
        return row

    async def session_job(sid, tool, inp):
        """A job on the session's own worker (the id before the dash), waited for like the job_ tools."""
        body = {"tool": tool, "input": inp, "agent_use": True, "require_worker": sid.split("-")[0]}
        return await wait_job(await start_background(body), JOB_WAIT_SECONDS)

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
        if name == 'favorite_unlocks':
            from .unlock_metadata import run
            return await run(a, get, post)
        if name == 'get_dispatch_feedback':
            from . import hermes_feedback
            data = await asyncio.to_thread(hermes_feedback.scan)
            return {key: data.get(key) for key in ('cooldowns', 'current_route', 'updated_at')} | {'lessons': data.get('lessons', [])[-20:]}
        if name == 'prepare_task_workspace':
            from . import hermes_delivery
            report = await get('/api/requests/' + a['request_id'])
            return await asyncio.to_thread(hermes_delivery.prepare, a['request_id'], report['number'])
        if name == 'publish_task_changes':
            from . import hermes_delivery
            await get('/api/requests/' + a['request_id'])
            out = await asyncio.to_thread(hermes_delivery.publish, a['request_id'], a['title'], a['files'], a.get('tests', []))
            await post('/api/requests/' + a['request_id'] + '/messages', {'author': 'agent',
                'text': f"Published tested task changes: {out['url']}\nCommit: {out['commit']}\n" + '\n'.join(out['checks']),
                'task_step': {'action': 'publish verified source changes', 'attempt': '1',
                              'result': out['url'], 'status': 'finished'}})
            return out
        if name == "list_tasks":
            snapshot = await get('/api/tasks')
            hermes = snapshot.get('hermes', [])
            if not a.get('include_finished'):
                hermes = [r for r in hermes if r.get('state') in ('claimed', 'running')]
            out = {'jobs': snapshot.get('jobs', []), 'hermes': hermes,
                   'completion_note': 'Hermes run completion is separate from verified inbox completion.'}
            capped = await _capped_requests()
            if capped:
                out['capped_requests'] = [{'request_id': rid} | s for rid, s in capped.items()]
            return out
        if name == "list_requests":
            rows = await get("/api/requests", status=a.get("status", "open,in_progress"), source=a.get("source", ""))
            if not a.get("include_recurring"):
                rows = [r for r in rows if not (r.get("title") or "").startswith("gBox request review (recurring")]
            if not a.get("include_coaching") and a.get("source") != "coach":
                # autoplay coaching tickets are live reporting for the agents at the inbox hook, note by note: the
                # bulk Hermes queue never takes them (gbox.hermes_work_queue.is_live_coaching)
                from .hermes_work_queue import is_live_coaching
                rows = [r for r in rows if not is_live_coaching(r)]
            offset, limit = max(0, int(a.get("offset", 0))), max(1, min(int(a.get("limit", 30)), 100))
            capped = await _capped_requests(rows)
            merged = _on_main_requests(rows)
            out = {"total": len(rows), "offset": offset, "items": [
                {"id": r["id"], "number": r.get("number"), "title": r.get("title"), "status": r.get("status"),
                 "source": r.get("source"), "automated": r.get("automated"), "parent_request_id": r.get("parent_request_id"),
                 "created": r.get("created"), "summary": (r.get("body") or "")[:350]}
                | ({"hermes_capped": {"runs": capped[r["id"]]["runs"],
                                      "note": hermes_tasks.capped_note(capped[r["id"]])}} if r["id"] in capped else {})
                | ({"hermes_on_main": {"sha": merged[r["id"]],
                                       "note": hermes_merges.VERIFY_NOTE.format(sha=merged[r["id"]][:12])}}
                   if r["id"] in merged else {})
                for r in rows[offset:offset + limit]]}
            if merged:
                # Whole inbox, not just this page: the oldest merged tickets sit far below the newest chat.
                out["ready_to_verify"] = [
                    {"id": r["id"], "number": r.get("number"), "title": (r.get("title") or "")[:100],
                     "status": r.get("status"), "sha": merged[r["id"]][:12]}
                    | ({"hermes_capped": True} if r["id"] in capped else {})
                    for r in rows if r["id"] in merged][:READY_LIMIT]
            return out
        if name == "get_build_feedback":
            return await get("/api/build-feedback", game_id=a["game_id"])
        if name == "get_request":
            return await get(f"/api/requests/{a['request_id']}")
        if name == "reply_request":
            message = a.get("text") or a.get("body") or a.get("message")
            if not message:
                raise ValueError("reply_request requires text, body, or message")
            report = await post(f"/api/requests/{a['request_id']}/messages",
                                {"author": "agent", "text": message} | ({"task_step": a["task_step"]} if a.get("task_step") else {}))
            messages = report.get("messages") or []
            return _request_receipt(report, a["request_id"]) | {
                "message_count": len(messages), "posted_message": messages[-1] if messages else None}
        if name == "capture_request_screenshot":
            return await post(f"/api/requests/{a['request_id']}/capture",
                              {"session_id": a["session_id"], "text": a["text"], "task_step": a.get("task_step", {})})
        if name == "set_request_status":
            return await post(f"/api/requests/{a['request_id']}/status", _request_status(a))
        if name == "record_request_metrics":
            metrics = _request_metrics(a)
            report = await post(f"/api/requests/{a['request_id']}/metrics", metrics)
            return _request_receipt(report, a["request_id"]) | {"metrics": report.get("metrics")}
        if name == "list_games":
            games = await get("/api/catalog/best", q=a["query"], limit=a.get("limit", 20))
            if a.get("platform"):
                games = [g for g in games if g.get("platform") == a["platform"]]
            return [{k: g.get(k) for k in ("game_id", "title", "platform", "system", "core", "playable")} for g in games]
        if name == "list_workers":
            return await get("/api/workers")
        if name == "get_broadcast_feeds":
            return await get("/api/broadcast/feeds")
        if name == "get_broadcast_status":
            return await get("/api/broadcast")
        if name == "select_idle_worker":
            return await select_background_worker(a.get('tool', 'launch_game'))
        if name == "capture_worker_screen":
            worker = a.get("worker") or "idle"
            if worker in ("idle", "other"):
                worker = (await select_background_worker('get_frame'))['id']
            body = {"tool": "get_frame", "input": {}, "require_worker": worker, "agent_use": True}
            if a.get("region"):
                body["input"]["region"] = a["region"]
            if a.get("request_id"):
                body["parent_request_id"] = a["request_id"]
            return await wait_job(await start_background(body), JOB_WAIT_SECONDS)
        if name == "list_favorites":
            page = await get("/api/catalog", favorites=True, limit=max(1, min(a.get("limit", 100), 1000)))
            return {"total": page["total"], "items": [{k: g.get(k) for k in ("game_id", "title", "platform", "system", "playable")}
                                                     for g in page["items"]]}
        if name == "get_game_work_queue":
            from .hermes_work_queue import snapshot
            return await asyncio.to_thread(snapshot, **a)
        if name == "record_game_work":
            from .hermes_work_queue import checkpoint
            return await asyncio.to_thread(checkpoint, **a)
        if name == "game_roster":
            return await get(f"/api/games/{a['game_id']}/roster")
        if name == "start_job":
            if a['tool'] not in registry:
                registry.update({t['name']: t for t in (await get('/api/registry'))['tools']})
            body = _generic_job_body(a, registry.get(a['tool'], {}).get('input_schema') or {})
            return await start_background(body)
        if name == "get_job":
            return await get(f"/api/jobs/{a['job_id']}")
        if name == "launch_game":
            node = a.get('node', 'auto')
            if node in ('idle', 'other'):
                node = (await select_background_worker('launch_game'))['name']
            job = await post(f"/api/games/{a['game_id']}/launch", node=node, debug=str(a.get("debug", False)).lower())
            return await wait_job(job, JOB_WAIT_SECONDS)
        if name == "list_sessions":
            return await sessions(a.get("include_ended", False))
        if name == "bot_sessions":
            rows, workers = await sessions(), await get("/api/workers")
            out = [BC.session_row(s, await get(f"/api/autoplay/telemetry/{s['session_id']}"), workers) for s in rows]
            return {"sessions": out, "commands": {k: v["label"] for k, v in bot_directives.COMMANDS.items()}}
        if name == "bot_directive":
            await live_session(a["session_id"])
            command = a.get("command")
            if not command:
                command = bot_directives.match(a.get("text") or "")
                if not command:
                    raise ValueError("no command matched the text, nothing sent; the commands: "
                                     + "; ".join(f"{k} = {v['label']}" for k, v in bot_directives.COMMANDS.items()))
            body = {"command": command} | ({"hold_s": a["hold_s"]} if a.get("hold_s") is not None else {})
            out = await post(f"/api/sessions/{a['session_id']}/directive", body)
            return out | {"matched_from_text": not a.get("command"),
                          "note": "the bot reads it within a second; bot_sessions shows directive_status while it acts"}
        if name == "game_live_controls":
            return await live_controls.call(a)
        if name == "live_run_map":
            from urllib.parse import urlencode
            worker, seed = a.get("worker"), a.get("session_id")
            if not worker and not seed:
                raise ValueError("Choose worker or session_id so the map follows the intended computer")
            rotation = await get("/api/mercmode")
            host = next((h for h in rotation.get("hosts", []) if h.get("online") and
                         (worker in (h.get("id"), h.get("name")) if worker else str(seed).startswith(str(h.get("id"))+"-"))), None)
            run = (host or {}).get("current_run") or {}
            if run.get("phase") != "playing":
                return {"state":"waiting", "worker":worker, "reason":"No active Mercenaries round on the selected computer"}
            sid = run["session_id"]
            session = await live_session(sid)
            if not sid.startswith(host["id"]+"-") or session.get("game_id") != run.get("game_id"):
                raise ValueError("Active session identity changed; refresh the map")
            frame = await get(f"/api/autoplay/tactical/{sid}")
            return {"state":"playing", "worker":host["name"], "session_id":sid, "map":frame,
                    "viewer_path":"/mercs-live.html?"+urlencode({"worker":host["id"]}),
                    "stream_path":f"/api/sessions/{sid}/mjpeg", "interventions_path":f"/api/sessions/{sid}/interventions"}
        if name == "game_intervention":
            if a.get('op') == 'magnum_quick4' and set(a) - {'session_id', 'op', 'request_id'}:
                raise ValueError('magnum_quick4 accepts only session_id and a fresh request_id')
            sid = a["session_id"]
            if a["op"] == "status":
                return await get(f"/api/sessions/{sid}/interventions")
            if not a.get("request_id"):
                raise ValueError("request_id must be a new UUID for each intended effect")
            payload = {"op": a["op"], "request_id": a["request_id"]}
            if a['op'] == 'equip_primary':
                payload['args'] = {'item': a.get('item')}
            if a['op'] == 'grenade_ring':
                payload['args'] = {'kind': a.get('kind', 'flash')}
            return await post(f"/api/sessions/{sid}/interventions", payload)
        if name == "game_mod":
            session = await live_session(a["session_id"])
            tool = BC.mod_tool_for(session, a.get("tool"))
            inp = BC.mod_input(tool, a["session_id"], a["op"], a.get("params"), session=session)
            return await session_job(a["session_id"], tool, inp) | {"mod_tool": tool, "op": inp["op"]}
        if name == "game_mod_ops":
            tool = a.get("tool")
            session = None
            if a.get("session_id"):
                session = await live_session(a["session_id"])
                tool = BC.mod_tool_for(session, tool)
            return BC.describe_ops(tool, session=session) if tool else {t: BC.describe_ops(t) for t in BC.MOD_TOOLS}
        if name == "bot_strategy":
            session = await live_session(a["session_id"])
            try:
                tool = BC.mod_tool_for(session)
            except ValueError:
                tool = None
            wid = a["session_id"].split("-")[0]
            host = next((w.get("name") for w in await get("/api/workers") if w.get("id") == wid), None)
            settings = a.get("settings") or {}
            if not settings:
                hosts = (await get("/api/mercmode")).get("hosts") or []
                mine = next((h for h in hosts if h.get("name") == host), None)
                return {"session_id": a["session_id"], "host": host, "mod_tool": tool, "options": BC.strategy_options(tool),
                        "mercmode_current": (mine or {}).get("settings"), "mercmode_settings_source": (mine or {}).get("settings_source")}
            applied = []
            for kind, payload in BC.strategy_plan(tool, session, settings):
                if kind == "mod":
                    applied.append({"kind": "mod", "op": payload["op"], "job": await session_job(a["session_id"], tool, payload)})
                elif kind == "mercmode":
                    target = payload.pop("host", None) or host
                    if not target:
                        raise ValueError("the session's PC is not a registered worker; pass settings.mercmode.host")
                    status = await post("/api/mercmode", {"host": target} | payload)
                    mine = next((h for h in status.get("hosts") or [] if h.get("name") == target), None)
                    applied.append({"kind": "mercmode", "host": target, "desired_settings": (mine or {}).get("desired_settings"),
                                    "settings": (mine or {}).get("settings"), "settings_source": (mine or {}).get("settings_source")})
                else:
                    applied.append({"kind": "team", "job": await session_job(a["session_id"], "mercs_team", payload)})
            return {"applied": applied, "not_settable": BC.NOT_SETTABLE}
        if name == "spawn_enemies":
            tool = None
            if a.get("session_id"):                     # the ticket for this session's title, when one is filed
                row = next((s for s in await get("/api/sessions") if s.get("session_id") == a["session_id"]), None)
                try:
                    tool = BC.mod_tool_for(row) if row else None
                except ValueError:
                    tool = None
            found = BC.spawn_tickets(await get("/api/requests", status="open,in_progress"), tool)
            return {"supported": False, "reason": BC.SPAWN_REASON, **found,
                    "available_instead": {"re_mods": "game_mod op=spawn_multiplier params={count: 2..8}: every enemy the game spawns "
                                                     "gets clones (not a chosen enemy at a chosen point)",
                                          "re5_mods": "no spawn write; bot_directive command=hunt sends the bot to the spawn points it knows"},
                    "requested": {k: a[k] for k in ("session_id", "enemy", "count", "spawn_point") if a.get(k) is not None}}
        if name == "get_session_observers":
            return await get(f"/api/sessions/{a['session_id']}/observers")
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
            if name == "read_request_artifact":
                req = await get(f"/api/requests/{a['request_id']}")
                digest = a["sha256"]
                refs = {req.get("image"), *(att.get("sha256") for msg in req.get("messages", [])
                                             for att in msg.get("attachments", []))}
                if digest not in refs:
                    raise ValueError("artifact does not belong to this request")
                r = await api.get(f"/api/artifacts/{digest}")
                r.raise_for_status()
                media = r.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
                if media.startswith("image/"):
                    return T.CallToolResult(content=[T.ImageContent(data=base64.b64encode(r.content).decode(),
                                                                     mime_type=media)])
                if media.startswith("text/") or media == "application/json":
                    body = r.content[:60_000].decode("utf-8", "replace")
                    if len(r.content) > 60_000:
                        body += f"\n[truncated; {len(r.content)} bytes total]"
                    return T.CallToolResult(content=[T.TextContent(text=body)])
                return T.CallToolResult(content=[T.TextContent(text=f"Attachment {digest}: {media}, {len(r.content)} bytes; binary preview unavailable")])
            if name == "capture_worker_screen":
                out = await convenience(name, a)
                if out.get('state') in ('queued', 'running'):
                    return T.CallToolResult(content=[T.TextContent(text=json.dumps(out))])
                if out.get("state") != "succeeded":
                    raise RuntimeError(out.get("error") or f"capture job {out.get('state')}")
                digest = out["output"]["sha256"]
                r = await api.get(f"/api/artifacts/{digest}")
                r.raise_for_status()
                if a.get("request_id"):
                    await post(f"/api/requests/{a['request_id']}/messages", {"author": "agent",
                        "text": a.get("text") or "Desktop screenshot from the test computer",
                        "attachments": [{"name": f"worker-{out.get('worker_id')}-desktop.png", "type": "image/png",
                                         "b64": base64.b64encode(r.content).decode()}],
                        "task_step": a.get("task_step") or {"action": "capture remote desktop", "attempt": "1",
                                                      "result": digest, "status": "finished"}})
                return T.CallToolResult(content=[T.TextContent(text=json.dumps({"job_id": out["id"],
                    "worker_id": out.get("worker_id"), "sha256": digest, "attached_request_id": a.get("request_id")})),
                    T.ImageContent(data=base64.b64encode(r.content).decode(), mime_type="image/png")])
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
                body = {"tool": tool, "input": a.get("input", {}) if generic else a, "agent_use": True}
                if ros:
                    body["require_os"] = ros
                if worker:
                    body["require_worker"] = worker
                if parent:
                    body["parent_request_id"] = parent
                if sid := body["input"].get("session_id"):     # sessions live on the worker that launched them
                    body["require_worker"] = sid.split("-")[0]
                out = await wait_job(await start_background(body), JOB_WAIT_SECONDS)
                ok = out["state"] in ("succeeded", "queued", "running")
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
