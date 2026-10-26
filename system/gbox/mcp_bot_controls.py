"""The Mercenaries bot's controls and the RAM mods as first-class MCP tools (operator 2026-10-26, request #3889: "all of
the mods we pipe into the game via ghidra need to be interactable via mcp so external services can change the weapon,
guide the bot, change the strategy, spawn enemies at all the spawn points, and have the bot drop landmines while fleeing").

Pure helpers for gbox.mcp_server (no MCP SDK, no HTTP here, so they test without the `mcp` package): which mod tool a
session's game takes, the catalog of each tool's ops exactly as its job input reaches run() (RE5ModsIn / REModsIn
fields only: anything else is dropped by the model, so it is rejected here instead of silently ignored), the strategy
knobs that are settable today versus the constants that are not, the bot summary for bot_sessions, and the spawn
request lookup for the spawn_enemies placeholder.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------------------------------------------------
# Which live-mod tool a session takes (by the library game or the title; never by the emulator alone: a Dolphin or RPCS3
# session of another game must not get RE4 / RE5 memory writes).
# ---------------------------------------------------------------------------------------------------------------------
MOD_TOOLS = {
    "re5_mods": {"game": "Resident Evil 5 Gold Edition (PS3, RPCS3)", "game_ids": ("e7ca89bbeb67360d",),
                 "title_re": r"resident evil 5|biohazard 5", "bot": "gbox.mercs.titles.re5_ps3 (autoplay / MercMode)"},
    "re_mods": {"game": "Resident Evil 4 (GameCube / Wii Edition, Dolphin)", "game_ids": ("78ab9efa2e310db4", "e42c9b780c07c437"),
                "title_re": r"resident evil 4|biohazard 4", "bot": "gbox.re4_merc_bot (autoplay / MercMode)"},
}
TEAM_GAME_IDS = ("e7ca89bbeb67360d", "0871eee3b68cdea3", "6fc93ff62e4eb868")   # mercs_team: RE5, RE6 (Xbox 360 / PS3)


def mod_tool_for(session: dict, override: str | None = None) -> str:
    """re5_mods or re_mods for this session row (/api/sessions: game_id, title, adapter); ValueError when neither fits."""
    if override:
        if override not in MOD_TOOLS:
            raise ValueError(f"tool must be one of {', '.join(MOD_TOOLS)}; for Resident Evil 6 use job_re6")
        return override
    gid, title = session.get("game_id") or "", (session.get("title") or "").lower()
    for name, spec in MOD_TOOLS.items():
        if gid in spec["game_ids"] or re.search(spec["title_re"], title):
            return name
    raise ValueError(f"{session.get('session_id')} is {session.get('title')!r} ({session.get('adapter')}): no RE4 / RE5 mod tool "
                     f"for it. Resident Evil 6: job_re6. Pass tool=re5_mods|re_mods only for a mislabelled RE4 / RE5 session.")


# ---------------------------------------------------------------------------------------------------------------------
# The op catalog: what each op does, its parameters with their allowed values, when it takes effect, and whether the
# tool keeps it as the operator's own setting for the session (the bots' round hooks then apply it instead of their
# defaults). Field names are the tools' job input fields (RE5ModsIn / REModsIn); nothing else reaches run().
# ---------------------------------------------------------------------------------------------------------------------
NOW, NEXT_ROUND, MENU = "now", "next round start (the game copies the loadout template then)", "next native menu boundary"

RE5_FIELDS = {"multiplier": "number, or a string such as \"max\" / \"only\" where an op says so", "on": "bool (default true)",
              "mode": "string", "character": "string", "stage": "integer", "weapon": "integer item id", "only": "bool"}
RE5_OPS = {
    "status": {"params": {}, "effect": "read-only: inventory, the modified tables, kill_time state, operator_overrides", "when": NOW},
    "turn_speed": {"params": {"multiplier": "0.25 .. 50; 1 = the game's, 2 = default, \"max\" = 10", "on": "false restores the game's"},
                   "effect": "the stick turns the player N times faster, aiming and not", "when": NOW, "retained": True},
    "fire_rate": {"params": {"multiplier": "0.1 .. 1000; 1 = the game's, 80 = the operator's default", "on": "false restores the game's"},
                  "effect": "firing tables and fire timer scaled for every gun", "when": NOW, "retained": True},
    "bullet_damage": {"params": {"multiplier": "0.1 .. 1000; 1 = the game's, 10 = default", "on": "false restores the game's"},
                      "effect": "every bullet's damage x N", "when": NOW, "retained": True},
    "infinite_ammo": {"params": {"on": "bool"}, "effect": "no rounds spent (the HUD's infinity sign)", "when": NOW, "retained": True},
    "unlimited_health": {"params": {"on": "bool"}, "effect": "HP refill each snapshot plus signature-verified incoming-hit immunity",
                         "when": NOW, "retained": True},
    "infinite_spray": {"params": {"on": "bool"}, "effect": "an infinite First Aid Spray in the loadout, restored after each use",
                       "when": NOW, "retained": True},
    "instant_qte": {"params": {"on": "bool"}, "effect": "native QTE assistance (button prompts completed at once)", "when": NOW, "retained": True},
    "kill_time": {"params": {"on": "bool", "multiplier": "seconds added to the clock per dispatched enemy: more than 0, at most 30 (default 10)"},
                  "effect": "a time bonus per kill, applied by the Mercenaries observer each snapshot", "when": NOW, "retained": True},
    "add_time": {"params": {"multiplier": "seconds 1 .. 3600 (default 60)"},
                 "effect": "adds to the round's countdown now, with the HUD's +NN Sec. notice", "when": NOW},
    "time_bonus_multiplier": {"params": {"multiplier": "1 .. 20"},
                              "effect": "the standing hourglasses' seconds x N (this round's; run it again each round)", "when": NOW},
    "loadout": {"params": {"on": "true: every character's guns become random powerful campaign weapons; false: the game's loadout"},
                "effect": "rewrites the Mercenaries loadout templates (honours a weapon_override instead of drawing)", "when": NEXT_ROUND},
    "weapon_override": {"params": {"weapon": "RE5 weapon item id (op addresses lists them under weapons); omitted or on=false restores the game's",
                                   "only": "true: that weapon in every gun slot (e.g. longbow-only rounds)"},
                        "effect": "every character's main gun (or every gun) is this weapon", "when": NEXT_ROUND, "retained": True},
    "live_weapon": {"params": {"weapon": "item id; live native creation supports the longbow only (0x0F)", "on": "false retires the request"},
                    "effect": "creates the weapon in the live inventory through the game's own constructor (queued; the result says the phase)",
                    "when": NOW},
    "replace_rockets": {"params": {}, "effect": "rocket launcher entries in the spawn templates become a magnum", "when": NEXT_ROUND},
    "replace_long_guns": {"params": {}, "effect": "rockets and the three sniper rifles become magnums", "when": NEXT_ROUND},
    "random_weapon": {"params": {}, "effect": "the bot switches to a random loaded quick-slot gun (through its input controller)", "when": NOW},
    "select_weapon": {"params": {"weapon": "a loaded quick-slot gun's item id (status lists the inventory)", "on": "false: automatic selection resumes"},
                      "effect": "the bot equips and keeps this gun for the session", "when": NOW},
    "random_cheats": {"params": {}, "effect": "the per-round randomizer: fire_rate x80, turn speed x1, bullet damage x10, infinite ammo, "
                                              "a 75% chance of a redrawn loadout, long guns replaced", "when": NOW},
    "mines": {"params": {"on": "bool: proximity-bomb placement by the bot", "multiplier": "seconds between mines 2 .. 300 (default 60); "
                         "\"only\" or 0 = mines only (one every 2-5 s, the gun put away)"},
              "effect": "the bot's mine cadence; the mine and mine_trail directives need it on", "when": NOW, "retained": True},
    "rotten_egg_only": {"params": {"on": "bool", "multiplier": "egg rate 1 .. 20"},
                        "effect": "rotten eggs as the only weapon, supplied by the game's own constructor", "when": NOW, "retained": True},
    "mercs_select": {"params": {"mode": "reunion | mercenaries", "character": "character name (default \"Chris (Heavy Metal)\")", "stage": "stage index"},
                     "effect": "the next round's mode, character and stage", "when": MENU},
    "addresses": {"params": {}, "effect": "read-only: this build's address table and the weapon id -> name list", "when": NOW},
    "revert_all": {"params": {}, "effect": "undo every change of this session (a relaunch is the full revert too)", "when": NOW},
}

RE4_FIELDS = {"item": "item name or id", "count": "integer", "target": "string", "on": "bool (default true)", "seconds": "number",
              "threshold": "number", "character": "string", "items": "list of strings", "fire_rate": "string", "damage": "number",
              "reset": "bool", "multiplier": "number (default 2)", "melee_only": "bool", "kind": "string", "force": "number",
              "direction": "string", "speed": "number", "seed": "integer", "guns": "integer"}
RE4_OPS = {
    "status": {"params": {}, "effect": "read-only: room, position, patches, items", "when": NOW},
    "list": {"params": {}, "effect": "read-only: the attache case", "when": NOW},
    "item_ids": {"params": {}, "effect": "read-only: this release's item catalog", "when": NOW},
    "addresses": {"params": {}, "effect": "read-only: the address table with sources", "when": NOW},
    "merc_loadout_list": {"params": {}, "effect": "read-only: the per-character Mercenaries loadout records", "when": NOW},
    "give": {"params": {"item": "name or id (\"rocket launcher\", \"0x37\")", "count": "amount (0 = the game's default)"},
             "effect": "the game's own take-item routine places it in the case", "when": NOW},
    "replace": {"params": {"item": "the new item", "target": "a case item: name, id or slot", "count": "amount"},
                "effect": "swap a case item for another", "when": NOW},
    "equip": {"params": {"item": "a weapon"}, "effect": "equip it now (given first when missing)", "when": NOW},
    "weapon_mod": {"params": {"item": "a weapon", "fire_rate": "frames between shots (30 = 1 s) or \"auto\"", "damage": "firepower x",
                              "reset": "true: the game's values first"}, "effect": "that weapon class's fire rate / firepower", "when": NOW},
    "merc_loadout": {"params": {"character": "leon | ada | hunk | krauser | wesker | any", "items": "[\"handcannon\", \"handcannon ammo:200\"]",
                                "count": "the first gun's ammo", "on": "true drops the default guns", "reset": "true: the game's loadout"},
                     "effect": "the character's Mercenaries loadout; kept as the operator's, so the bot's per-round random draw is skipped",
                     "when": "the next Mercenaries run start", "retained": True},
    "random_loadout": {"params": {"character": "leon | ada | hunk | krauser | wesker | all", "guns": "how many random guns", "count": "ammo each (200)",
                                  "damage": "firepower x", "seed": "repeat a draw", "on": "bool"},
                       "effect": "a random gun from the weapon table at each Select Player; kept as the operator's loadout",
                       "when": "the next Mercenaries run start", "retained": True},
    "spawn_multiplier": {"params": {"count": "factor 1 .. 8", "on": "false = x1"},
                         "effect": "every enemy the room / Mercenaries spawns gets factor-1 clones beside it (the game's 80 slots cap it); "
                                   "not a spawn at a chosen point", "when": NOW, "retained": True},
    "infinite_ammo": {"params": {"on": "bool"}, "effect": "code patch", "when": NOW, "retained": True},
    "combo_freeze": {"params": {"on": "bool"}, "effect": "the Mercenaries combo never ends", "when": NOW, "retained": True},
    "merc_timer_freeze": {"params": {"on": "bool"}, "effect": "the Mercenaries timer stands still", "when": NOW, "retained": True},
    "unlimited_health": {"params": {"on": "bool"}, "effect": "code patch", "when": NOW, "retained": True},
    "grenade_safe": {"params": {"on": "bool"}, "effect": "your own hand grenades never hurt you", "when": NOW, "retained": True},
    "auto_first_aid": {"params": {"on": "bool", "threshold": "0.05 .. 0.95 of full health (0.35)", "seconds": "least seconds between sprays 0.5 .. 60 (2.5)"},
                       "effect": "the autobot's infinite First Aid Spray (HP back to full under the threshold)", "when": NOW},
    "merc_time": {"params": {"seconds": "the Mercenaries timer's new value"}, "effect": "sets the timer (in a Mercenaries stage only)", "when": NOW},
    "merc_time_bonus": {"params": {"multiplier": "x every time pickup (1 = the game's)", "on": "false = x1"},
                        "effect": "every hourglass pickup x N", "when": NOW, "retained": True},
    "combo_time": {"params": {"multiplier": "0.25 .. 20 (1 = the game's 10 s window)", "on": "false = x1"},
                   "effect": "the combo window x N", "when": NOW, "retained": True},
    "aim_turn_speed": {"params": {"multiplier": "x the game's aim turn speed", "on": "false = x1"},
                       "effect": "how fast the stick turns Leon while aiming", "when": NOW, "retained": True},
    "explosive_melee": {"params": {"on": "bool", "kind": "grenade | flash | rocket"}, "effect": "knife hits explode (never hurts Leon)", "when": NOW},
    "super_melee": {"params": {"on": "bool", "force": "feet (default 100)", "direction": "up | away | both"},
                    "effect": "knife hits throw the enemy", "when": NOW},
    "auto_spin": {"params": {"on": "bool", "speed": "degrees per second (360)", "target": "fire | aim | always"},
                  "effect": "Leon turns continuously while firing / aiming / always", "when": NOW},
    "flashbang": {"params": {"target": "player | aim"}, "effect": "one flash blast there", "when": NOW},
    "grenade": {"params": {"target": "player | aim"}, "effect": "one grenade blast there", "when": NOW},
    "flashbang_loop": {"params": {"on": "bool", "seconds": "period (3)"}, "effect": "a flash at the player's feet every period", "when": NOW},
    "grenade_loop": {"params": {"on": "bool", "seconds": "period (3)"}, "effect": "a grenade at the player's feet every period", "when": NOW},
    "explosive_rounds": {"params": {"items": "gun names (default: handgun, red9, blacktail, punisher)", "on": "bool"},
                         "effect": "every bullet impact of these guns detonates a grenade blast", "when": NOW},
    "warp": {"params": {"target": "room: r1xx village, r2xx castle, r3xx island (disc 2), r4xx Mercenaries", "items": "[x, y, z] optional"},
             "effect": "what a door does: load that room", "when": NOW},
    "teleport": {"params": {"items": "[x, y, z] game units (status shows the current position)"}, "effect": "move the player", "when": NOW},
    "mercenaries_unlock": {"params": {"on": "bool"}, "effect": "The Mercenaries, its characters and stages unlocked", "when": NOW, "retained": True},
    "unlock_all": {"params": {"on": "bool"}, "effect": "every extra mode, character, stage and Professional", "when": NOW},
    "mercs_select": {"params": {"character": "leon | ada | hunk | krauser | wesker (empty = random)", "target": "stage name or index (empty = random)"},
                     "effect": "the next Select Player / Select Stage picks", "when": MENU},
    "punch": {"params": {}, "effect": "read-only: why RE4 has no punch and what to use instead", "when": NOW},
}
CATALOG = {"re5_mods": {"fields": RE5_FIELDS, "ops": RE5_OPS}, "re_mods": {"fields": RE4_FIELDS, "ops": RE4_OPS}}


def describe_ops(tool: str) -> dict:
    spec, cat = MOD_TOOLS[tool], CATALOG[tool]
    return {"tool": tool, "game": spec["game"], "fields": cat["fields"],
            "ops": {name: {"params": op["params"], "effect": op["effect"], "when": op["when"], "retained": bool(op.get("retained"))}
                    for name, op in cat["ops"].items()},
            "note": "retained ops are kept as the operator's own setting for this game process: the bot's round hooks apply them "
                    "instead of their defaults (bot_strategy). Every write is read back; the job's output.result carries verified."}


def mod_input(tool: str, session_id: str, op: str, params: dict | None) -> dict:
    """The re5_mods / re_mods job input, with unknown fields rejected (the tool's input model drops them silently)."""
    cat = CATALOG[tool]
    op = str(op or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not op:
        raise ValueError("op is required; game_mod_ops lists them")
    params = dict(params or {})
    if "session_id" in params or "op" in params:
        raise ValueError("session_id and op are arguments of game_mod, not params")
    unknown = sorted(k for k in params if k not in cat["fields"])
    if unknown:
        raise ValueError(f"{tool} has no field {', '.join(unknown)}; its fields: {', '.join(cat['fields'])}"
                         + (f". {op} takes: {', '.join(cat['ops'][op]['params']) or 'nothing'}" if op in cat["ops"] else ""))
    return {"session_id": session_id, "op": op, **params}


# ---------------------------------------------------------------------------------------------------------------------
# Strategy: what is settable at runtime through an API today, and what is a constant.
# ---------------------------------------------------------------------------------------------------------------------
RETAINED_OPS = {tool: sorted(n for n, op in CATALOG[tool]["ops"].items() if op.get("retained")) for tool in CATALOG}
MERCMODE_KEYS = {"enabled": "bool: MercMode on this PC (rounds of the listed titles in turn)",
                 "titles": "list of re4 | re5 | re6 (the rotation)", "rounds_per_title": "1 .. 20 rounds before the next title",
                 "presentation_priority": "bool: a presentation launch outranks other work on the PC",
                 "keep_warm": "0 .. 2 titles kept booted and waiting behind the playing one",
                 "queue": "list of queued round requests (objects)", "preferred_editions": "object: title -> edition / backend preference"}
TEAM_KEYS = {"role": "solo_p1 | teammate_p2 | observe_human", "training_profile": "assisted | unmodified_evaluation",
             "auto_reduce_mods": "bool", "selected_route_id": "string: a reviewer demonstration route"}
NOT_SETTABLE = {
    "re5_policy": "gbox.mercs.titles.re5_strategy.Policy is a dataclass of constants read at import: critical_radius_cm 350, "
                  "combo_reserve_s 1.0, pickup_s 0.75, at_bonus_pickup_s 0.35, critical_clock_s 15, heal_fraction 0.4, "
                  "boss_delay_combo 120, optional_item_trip_s 5.0. No API changes them; a code change does.",
    "re5_playing_ops": "the RE5 profile's playing_ops (profiles/gamedata/BLUS30491-ram.json: unlimited_health off, infinite_spray on, "
                       "kill_time 10 s, replace_rockets) is a file the worker reads; the retained mods above take precedence over it.",
    "re4_package": "gbox.re4_merc_bot.PACKAGE / ROUND_OP (the Hand Cannon 50/50 with a random x20 gun, spawn x3, combo x3 ...) and its "
                   "engagement radii are constants; the retained RE4 mods above are applied instead of the package's values, and an "
                   "operator loadout (merc_loadout / random_loadout) makes the bot skip its own per-round draw.",
}


def strategy_options(tool: str | None) -> dict:
    return {"mods": {"description": "list of {op, ...params}: the ops this title's bot keeps for the session (its round hooks apply them "
                                    "instead of their defaults); other ops: game_mod",
                     "ops": RETAINED_OPS[tool] if tool else RETAINED_OPS},
            "mercmode": MERCMODE_KEYS, "team": {"keys": TEAM_KEYS, "games": "Resident Evil 5 and 6 only"},
            "not_settable": NOT_SETTABLE}


def strategy_plan(tool: str | None, session: dict, settings: dict) -> list[tuple[str, dict]]:
    """settings -> [(kind, payload)]: ('mod', job input), ('mercmode', patch), ('team', job input). ValueError on anything else."""
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object with any of: mods, mercmode, team")
    unknown = sorted(k for k in settings if k not in ("mods", "mercmode", "team"))
    if unknown:
        raise ValueError(f"unknown settings {', '.join(unknown)}; the keys are mods, mercmode, team (bot_strategy with empty settings lists them)")
    plan: list[tuple[str, dict]] = []
    mods = settings.get("mods") or []
    if mods and tool is None:
        raise ValueError("mods need an RE4 / RE5 session")
    if not isinstance(mods, list):
        raise ValueError("mods must be a list of {op, ...params}")
    for item in mods:
        if not isinstance(item, dict) or not item.get("op"):
            raise ValueError("each mods entry is an object with op and its params")
        op = str(item["op"]).strip().lower().replace(" ", "_").replace("-", "_")
        if op not in RETAINED_OPS[tool]:
            raise ValueError(f"{op} is not a setting the {tool} bot keeps; the retained ops: {', '.join(RETAINED_OPS[tool])}. "
                             f"Apply it once with game_mod.")
        plan.append(("mod", mod_input(tool, session["session_id"], op, {k: v for k, v in item.items() if k != "op"})))
    merc = settings.get("mercmode")
    if merc is not None:
        if not isinstance(merc, dict) or not merc:
            raise ValueError("mercmode must be an object of settings")
        bad = sorted(k for k in merc if k not in MERCMODE_KEYS and k != "host")
        if bad:
            raise ValueError(f"unknown mercmode settings {', '.join(bad)}; the keys: {', '.join(MERCMODE_KEYS)}")
        plan.append(("mercmode", dict(merc)))
    team = settings.get("team")
    if team is not None:
        if not isinstance(team, dict) or not team:
            raise ValueError("team must be an object of settings")
        bad = sorted(k for k in team if k not in TEAM_KEYS)
        if bad:
            raise ValueError(f"unknown team settings {', '.join(bad)}; the keys: {', '.join(TEAM_KEYS)}")
        if session.get("game_id") not in TEAM_GAME_IDS:
            raise ValueError("team settings cover Resident Evil 5 and 6 sessions only")
        plan.append(("team", {"session_id": session["session_id"], "op": "configure", **team}))
    return plan


# ---------------------------------------------------------------------------------------------------------------------
# bot_sessions: one row per running session with the bot's live summary.
# ---------------------------------------------------------------------------------------------------------------------
SUMMARY_KEYS = ("phase", "screen", "rounds", "profile", "kills_seen", "hits", "max_combo", "shots_s", "directive", "directive_active",
                "directive_status", "team_role", "team_phase", "mines_enabled", "mine_interval_s", "mines_only", "mine_status",
                "playing_hooks", "stopped_reason", "mercs_unlocks")


def bot_summary(telemetry: dict | None) -> dict:
    t = telemetry or {}
    stats = t.get("stats") or {}
    out = {"running": bool(t.get("running")) if t else False, "telemetry": bool(t)}
    if t:
        out.update(age_s=t.get("age_s"), mode=t.get("mode"), mission=t.get("mission"), autoplay_job_id=t.get("source_autoplay_job_id"))
        out.update({k: stats[k] for k in SUMMARY_KEYS if k in stats})
    return out


def session_row(session: dict, telemetry: dict | None, workers: list[dict]) -> dict:
    sid = session.get("session_id") or ""
    wid = sid.split("-")[0]
    worker = next((w for w in workers if w.get("id") == wid), None)
    try:
        tool = mod_tool_for(session)
    except ValueError:
        tool = None
    return {"session_id": sid, "title": session.get("title"), "game_id": session.get("game_id"), "adapter": session.get("adapter"),
            "state": session.get("state"), "worker_id": wid, "host": worker.get("name") if worker else None,
            "host_online": worker.get("online") if worker else None, "mod_tool": tool, "bot": bot_summary(telemetry)}


# ---------------------------------------------------------------------------------------------------------------------
# spawn_enemies: not implementable yet. Neither title has a verified enemy-spawn write (RE4's spawn_multiplier clones what the
# game spawns; RE5 has no spawn or enemy-count address verified). The operator's request is tracked in the inbox.
# ---------------------------------------------------------------------------------------------------------------------
SPAWN_WEAK = re.compile(r"spawn", re.I)
SPAWN_STRONG = re.compile(r"(any|whatever|every|all|more) (the |of the )?(enem|majini|ganado)|\bwaves?\b|endless|enemies appear|spawn ?points?", re.I)
SPAWN_REASON = ("No verified spawn address in either title: RE5 (BLUS30491) has no verified enemy-spawn or enemy-count write, and RE4's "
                "spawn_multiplier only clones the enemies the game itself spawns (1 .. 8x, game_mod op=spawn_multiplier). Spawning a chosen "
                "enemy at a chosen spawn point needs the native spawn routine located and verified first.")


SPAWN_TITLE_HINT = {"re5_mods": re.compile(r"\bRE5\b|resident evil 5|biohazard 5|BLUS30491|\bPS3\b", re.I),
                    "re_mods": re.compile(r"\bRE4\b|resident evil 4|biohazard 4|G4BE08|gamecube|\bGC\b", re.I)}


def spawn_tickets(rows: list[dict], tool: str | None = None) -> dict:
    """The open spawn requests (a title with 'spawn' plus a wave / any-enemy / spawn-point wording), newest first; ticket is
    the one for this session's title when a title-specific request exists (#3900 RE5, #3901 RE4), else the newest, else None."""
    def brief(r):
        return {"number": r.get("number"), "id": r.get("id"), "title": (r.get("title") or "")[:160], "status": r.get("status")}
    hits = sorted((r for r in rows or [] if SPAWN_WEAK.search(r.get("title") or "") and SPAWN_STRONG.search(r.get("title") or "")),
                  key=lambda r: r.get("created") or 0, reverse=True)
    if not hits:
        return {"ticket": None, "request": None, "requests": []}
    hint = SPAWN_TITLE_HINT.get(tool or "")
    best = next((r for r in hits if hint is not None and hint.search(r.get("title") or "")), hits[0])
    return {"ticket": best.get("number"), "request": brief(best), "requests": [brief(r) for r in hits]}
