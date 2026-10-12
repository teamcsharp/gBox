"""gBox chat agent: a local LLM (Spark Ollama, OpenAI-compatible tool calling) that operates gBox for the operator.

The agent never touches internals directly: every action goes through gBox's own authenticated API (jobs with receipts,
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
from .agent_contracts import (native_swap_outcome, native_swap_result, require_character,
                              required_operation_outcome, resolve_read_session, validate_cheat_call)

SYSTEM = """You are gBox, an assistant that operates a game laboratory for its operator (who owns these games) in real time.
You can search the web, find and launch games, inspect and edit live emulator memory, extract sprites/tiles to Blender,
and run Ghidra analyses. Use tools; don't guess facts you can look up or measure.
REA provides deconstruction, application/binary/runtime analysis and reconstruction verification: use rea_tools query
to find an operation, then rea_tools name to load its native function and schema. Run it directly or through run_tool.
Keep related calls on the same worker. Preserve evidence/unknowns; check actual provider support before claiming success.

How to work:
- Understand the request in the operator's words. If it's about a specific game, use the session context or search_games.
- Reverse engineering (Ghidra, "find the code that…", model/file formats, patch points, character swaps a game has no writer
  for): re_dossier op=read (what gBox already knows about this title), re_playbook op=list + op=get (the how-to, with lessons
  from earlier tasks), re_study (the executable in Ghidra at the right address), follow the steps; record every address you
  confirm or rule out with re_dossier op=record, and finish with re_playbook op=learn. That is how you get better at each game.
- Cheats like "infinite lives/health/money": web_search for the game's GameShark/Action Replay/Pro Action Replay codes or a RAM map,
  convert the code to an address (e.g. N64/GameCube GameShark 80XXXXXX YY = 8-bit write of YY at 0x80XXXXXX, 81XXXXXX YYYY = 16-bit;
  NES Game Genie needs decoding, Pro Action Replay 7EXXXXYY = SNES WRAM 0x7EXXXX), read_memory there to sanity-check the current value,
  then freeze_memory to hold it. If no code is found, use memory_snapshot + memory_filter (e.g. lives: snapshot, lose a life, filter "dec",
  then "eq" with the shown value) and freeze the surviving address. Tell the operator what you changed and how to undo it.
- Sprites/graphics: extract_tiles from the ROM (cartridge systems) with the right format (nes, gb, snes, md, lin8, one); it lands on the
  gBox clipboard so the operator presses Ctrl+Shift+V in Blender. Try several offsets/formats if the first looks like noise.
- CPU-level work: debugger(op="break", kind="write", address=<HP/lives address>) then resume and wait for the hit to find the code
  that changes a value; debugger(op="info") shows registers, op="disasm" the code. Always resume the CPU when you're done.
- Reverse engineering: ghidra_scripts to find a script, analyze_binary / ghidra_script to run Ghidra on an executable.
- "Put me on <stage/world/level>", "play as <character>", "skip to <boss>": DO IT, don't explain how the operator could.
  Playbook, in order, until it works: (1) web_search the game's RAM map / level-select or debug code / "level ID list"
  (datacrystal.tcrf.net, tcrf.net, smwcentral.net, gamehacking.org, speedrun wikis), web_fetch the page for exact addresses and IDs;
  (2) read_memory those addresses to confirm the live values match (current level/world/character); (3) write_memory the target
  level/world/character ID (plus any "unlocked/cleared" flags and the transition/load trigger, e.g. set the level number and force
  a level reload or death/exit); freeze_memory if the game keeps overwriting it; (4) look_at_screen to verify you got there;
  (5) if no map exists, find it yourself: memory_snapshot, have the operator (or you via the level change) move, memory_filter chg/same,
  or run_tool ghidra_script/analyze_binary on the ROM to find the level-load routine and its table, or patch a debug/level-select
  code from a GameShark/Game Genie/Action Replay list. Keep trying alternatives; only stop after verifying on screen.
- "I want this to be X" (Ctrl+click / eyedropper messages carry a frame + close-up with the spot circled): (1) read the value
  or name under the mark from the vision description (a number on screen, an item, a stat); (2) recall + web_search for a known
  address/code first; (3) otherwise memory_search op=start type=u32 value=<shown number> (also try u16 and f32), then ask_user to
  change it in game (spend money, take damage, level up) or change it yourself, op=next cmp=eq value=<new number>, repeat until
  1-5 candidates; (4) write_memory the target value to each candidate (encode in the platform's endianness), look_at_screen to
  verify the display changed, freeze_memory if the game reverts it; (5) remember the verified address for next time.
  For items/equipment, find the inventory slot the same way (search for the item's ID from the game's item list), then write the
  wanted item's ID. Do it; don't explain how.
- Phantasy Star Online drops: "double/triple the rare rate", "only rares", "every enemy drops rares" -> pso_drops (scale with
  factor, or all_rare), then tell them the new odds from its sample. "I want more rares" -> offer_controls with a 'Rare drop rate'
  slider (1-64x, tool pso_drops op=scale factor='{value}') plus an 'Only rares' toggle (tool pso_drops, input op='all_rare').
  Things gBox hasn't mapped yet (rare *enemy* spawn rate, drop-anything rate): find them (recall, web_search newserv/PSO dev
  docs for the constant or table, debugger write/exec breakpoints, ghidra on the executable), verify, remember, then offer controls.
- "Give me a slider for X" / "make my character bigger" / "faster cars" (any game): ALWAYS answer with offer_controls.
  First locate the value: recall, then web_search the game's memory map (e.g. GTA: gtamods.com wiki - CPed/CVehicle structs,
  handling.cfg fields: fAcceleration / fMaxVelocity / fTractionMultiplier live in the handling table in RAM; a ped's size is
  its RwMatrix: right/up/at vectors' lengths), then read_memory / memory_search to find and verify the live address on this
  session, then offer_controls with tool 'poke' (scale_original:true for multipliers, e.g. character size 1..800x writes all
  three matrix axes). remember the verified addresses so the next request is instant.
- After you get something working that the operator may ask again (an item spawn, a slider's address, a level warp), call
  save_recipe with the exact verified steps. Prefer an existing recipe_* tool over research when one fits.
- GTA pedestrians / traffic amount: the population density multipliers (PedDensityMultiplier, CarDensityMultiplier floats,
  1.0 default) are globals in RAM; find them (recall, web_search gtamods for the game + platform, or memory_search f32 =1.0
  while toggling a known density cheat), verify by watching the street, then offer_controls with a 'poke' slider 0..10x.
- Whenever you need the operator to pick or clarify something (which game, which approach, which option), call ask_user with
  2-6 short concrete options instead of writing a numbered list; the operator clicks one. Don't ask when a sensible default exists.
- UNDERSTAND, THEN EXECUTE. Read past the literal words to the result the operator wants in the running game ("make my sword
  three times bigger" = scale the sword model/hitbox by 3; "get me past X" = set the story flags X sets and put me just after it;
  "I want rapid fire" = shorten the attack's recovery timer). Silently plan: the goal, the game state/values/code involved, and
  the tools that reach them - live RAM (read_memory, memory_search/memory_filter, write_memory, freeze_memory, poke), cheat codes
  (cheats), the debugger (breakpoints on reads/writes to find the code that touches a value), Ghidra (ghidra_scripts to pick one, run_tool ghidra_script /
  analyze_binary on the game executable to find and patch routines), script_patch / mod for code patches, game-specific tools
  (zelda_oot, pso_drops, ...), look_at_screen to see results. Then do it, step by step, verifying each change.
  Ask (ask_user, 2-5 concrete options) only when the request is genuinely ambiguous in a way that changes the outcome (which
  character, which save, permanent vs. toggle); otherwise pick the sensible reading, say which one you picked, and act. Never ask
  permission for something the operator already asked for, and never answer "I can't" before trying the tools above.
- "Skip this talking / dialogue / text", "skip to the end of the conversation" (Zelda: Ocarina of Time): zelda op=skip_text
  on the live session; if the result has timed_out, run it again; if it still is in text, say so with a look_at_screen frame.
  "Get me past the Deku Tree" (the whole story segment) is zelda_oot op=skip_deku_tree instead. Other games: run_tool
  session_op (op=fast_forward, then op=send_input A presses), and say that gBox has no text detector for that game.
- "Walk through walls / doors", "noclip", "no collision" (toggle): game tool first (pso_mods op=noclip, zelda op=noclip), else
  cheats op=list with query "through", then "wall", then "clip" and enable the match (disable it to toggle off); else find the
  player's wall-collision check with the debugger (watch the position while walking into a wall) and patch it, keeping floor collision.
- After mercenaries_unlock the title menu rebuilds once the attract demo plays (~60 s idle) then Start; Up once from LOAD
  = THE MERCENARIES. Dolphin input takes pad names (a, b, start, up), not raw keys.
- MODELS: extract -> collection -> use in any game. The collection (characters tool) holds characters, vehicles, objects
  and environments extracted from the operator's own games; never download models. "Extract / add X to my collection"
  (pick whip "Extract X's model ...") -> characters op=extract character=X kind=character|vehicle|object|environment
  session_id, x/y = X's position on the frame as fractions ("45% across, 60% down" -> x=0.45 y=0.6). "Play as X",
  "replace A / me with B", pick-whip swaps -> characters op=use character=B session_id (not in the collection: op=extract first;
  RE4 "make the enemies X": slot=enemies; OoT: x/y or slot=<NPC> replaces whoever is there, e.g. a Kokiri). OoT pick whip
  "Play as B" -> op=swap a=link b=<B point "x,y" or name> one_way=true; "Swap A <-> B" -> op=swap a=<A> b=<B> (START = A,
  ARROW = B). "Put a X statue here / next to Y" -> op=place character=X session_id [near=Y | x y]. use says "missing" (no writer for that game) or the operator wants it now ->
  characters op=overlay character=B session_id [x y]: B drawn over the player in the desktop app; say it's an overlay.
  Report the status as returned; "extracted" only with checked.ok. Unknown model
  format: Ghidra (analyze_binary / ghidra_script) on the game's executable to find the loader. View an entry: bevy_scene;
  edit: open_in_blender, then characters op=add from_clipboard=true.
- ACT, DON'T SEARCH. A request to change the running game ("infinite red shells", "max money", "make cars fly") is a job to
  DO on the live session, not a question. Break it into steps and run them, in this order, stopping at the first that works:
  (1) recall / an existing recipe_*; (2) cheats op=list query=<1-2 key words, e.g. "shell", "item", "money"> on the session -
  the emulator's cheat database has thousands of codes; enable the match, or cheats op=add with a code built from what you
  learn (e.g. an "Item Select" code shows the item byte's address: hold it with cheats op=add "<addr> <value>");
  (3) memory_search / read_memory to find the value yourself; (4) only then web_search, and only to find an address or code
  you then APPLY. A list of web links is never an answer to a "do X" request. Never stop at "I couldn't find a code" before
  trying (2) and (3). When it works: verify, then save_recipe.
- A game tool's own read-back (verified: true, landed: true, floor_list / list showing the change) IS verification: report it and
  finish. Use look_at_screen at most once per request, as a bonus; small items/values are often unreadable in a frame.
- VERIFY every change before you say it worked: read the result's verified/read_back fields, read_memory the address
  again, or look_at_screen. Say "verified in RAM" vs "verified on screen" vs "written but not yet confirmed". Never tell the
  operator something is done when a tool returned an error, a mismatch, or nothing that proves it.
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
        fn("save_recipe", "Turn something you just made work into a reusable gBox tool (a 'recipe') so next time it's one call, "
           "no research. name (snake_case), description (when to use it), game (title it applies to, '' = any), params "
           "({name: description}), steps = the exact tool calls that worked, with {param} / {session_id} placeholders, e.g. "
           "[{tool:'poke', args:{session_id:'{session_id}', address:'0x9A1B20', type:'f32', value:'{density}', hold:true}}]. "
           "Save only verified procedures; it also lands in the knowledge base.",
           {"name": s, "description": s, "game": s, "params": {"type": "object"}, "steps": {"type": "array", "items": {"type": "object"}}},
           ["name", "description", "steps"]),
        fn("recall", "Search gBox's own knowledge base (everything learned in earlier conversations: wiki pages, answers, verified "
           "RAM addresses and IDs). It is checked automatically at the start of each request; call it again for a narrower question.",
           {"query": s}, ["query"]),
        fn("re_playbook", "Reverse-engineering playbooks: step-by-step how-tos for Ghidra tasks (find the code that writes a "
           "value, a patch point, a model loader / file format, an entity table, a level warp, the input handler, UE3 scripts), "
           "with the exact gBox tools to call and lessons from earlier tasks. ALWAYS op=list (query = the task words) then op=get "
           "before a Ghidra/reverse-engineering task, and op=learn after it (lesson = what worked or what to avoid, outcome = "
           "worked|failed|partial).", {"op": s, "query": s, "id": s, "lesson": s, "outcome": s}, ["op"]),
        fn("re_dossier", "The live game's reverse-engineering dossier: its executable (CPU, Ghidra processor, load address), "
           "Ghidra summary, every known function/global/table/hook with its status (validated / documented / hypothesis) and "
           "open questions. op=read before working on a title; op=record after you find something: kind function|global|table|"
           "hook|format|struct|note, address, name, role (what it does), status hypothesis (default) or validated with evidence "
           "= artifact sha256s that prove it; or question = an open question.",
           {"op": s, "game": s, "kind": s, "address": s, "name": s, "role": s, "status": s, "evidence": {"type": "array", "items": s},
            "question": s}, ["op"]),
        fn("re_study", "Prepare a title for Ghidra: extract its main executable from the disc/ROM as an ELF at the right load "
           "address and processor (GameCube, Wii, Dreamcast, PS1, PS2, N64, GBA, Xbox 360), or source=ram + session_id to "
           "snapshot the running game's RAM; analyze=true also runs Ghidra auto-analysis. Results go into the title's dossier "
           "and are reused for the same executable. Then use analyze_binary / ghidra_script / find_code_that_writes on the ELF.",
           {"game": s, "source": s, "session_id": s, "analyze": b}),
        fn("remember", "Save a verified fact to gBox's knowledge base so later questions are answered instantly (e.g. 'PSO v2 DC: meseta "
           "u32 at 0x8C...; verified by write'). Only facts you verified.", {"text": s, "title": s}, ["text"]),
        fn("web_search", "Search the web (SearXNG). Use for cheat codes, RAM maps, game facts, wikis (Fandom, Wikipedia, "
           "game wikis), tool docs. The operator sees the results as link cards with page thumbnails.", {"query": s, "n": i}, ["query"]),
        fn("web_fetch", "Read a web page (wiki article, guide, FAQ) as plain text (first ~6000 chars); shown to the operator "
           "as a card with the page's thumbnail.", {"url": s}, ["url"]),
        fn("wiki", "Read a wiki article through the MediaWiki API (reliable; web pages of wikis are often bot-blocked). "
           "site = the wiki's host, e.g. phantasystar.fandom.com, zelda.fandom.com, en.wikipedia.org (default), "
           "or another MediaWiki. Returns the best-matching article's text and shows its card + images to the operator.",
           {"query": s, "site": s}, ["query"]),
        fn("show_asset", "Show an extracted game asset (3D model with textures, from the gBox asset packages) in the chat as a "
           "rotating 3D view the operator can orbit, copy to Blender or export (GLB/OBJ/FBX/ABC). query = words of the package "
           "name (e.g. 'savage wolf', 'forest'); empty lists what exists. Extract new assets first with the extraction tools.",
           {"query": s}, []),
        fn("browse", "Open a web page in the operator's AutoBrowse browser on their PC (op=open), or queue a file/video download "
           "there (op=download). Use when they want to look at / read / download something from a result.",
           {"op": s, "url": s}, ["url"]),
        fn("image_search", "Find images on the web (item icons, maps, characters, screenshots) and show them in the chat as "
           "thumbnails.", {"query": s, "n": i}, ["query"]),
        fn("show_gif", "Show a reaction GIF in the chat when it fits the moment (a win, a fail, excitement). Use sparingly.",
           {"query": s}, ["query"]),
        fn("search_games", "Search the gBox library (63k games).", {"query": s, "platform": s}, ["query"]),
        fn("launch_game", "Launch a game. where='local' runs natively on the operator's PC (default), 'spark' streams from the DGX Spark. "
           "debug=true runs it on the Spark in an emulator with a full CPU debugger (GameCube/Wii, GBA, PS1, arcade). "
           "mod=<file mod name> boots a built model/file mod, e.g. RE4 'play as Mario' = mod re4_mario (see the MODELS rule).",
           {"game_id": s, "where": s, "debug": b, "mod": s}, ["game_id"]),
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
        fn("extract_tiles", "Decode tiles/sprites from the ROM (source=rom) or RAM and put a PNG on the gBox clipboard for Blender.",
           {"session_id": s, "source": s, "offset": s, "format": s, "count": i}, ["session_id", "offset", "format"]),
        fn("look_at_screen", "Capture the game screen and describe it with a vision model (what's on screen, menus, HUD values).",
           {"session_id": s, "question": s}, ["session_id"]),
        fn("debugger", "CPU debugger on a live session. op: info (state+registers), disasm (address hex or omit for PC, count), "
           "halt, resume, step, break / unbreak (address hex, kind exec|write|read|access; write watchpoints find the code that "
           "changes a value, e.g. HP). Full registers/breakpoints on Dolphin sessions; others give memory+disassembly only.",
           {"session_id": s, "op": s, "address": s, "kind": s, "count": i}, ["session_id", "op"]),
        fn("find_code_that_writes", "Trace which game code writes a memory value (Phase 4 bridge): sets a write watchpoint, triggers it "
           "(press trigger_key, or waits for the game), decompiles the function with Ghidra, validates with a breakpoint and "
           "records a knowledge edge. Needs a debugger session (launch_game debug=true). Takes several minutes.",
           {"session_id": s, "address": s, "length": i, "trigger_key": s, "label": s}, ["session_id", "address", "label"]),
        fn("cheats", "Cheat codes for a live session. op=list (optionally query=text to filter), enable/disable requires an existing index from list, "
           "add requires codes=['ADDR VALUE', ...] and enables those new lines immediately; do not send codes with op=enable. "
           "Gecko/Action Replay raw or plain address/value lines, desc. Emulator-engine codes "
           "(GameShark/Game Genie/CodeBreaker from the bundled database) toggle live; added codes are held by gBox until disabled.",
           {"session_id": s, "op": s, "index": i, "codes": {"type": "array", "items": s}, "desc": s, "query": s}, ["session_id", "op"]),
        fn("offer_controls", "Give the operator live controls in the chat instead of a one-off change: sliders/toggles that run a "
           "gBox tool each time they're moved. Use when they want 'more/less' of something (rares, speed, lives, difficulty). "
           "controls=[{label, kind:'slider'|'toggle'|'button', min, max, step, value, unit, tool, input}] where input may contain the "
           "string '{value}' (replaced by the slider value / true-false; a button runs input as is). A slider's maximum can be "
           "made adjustable with a second control {label:'Max height', kind:'slider', max_for:'<label of the slider>', min, max, "
           "value} (no tool: it sets that slider's range). Example for 'I want more rares' in PSO: {label:'Rare drop rate', "
           "kind:'slider', min:1, max:64, step:1, value:2, unit:'x', tool:'pso_drops', input:{session_id:'<sid>', op:'scale', "
           "factor:'{value}'}}. ANY game value you have located in RAM gets a slider through tool 'poke': input {session_id, "
           "address:'0x..' (comma list for several, e.g. a matrix's 3 scale axes), type:'f32'|'u32'|..., value:'{value}', "
           "scale_original:true for 'x times bigger/faster' sliders (1..800x), hold:true}. Only offer controls you can back with "
           "a located, verified address.",
           {"title": s, "controls": {"type": "array", "items": {"type": "object"}}}, ["controls"]),
        fn("ask_user", "Ask the operator a multiple-choice question; they click an option (their answer arrives as the next message). Ends your turn.",
           {"question": s, "options": {"type": "array", "items": s}}, ["question", "options"]),
        fn("unreal_script", "Explore an Unreal Engine 3 game's script code from its disc folder (path = USRDIR or a package). "
           "op: summary (packages), members (cls), disasm (function='Class.Function' -> readable UnrealScript), search "
           "(query regex over names + script). Use it to find the systems behind a mechanic (e.g. Stranglehold precision "
           "aim: StrangleholdProjectile_Bullet_PrecisionAim.ResolvePrecisionAim, StrangleholdPawn.ServerResolveDamage).",
           {"path": s, "op": s, "cls": s, "function": s, "query": s}, ["path", "op"]),
        fn("memory_search", "Cheat-search scan of a live game's RAM to find where a value or state lives. op=start (type "
           "u8/u16/u32/f32; value=N if known, else unknown), then op=next with cmp changed/unchanged/increased/decreased/eq/ne "
           "between game actions (ask the operator to do the action, or press keys yourself) until few candidates remain; "
           "then read/freeze/write them. Main RAM is the default range (PS3, GameCube/Wii, Dreamcast, N64, PS1/PS2, GBA/DS). "
           "Money/items: search the shown amount (eq), spend or pick up, search again, then freeze_memory or mod save.",
           {"session_id": s, "op": s, "type": s, "value": {"type": "number"}, "cmp": s,
            "ranges": {"type": "array", "items": {"type": "array", "items": i}}}, ["session_id", "op"]),
        fn("pick", "Live picker: what is at this point of the running game's picture (x, y = 0..1 across the window)? Projects "
           "the game's entities through its camera; returns the entity (class, id, RAM pointer, position) and, for enemies/objects "
           "with a model, an asset package to show with show_asset. Use for 'what is this' / 'extract that' on a click.",
           {"session_id": s, "x": {"type": "number"}, "y": {"type": "number"}}, ["session_id", "x", "y"]),
        fn("pso_inventory", "Phantasy Star Online (Dreamcast v2) inventory: op=list, equip (code = item code hex of a weapon/frame/"
           "barrier/unit/mag; replaces what's equipped in that category), give (code, count for tools). Look codes up with "
           "pso_item_search. Use for 'give me / equip X', 'infinite sabers'. op=meseta with value sets the character's money "
           "('give me $10,000' -> value 10000; 'max meseta' -> 999999).", {"session_id": s, "op": s, "code": s, "count": i, "value": i},
           ["session_id", "op"]),
        fn("pso_item_search", "Search the PSO item catalog read from the game disc: names -> item codes (all weapons, armor, units, "
           "mags, tools).", {"query": s}, ["query"]),
        fn("pso_drops", "Phantasy Star Online rare drops on the live session: op=scale with factor (2 = double the rare rate, "
           "3 = triple...), all_rare (every enemy/box rare slot at the maximum chance), item (code = an item code from "
           "pso_item_search: every enemy and box drops THAT item - the reliable way to 'give me / equip X'), restore, status. Finds the game's rare tables "
           "in RAM and rewrites them; works on PSO versions with a drop_tables profile (others: tell the operator it's not mapped yet).",
           {"session_id": s, "op": s, "factor": {"type": "number"}, "code": s, "boxes": b}, ["session_id", "op"]),
        fn("pso_mods", "Phantasy Star Online Ver.2 (Dreamcast) live mods, all verified in game. op=give (code = item code hex from "
           "pso_item_search, count: real inventory items, 30-slot limit - 'give me 15 DB sabers'), equip_any on=true|false (any class/level "
           "can equip anything - 'let me equip any weapon'), floor_spawn (code, count: real items on the ground next to the player - "
           "'drop a DB saber on the ground'), floor_rares (count: rares scattered around the player), floor_clear (on=false: remove "
           "only items gBox spawned; on=true: every item on this floor - 'remove the rares from the ground'), floor_list, meseta (value) / meseta_max, "
           "crit_always on=true|false ('every attack is a critical'), attack_speed (on=true value=10: attack N times faster, and "
           "holding the attack button rapid-fires; on=false to stop), stat (name atp|mst|evp|hp|dfp|ata|lck, value: 'set my ATP to 900' - sticks and is saved), "
           "list (the live inventory: slot, name, code, equipped), item_set (target = slot number as the menu shows it (0 = first) | "
           "weapon | armor | mag | current code; code = new item code/name, or rare=true for a random rare of the same kind: "
           "'make this item a Durandal', 'make my weapon rare'; for a Ctrl+clicked item, op=list first and match the name), "
           "multi_equip (target = slot | item code | weapon/armor/mag: equip it ON TOP of what's equipped, stats stack - the "
           "'multi-equip bug'; on=false target='' unequips all extras), "
           "status, unhook. give with equip=true also equips the first item ('equip me with a DB saber' = give code count=1 "
           "equip=true; add equip_any first if the class can't normally use it).",
           {"session_id": s, "op": s, "on": b, "value": i, "code": s, "count": i, "equip": b, "name": s, "target": s, "rare": b},
           ["session_id", "op"]),
        fn("re_mods", "Resident Evil 4 live mods (GameCube; Wii Edition = unlock_all, merc_time, merc_time_bonus, merc_timer_freeze, "
           "unlimited_health, weapon_mod), verified by read-back. MERCENARIES (same op names in every RE with a Mercenaries "
           "mode, see docs/mercenaries.md; RE6 = tool re6, RE4 2023 = tool re4r): unlock_all (every Merc character, stage, extra "
           "mode + Professional: 'unlock everything in Mercenaries') | merc_time_bonus multiplier=N ('triple my time bonus' = 3; "
           "RE4 time only comes from hourglasses, so every time pickup is scaled) | explosive_melee on=true kind=grenade|flash|"
           "rocket ('punches explode': knife hits set off a player-owned blast that never hurts Leon; kicks not hooked yet) | "
           "super_melee on=true force=<feet> direction=up|away|both ('punch them hundreds of feet in the air' = force=300 "
           "direction=up; with explosive_melee the blast goes off where they land) | auto_spin on=true speed=<deg/s> target=fire|"
           "aim|always ('spin while firing') | aim_turn_speed multiplier=N ('turn faster while aiming'). 'Make the hand cannon a "
           "machine gun and let me spin while firing' = weapon_mod item=handcannon fire_rate=auto + infinite_ammo + equip "
           "item=handcannon + auto_spin on=true. op=status | list (attache case) | give item=<name|0xID> "
           "count=N (game's own routine, auto-placed in the case) | replace target=<case item/slot> item=<name> | mercenaries_unlock "
           "(The Mercenaries, Assignment Ada, Ada/HUNK/Krauser/Wesker, all 4 stages - shown when the title menu is rebuilt: Options > "
           "Retry or Load > Game Reset) | infinite_ammo | combo_freeze (Merc combo never ends) | merc_timer_freeze | unlimited_health "
           "(each on=true|false) | merc_time seconds=N. Item names: rocket launcher, handcannon, striker, tmp, chicago typewriter, "
           "infinite launcher, red9, flash grenade, hand grenade, shotgun shells ... | equip item=<weapon> (gives it if missing, "
           "then the game's own weapon change: 'equip the handcannon') | weapon_mod item=<weapon> fire_rate=<frames|auto> damage="
           "<multiplier> (reset=true restores; 'make the handcannon full-auto' = fire_rate=auto) | merc_loadout character=<leon|"
           "ada|hunk|krauser|wesker|any> items=[names] on=true (Mercenaries start loadout: XL case, default guns removed, first "
           "gun equipped ~5 s into the run; run it BEFORE picking the character). 'Machine-gun Handcannon for everyone in "
           "Mercenaries' = merc_loadout character=any items=['handcannon'] + weapon_mod handcannon fire_rate=auto + "
           "infinite_ammo. | spawn_multiplier count=2..8 on=true|false (every spawned enemy gets count-1 clones; the enemy manager "
           "caps around 30 Ganados in the Village). | flashbang target=player|aim / grenade target=player|aim (detonate now via the "
           "game's own sequence) | flashbang_loop seconds=3 on=true|false (item=grenade for grenades; 'a flashbang at my feet "
           "every 3 seconds') | explosive_rounds items=[guns] on=true|false (each bullet impact also detonates a grenade blast; "
           "default all pistols - 'make my pistol behave like a rocket launcher') | warp target=r102 [items=[x,y,z]] (go to a room "
           "like a door does; story rooms; r3xx island rooms incl. the final battle r332 are only on disc 2; rooms with a pending "
           "first-visit event can crash - save first) | teleport items=[x,y,z] (move inside the room; status shows player_pos). "
           "No chapter select exists in the GC build. Weapons on non-Leon Merc characters use Leon's stats but keep their own "
           "model; P.R.L. 412 does not exist in the GameCube version (say so).",
           {"session_id": s, "op": s, "item": s, "count": i, "target": s, "on": b, "seconds": i, "character": s,
            "items": {"type": "array", "items": s}, "fire_rate": s, "damage": {"type": "number"}, "reset": b,
            "multiplier": {"type": "number"}, "kind": s, "force": {"type": "number"}, "direction": s, "speed": {"type": "number"}},
           ["session_id", "op"]),
        fn("re6", "Resident Evil 6 (Xbox 360, running in Xenia on the Windows PC; session_id = that session). Offline only: "
           "refuses if the game could be online. MERCENARIES LOADOUTS (any item, story-only weapons included; verified in game): "
           "give item=<name|id> [amount] [character=leon|helena|chris|piers|jake|sherry|ada|agent|any] ('give me the hand "
           "cannon in Mercenaries' = give item='elephant killer'; 'hand cannon'/'magnum'/'revolver' resolve to the Elephant "
           "Killer, 'desert eagle' to the Lightning Hawk) | set_loadout items=[names or {id, amount}] [character] [replace] "
           "('change my loadout to the rocket launcher and both magnums') | auto items=[...] on=true (saved: applied whenever RE6 "
           "runs; on=false stops) | inventory (the start loadouts per character) | status (mode title/story/mercenaries, online, "
           "loadout state). Loadouts take effect when a match is started from character select (Continue/Retry keep the "
           "running loadout): tell the operator. loadout_set = set_loadout. UNLOCKS (boot profile 'RE6: Everything "
           "unlocked', ON by default): unlock_all [on=false restores the original save] = every campaign / chapter / "
           "difficulty up to Professional, Agent Hunt, Mercenaries (3 stages on this disc, all 9 characters + EX costumes), "
           "skills, figures/emblems/titles; in the save (backup kept) and live in a running RE6. everything_unlocked on= "
           "(the same + saved as the boot default), boot_to_title on= (default on: the logo movie is skipped and gBox presses "
           "through PRESS START + notices to the title screen when no real controller is connected). 'Mercenaries No Mercy', "
           "No Hope difficulty, DLC stages/retro costumes aren't in this 360 build: say so plainly. CHARACTER SWAPS: 'play as Aya' = characters op=use "
           "(builds re6_<slug>: Leon in every costume becomes that collection character; pick Leon). build_mod character=<name> "
           "builds without launching; mods lists them. revert_all = loadouts back to the originals, auto off, save restored, "
           "gBox's RE6 mods deleted (the disc is never changed). LIVE (verified in game, Mercenaries; same player structure in "
           "the campaign): infinite_health on=true|false, infinite_ammo on=true|false (held while RE6 runs, saved; 'god mode' / "
           "'unlimited ammo'; offer them as offer_controls toggles: tool re6, input {session_id, op:'infinite_ammo', on:'{value}'}) "
           "| give_now item=<name|id> [amount] = into the inventory RIGHT NOW mid-match (ammo, herbs, grenades, sprays, and ANY "
           "gun: gBox loads the gun's resources first; relay the tool's message) | remove_item slot=N | set_slot slot=N "
           "[item=] [amount=] (change / recount one inventory slot live; slots from live_inventory). Ctrl+click item picker requests ('make this / give me <item>' with 'this game's item id N') "
           "-> give_now item=N | live_inventory | auto_qte on=true|false (every QTE / button prompt succeeds; ON by default "
           "whenever RE6 boots through gBox) | settings. NOT available yet (say so): replacing a pickup lying in the world, "
           "campaign-only characters (Deborah, Simmons...) as playable Mercenaries characters, faster movement for a swapped character.",
           {"session_id": s, "op": s, "item": s, "amount": i, "slot": i, "items": {"type": "array", "items": {}}, "character": s,
            "replace": b, "on": b, "target": s, "costume": s}, ["op"]),
        fn("re_inventory", "ANY Resident Evil running live (RE4 GameCube, RE6 Xbox 360, classic REs whose slot layout gBox "
           "knows): the selected character's inventory. FIRST CHOICE for 'give me a rocket launcher', 'put a first aid spray in "
           "my inventory', 'remove the knife', 'change my shotgun to a magnum', 'set my handgun ammo to 99', 'what do I have'. "
           "op=get (slots: slot, item, amount, max; HP) | give item=<name> [amount] | remove slot=N | set slot=N [item=<name>] "
           "[amount=N] | loadout character=<name> items=[names] (Mercenaries start loadout: RE4 leon|ada|hunk|krauser|wesker, "
           "RE6 leon|helena|chris|piers|jake|sherry|ada|agent) | health amount=N | catalog (every item + the cross-game list). "
           "Item names work across games: 'rocket launcher', 'handgun', 'magnum', 'shotgun shells', 'first aid spray', "
           "'green herb' map to each game's own item; game-specific names and ids work too. Slot numbers come from op=get. "
           "Relay the tool's message; if it says an op isn't available for that game, say so plainly.",
           {"session_id": s, "op": s, "item": s, "amount": i, "slot": i, "character": s, "items": {"type": "array", "items": {}}},
           ["session_id", "op"]),
        fn("re4r", "Resident Evil 4 (2023 remake, Steam, PC) on the Windows PC, through REFramework (praydog) + gBox's Lua "
           "bridge (live game objects by type path; no raw addresses, no debugger on the Denuvo-protected exe). No session_id: "
           "it acts on the game installed on the PC. Offline single-player only. "
           "SETUP/LIFECYCLE: op=status (installed? running? bridge alive? player stats, mods, eula_pending) | install (REFramework "
           "+ bridge into the game folder, manifest + backups) | uninstall (removes all of it + every gBox mod file) | launch "
           "(through Steam; reports when Steam waits for the operator to accept Capcom's EULA - never accept it for them) | stop. "
           "LIVE (game running, in play): stats (hp, max_hp, money = pesetas, spinels, position, time_scale) | set key=hp|max_hp|"
           "money|spinels|invincible|time_scale value=N ('give me 999999 pesetas' = set key=money value=999999) | freeze "
           "key=health on=true|false (HP held at max) or key=<stat> value=N | infinite_ammo / unlimited_items / no_recoil "
           "on=true|false (flag-guarded hooks on the game's own methods) | inventory (items, counts, equipped weapon ammo) | "
           "teleport position=[x,y,z] relative=true|false | revert_all scope=live|files|all (puts back every value gBox changed, "
           "clears freezes and hooks; files = removes every gBox mod file). "
           "GENERIC (for anything else; find names with the type dump): get/set path='singleton:chainsaw.InventoryManager/"
           "CurrPTAS' value=.. (steps: singleton:<type> | type:<type> | addr:0x.. then field, method() or [i]; a property "
           "name works as a field) | call path=<object path> method='recovery(System.Int32)' args=[100] | fields path=<object> "
           "(live field values) | type_info name=<type> (fields + methods) | find_types items=[names] | lua code=<Lua on the "
           "game thread; helpers resolve(path), ser(v)> | changes | dump_types (BFS over the game's type DB from seeds, "
           "written to JSON) then types query=<regex> (search type/method/field names). "
           "MODELS/MODS: export character=leon|ashley (glTF to the collection: characters op=extract does this) | mod_build "
           "name=<mod> character=leon (artifact=<sha of an edited collection .glb / Blender variant> or path=<.glb>: only the "
           "parts that changed are rebuilt; or scale=1.6 parts=[1,2,3] = big head; or texture=<natives/stm/... .tex> png=<image>) "
           "| mods | mod_enable name=<mod> / mod_disable name=<mod> (loose files under natives/, loaded by REFramework's loose "
           "file loader at game start: restart the game to see them; disable = delete gBox's files).",
           {"op": s, "key": s, "value": {"description": "number / bool / {x,y,z}"}, "on": b, "path": s, "method": s,
            "args": {"type": "array"}, "name": s, "items": {"type": "array", "items": s}, "query": s, "code": s,
            "position": {"type": "array", "items": {"type": "number"}}, "relative": b, "character": s, "artifact": s,
            "texture": s, "png": s, "scale": {"type": "number"}, "parts": {"type": "array", "items": i}, "scope": s},
           ["op"]),
        fn("zelda", "Zelda, ANY game/system (NES Zelda 1 & 2, A Link to the Past, Link's Awakening/DX, Oracle of Seasons/Ages, "
           "Minish Cap, Ocarina of Time, Majora's Mask, Wind Waker): edit Link live. op=give item=<name> [count] ('give me the "
           "hookshot', Ctrl+click an item + 'give me this'); equip item=<name> button=b|a|y|x|z|c-left|c-down|c-right "
           "('put the bow on Y', 'equip this'; swords/shields/tunics are just worn); all_items ('give me everything'); "
           "unrestrict ('let me use/equip anything': OoT any age, MM any form, other games the gear that opens every path); "
           "noclip on=true|false (walk through walls/doors); skip_text [count=max seconds, default 90] ('skip this talking', "
           "'skip the dialogue/cutscene', 'skip to the end of the conversation': taps A until the whole conversation ends; "
           "Ocarina of Time only - other games report that no text detector exists); "
           "hearts count=N; rupees count=N; max; remove item=<name>; list "
           "(what Link has + what is on each button); games. Item names are fuzzy ('hook shot', 'bow and arrows', 'master "
           "sword', 'bottle', 'fire arrows'). Results carry before/after bytes and verified (read-back). For Ocarina of Time "
           "story skips / warps use zelda_oot (skip_deku_tree, goto).",
           {"session_id": s, "op": s, "item": s, "count": i, "button": s, "on": b}, ["session_id", "op"]),
        fn("ac_mods", "Armored Core (PS1/PSP) player AC, live, verified. op=build (current parts per slot + EP/weight check) | equip "
           "part=<name/alias e.g. 'karasawa', 'moonlight', 'WG-XP1000', 'pulse rifle', 'SP-MAW'> [slot=head|core|arms|legs|"
           "arm_weapon_r|arm_weapon_l|back_weapon_l|back_weapon_r|booster|fcs|generator|option] | remove slot=.. | apply_build "
           "parts=[names...] (a whole build, e.g. from a web build guide; 'back right: RZ-A0' forces a slot) | unlock_all_parts "
           "(garage offers every part) | money value=N (credits; 0 = max) | parts_search query=.. | best_build goal=all-round|"
           "speed|heavy|... (returns current build + parts by slot + how to apply: web_search a build for THIS game, then "
           "apply_build) | ap (mission: refill armor). Refuses builds the garage would reject (Not Enough Energy / Overweight) "
           "unless force=true. Changes show the next time the garage/Assembly opens and in the next sortie; don't apply while "
           "the Assembly screen itself is open.",
           {"session_id": s, "op": s, "part": s, "slot": s, "parts": {"type": "array", "items": s}, "value": i, "query": s,
            "goal": s, "force": b}, ["session_id", "op"]),
        fn("gta_mods", "PS2 Grand Theft Auto live mods (GTA III, Liberty City Stories), installed into the running game. "
           "op=car_jump: clicking a stick while driving springs the player's car straight up; value=height in feet, "
           "button=l3|r3 (left/right stick click), max_height=cap in feet, on=false turns it off ('make my car jump when I "
           "click the stick', 'car jump 200 ft'). op=ped_rain: count pedestrians (1-100) spawn in the air around the player "
           "and fall; behaviour=0 rain (spread wide, staggered over seconds) .. 1 splash (all at once from one point, "
           "bursting outward), or 'rain'/'splash'; height (m, default 25), radius (m, default 30); on=false stops it ('rain "
           "peds on me', 'make them splash'). GTA III also: punch_launch value=mph, exploding_punch, tank_rain value=seconds, "
           "flying_cars, super_jump value=feet, heli, ped_density/car_density value=multiplier, giant value=scale, "
           "spawn_vehicle model=id. op=status shows what is on and the ops this game supports. Results are read back.",
           {"session_id": s, "op": {"type": "string", "enum": ["status", "car_jump", "ped_rain", "punch_launch", "exploding_punch",
                                                              "tank_rain", "flying_cars", "super_jump", "heli", "ped_density",
                                                              "car_density", "giant", "spawn_vehicle", "games"]},
            "on": b, "value": {"type": "number", "description": "car_jump: height in feet; punch_launch: mph; super_jump: feet; ..."},
            "button": {"type": "string", "enum": ["l3", "r3"]}, "max_height": {"type": "number"},
            "count": {"type": "integer", "description": "ped_rain: how many peds, 1-100"}, "behaviour": {"type": "string", "description": "0 = rain .. 1 = splash, or rain | splash"},
            "height": {"type": "number"}, "radius": {"type": "number"}, "model": i, "explosion": s}, ["session_id", "op"]),
        fn("zelda_oot", "Zelda: Ocarina of Time on the live session. op=skip_deku_tree ('get me past the Deku Tree'), "
           "goto with place ('end of the shadow temple', 'final battle', 'gohma', 'forest temple', 'kakariko'... gives the gear "
           "that place needs and warps; adult places make Link adult), give with item (+c_button 1-3 to equip: 'equip the "
           "hookshot'), kit (child|adult|endgame), full_inventory ('give me every item'), scale with factor ('make Link 2x bigger'), state. Verifies the warp landed "
           "and auto-restores a save state if the game hangs.",
           {"session_id": s, "op": s, "place": s, "item": s, "c_button": i, "kit": s, "factor": {"type": "number"}, "cutscene": b},
           ["session_id", "op"]),
        fn("autoplay", "Take control: gBox plays the live game itself (scripted mission through the debugger). op=list | "
           "start (mission optional; assist=true holds the player's HP so it can't die) | stop (hand control back) | status.",
           {"session_id": s, "op": s, "mission": s, "assist": b}, ["session_id", "op"]),
        fn("mod", "Mod builder for the live game: op=save (name, desc, changes=[{kind:'write',address,hex} | {kind:'preset',"
           "preset} | {kind:'cheat',codes:[...]}] or capture=true to save what is active now), apply (with rollback data), "
           "rollback, verify (regression check that it is still in effect), list, delete.",
           {"session_id": s, "op": s, "name": s, "desc": s, "changes": {"type": "array", "items": {"type": "object"}},
            "capture": {"type": "boolean"}}, ["session_id", "op"]),
        fn("game_link", "Cross-game link between two live sessions: when the host's trigger fires (e.g. Stranglehold bullet-cam), "
           "pause the host, load the guest's save state (e.g. a Puyo Puyo Tetris match), wait for win/lose, apply the host "
           "preset (on_win/on_lose, e.g. god_hit/god_miss) and resume. trigger/win/lose = {address, type u8|u16|u32|f32, "
           "eq|ne|lt|gt: value}, found with memory_search. op start|stop|status.",
           {"op": s, "host": s, "guest": s, "trigger": {"type": "object"}, "win": {"type": "object"}, "lose": {"type": "object"},
            "on_win": s, "on_lose": s}, ["op", "host", "guest"]),
        fn("bevy_scene", "Render models in the gBox Bevy viewer: collection entries (items=[{character: slug} or {environment: "
           "slug}]) or UAP asset packages ({package: 'pso_dc_forest01'}), each with optional translation [x,y,z], scale, "
           "rotation_y_deg; camera={eye, target}. screenshot=true returns a PNG (shown in the chat) - use it to look at an "
           "extracted model; false opens a live Bevy window on the operator's PC.",
           {"name": s, "items": {"type": "array", "items": {"type": "object"}}, "camera": {"type": "object"},
            "screenshot": {"type": "boolean"}}, ["items"]),
        fn("video", "Video knowledge (YouTube etc.). op=search (query, n) -> videos to suggest or play; ingest (url) -> transcript "
           "with timestamps + description + chapters + top comments saved to the gBox knowledge base (then plan from it); "
           "frame (url, at seconds) -> still image; knowledge (query) -> videos already ingested. Put a video's url in your "
           "reply to play it in the chat.",
           {"op": s, "query": s, "url": s, "n": i, "at": {"type": "number"}}, ["op"]),
        fn("file_mod", "File-replacement mods for folder games (PS3 disc folders): op=build (name, changes={relative path: "
           "{patch:[{offset,hex}]} | {artifact: sha256} | {from: local path}}), list, remove. The original is never touched; "
           "launch the mod with launch_game(mod=name).", {"game_id": s, "op": s, "name": s, "changes": {"type": "object"}}, ["game_id", "op"]),
        fn("rom_export", "Export ROM hack: bake a mod into a bootable copy of the operator's OWN game file for their own "
           "flash cart / modded console / emulator (N64 .z64 with fixed CRC, GameCube .iso, Wii .iso/.rvz, PS2 .iso, PS3/360 "
           "extracted folder) + a shareable BPS/IPS patch with no game data + cheat files for codes. mod_id = a saved mod "
           "(its file mod, re_mods code patches and cheat codes are baked; live memory mods are reported as not bakeable); "
           "mods = more file-mod names / saved mod ids to stack; op=plan shows what can be baked without building; "
           "op=list shows finished exports. Output stays on this gBox (exports/); tell the operator to download it from the "
           "mod card's 'Export ROM hack' button.",
           {"op": s, "mod_id": s, "game_id": s, "mods": {"type": "array", "items": s}, "name": s}, []),
        fn("script_patch", "Live UnrealScript patches from the game's profile on a running session (PS3 UE3 games). op: status, "
           "locate (find the profile's script functions in RAM), preset (preset=name, e.g. Stranglehold 'god' = infinite life, "
           "'hit' = precision-aim shots always lethal, 'miss' = always miss, 'god_hit'/'god_miss' = both, 'off' = original "
           "game), revert. For 'infinite life' on a game that has a profile, use this before searching RAM. Pair with session_op pause/resume to "
           "hold a shot mid-flight while something else decides its outcome.",
           {"session_id": s, "op": s, "preset": s}, ["session_id", "op"]),
        fn("ghidra_scripts", "Search the installed Ghidra scripts (311) by keyword.", {"query": s}, ["query"]),
        fn("analyze_binary", "Ghidra headless import + auto-analysis of a game executable (functions + strings). Use it to find "
           "a model/format loader: look for strings and functions near file names (.nj, .prs, .dat, .mdl, .dff), then "
           "ghidra_script / debugger on them. binary_path = a file the worker can read (an extracted executable: Dreamcast "
           "1ST_READ.BIN, PS1/PS2 SLUS_xxx.xx, GameCube main.dol); processor e.g. SuperH4:LE:32:default (Dreamcast), "
           "MIPS:LE:32:default (PS1), PowerPC:BE:32:Gekko_Broadway (GameCube). Takes minutes.",
           {"binary_path": s, "processor": s}, ["binary_path"]),
        fn("ghidra_script", "Run one Ghidra script (find one with ghidra_scripts) headlessly on an executable, e.g. to decompile "
           "a loader or dump a table. Returns the script log.", {"binary_path": s, "script": s, "args": {"type": "array", "items": s},
           "processor": s}, ["binary_path", "script"]),
        fn("characters", "collect (game): extract the supported native character roster without vision calls; returns verified models, mapped rig readiness and individual failures. gBox's collection: characters, vehicles, objects and environments extracted from the operator's games, "
           "reusable in any game. use/live_use/overlay/place require a nonempty character copied from the operator's exact slug/name. "
           "Overlay/missing/pending results do not complete a native swap; keep the request pending until native verification. "
           "op=list | get (character) | environments | extract (character = what to extract, kind = "
           "character|vehicle|object|environment, session_id or game, x/y = its point on the picture 0..1): returns it if it's "
           "already collected, else runs the game's own extractor, else cuts it out of a RenderDoc capture of the frame "
           "(environment = whole scene minus HUD), else says what's missing and files a request; result has status, checked "
           "(model + preview verified) and a preview image | use (character, session_id or game, slot): launch/build the swap mod "
           "(RE4 GameCube replaces Leon, Super Mario 64 replaces Mario, Ocarina of Time replaces Link - or with x/y or slot=<NPC "
           "name> the NPC there), else what that game lacks | swap (OoT; a, b = 'link', an NPC name or a picture point 'x,y'; "
           "session_id): A gets B's model, B gets A's; one_way=true: only A <- B ('play as B') | place (OoT; character, "
           "session_id, optional near=<actor name> or x/y, size): a statue of the character in the world, default in front of "
           "the player | unplace (OoT; session_id, optional character) | overlay (character, session_id, "
           "optional x/y = the target's point 0..1): any game, now: the model tracks and covers the player on screen in the "
           "desktop app (an overlay, not in-engine) | add (character = new name, from_clipboard=true): store a "
           "model edited in Blender. game = title or catalog game_id (default: the chat's game); extract needs a running "
           "session only when the thing has to be cut from the frame.",
           {"op": s, "character": s, "kind": s, "session_id": s, "game": s, "x": {"type": "number"}, "y": {"type": "number"},
            "slot": s, "from_clipboard": b, "a": s, "b": s, "one_way": b, "near": s, "size": {"type": "number"}}, ["op"]),
        fn("scene_capture", "Capture the frame on screen of a live session (Windows PC emulators started with Examine 3D) as a "
           "real 3D scene: glTF with one node per draw call + textures, HUD separate. For extracting a model into the "
           "collection use characters op=extract (it does this and cuts the object out); this is for looking at the raw scene.",
           {"session_id": s}, ["session_id"]),
        fn("open_in_blender", "Put a collection model (character = slug/name) or an asset package (package) on the gBox clipboard; "
           "the operator presses Ctrl+Shift+V in Blender (gBox add-on) to import it, edits it, then 'Send to gBox' in the "
           "add-on panel; then call characters op=add character=<new name> from_clipboard=true.",
           {"character": s, "package": s}, []),
        fn("rea_tools", "Discover REA tools for deconstruction, analysis and reconstruction. Search query first, then exact name "
           "to obtain its input schema and examples. Call run_tool with the rea_ name; keep analysis on its returned worker_id.",
           {"query": s, "name": s}, []),
        fn("read_rea_result", "Read full REA evidence after an inline excerpt: sha256 is evidence_sha256. Empty pointer lists root keys; "
           "JSON Pointer selects a child; offset/limit paginate lists or keys. Strings return 6000 characters per page.",
           {"sha256": s, "pointer": s, "offset": i, "limit": i}, ["sha256"]),
        fn("run_tool", "Run any gBox typed tool as an audited job, including every rea_ operation. Use rea_tools to discover "
           "their inputs; worker_id pins stateful REA calls to the same worker; node selects windows/linux.",
           {"name": s, "input": {"type": "object"}, "worker_id": s, "node": s}, ["name", "input"]),
    ]


class Agent:
    def __init__(self, api_base: str, token: str, llm_url: str, model: str, searx_url: str, vision_model: str | None = None):
        self.api = httpx.Client(base_url=api_base, headers={"authorization": f"Bearer {token}", "x-gbox-actor": "gbox-agent"}, timeout=120)
        self.llm_url, self.model, self.searx, self.vision = llm_url.rstrip("/"), model, searx_url.rstrip("/"), vision_model
        self.snapshots: dict[str, dict] = {}
        self.game: str | None = None                           # title of the live game; pins web searches to it
        self.analysis_share = "//10.89.1.246/ehm_eckx/gBox/system/gbox-data/analysis"   # where Windows Ghidra reads ELFs

    # --- tool implementations (all through the public API) ---
    def _job(self, tool, inp, node=None, limit=900, worker=None):
        sid = inp.get("session_id") if isinstance(inp, dict) else None
        if sid and tool != "session_op" and (bad := self._live_session(sid)):   # a mistyped id would queue the job forever
            return {"state": "failed", "error": bad["error"], "output": None}
        body = {"tool": tool, "input": inp}
        if getattr(self, "parent_request_id", None):
            body["parent_request_id"] = self.parent_request_id
        if node:
            body["require_os"] = node
        if worker:
            body["require_worker"] = worker
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
        game = re.sub(r"\s*[\(\[].*?[\)\]]", "", self.game or "").strip()       # "(USA)" / "[!]" tags ruin web searches
        if game and not all(w in query.lower() for w in game.lower().split()[:3]):
            query = f"{game} {query}"                           # small models drift to other games; keep searches on the live one
        r = httpx.get(f"{self.searx}/search", params={"q": query, "format": "json", "categories": "general",
                                                       "safesearch": 1, "language": "en"}, timeout=30).json()
        # ponytail: crude relevance gate; this SearXNG's bing engine sometimes answers with unrelated pages
        terms = {w for w in re.findall(r"[a-z0-9]{4,}", query.lower())}
        need = max(1, (len(terms) + 1) // 2)                     # at least half the meaningful words must appear
        hits = [x for x in r.get("results", []) if not terms or
                len(terms & set(re.findall(r"[a-z0-9]{4,}", f"{x.get('title')} {x.get('url')} {x.get('content')}".lower()))) >= need]
        res = [{"title": x.get("title"), "url": x.get("url"), "snippet": (x.get("content") or "")[:300],
                "thumb": x.get("thumbnail") or x.get("img_src")} for x in hits[:max(1, min(n, 10))]]
        if not res:
            return {"results": [], "note": "web search returned nothing relevant (the search engine pool is limited right now); use "
                    "wiki(query, site=...) for game facts - e.g. phantasystar.fandom.com, zelda.fandom.com, en.wikipedia.org",
                    "_cards": {"kind": "links", "items": []}}
        return {"results": [{k: v for k, v in x.items() if k != "thumb"} for x in res], "_cards": {"kind": "links", "items": res}}

    def web_fetch(self, url):
        r = httpx.get(url, timeout=30, follow_redirects=True, headers={"user-agent": "Mozilla/5.0 gBox"})
        meta = lambda k: (re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*content=["\']([^"\']+)' % k, r.text, re.I) or [None, None])[1]
        title = meta("og:title") or (re.search(r"(?is)<title[^>]*>(.*?)</title>", r.text) or [None, ""])[1].strip()
        t = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", r.text)
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip()
        card = {"title": html.unescape(title or url), "url": str(r.url), "snippet": (meta("og:description") or t[:240]),
                "thumb": meta("og:image") or meta("twitter:image")}
        self._learn(t[:20000], str(r.url), card["title"], "page")
        return {"text": t[:6000], "_cards": {"kind": "links", "items": [card]}}

    def wiki(self, query, site="en.wikipedia.org"):
        site = re.sub(r"^https?://|/.*$", "", site or "en.wikipedia.org")
        h = {"user-agent": "Mozilla/5.0 gBox (game assistant)"}
        hits, api = None, None
        for path in (("w/api.php", "api.php") if site.endswith("wikipedia.org") else ("api.php", "w/api.php")):
            try:                                           # MediaWiki lives at /api.php (Fandom) or /w/api.php (Wikipedia)
                api = f"https://{site}/{path}"
                hits = httpx.get(api, params={"action": "query", "list": "search", "srsearch": query, "srlimit": 5, "format": "json"},
                                 headers=h, timeout=20, follow_redirects=True).json()["query"]["search"]
                break
            except (ValueError, KeyError, httpx.HTTPError):
                continue
        if hits is None:                                   # not a MediaWiki site (or blocked): search it instead
            return self.web_search(f"site:{site} {query}")
        if not hits:
            return {"error": f"no article for {query!r} on {site}"}
        title = hits[0]["title"]
        p = httpx.get(api, params={"action": "parse", "page": title, "prop": "text|images", "format": "json", "formatversion": 2,
                                   "redirects": 1}, headers=h, timeout=30).json()["parse"]
        body = re.sub(r"(?is)<(script|style|table class=\"navbox).*?</\1>", " ", p["text"])
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
        imgs = [html.unescape(u) for u in re.findall(r'<img[^>]+(?:data-src|src)="([^"]+)"', p["text"]) if u.startswith("http")
                and not re.search(r"\.svg|icon|logo|/thumb/.*?/(1\d|[1-9])px-", u, re.I)]
        imgs = list(dict.fromkeys(imgs))[:8]
        url = f"https://{site}/wiki/{p['title'].replace(' ', '_')}"
        cards = [{"type": "cards", "kind": "links", "items": [{"title": f"{p['title']} · {site}", "url": url, "snippet": text[:240],
                                                                "thumb": imgs[0] if imgs else None}]}]
        if len(imgs) > 1:
            cards.append({"type": "cards", "kind": "images", "items": [{"title": p["title"], "url": url, "img": i, "thumb": i} for i in imgs]})
        self._learn(text[:20000], url, p["title"], "wiki")
        return {"title": p["title"], "url": url, "other_matches": [x["title"] for x in hits[1:]], "text": text[:6000], "_cards": cards}

    def _learn(self, text, source="", title="", kind="page"):
        """Background: store what was just read so the next similar question is answered from the knowledge base."""
        if not text or len(text) < 80:
            return
        threading.Thread(target=lambda: self.api.post("/api/kb", json={"text": text, "source": source, "title": title,
                                                                           "game": self.game or "", "kind": kind}), daemon=True).start()

    def _bookmark_state(self, sid):
        """Save state into the bookmark ring (slots 20-39) and return {slot, frame}; never fails the request."""
        try:
            n = getattr(Agent, "_bm_n", 0)
            Agent._bm_n = n + 1
            slot = 20 + n % 20
            j = self._job("session_op", {"session_id": sid, "op": "save_state", "args": {"slot": slot}}, worker=sid.rsplit("-", 1)[0], limit=60)
            r = (j.get("output") or {}).get("result") or {}
            return {"slot": r.get("slot", slot), "frame": r.get("frame"), "ts": time.time()}
        except Exception as e:
            return {"error": str(e)}

    def save_recipe(self, name, description, steps, game="", params=None):
        name = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")[:48]
        r = self.api.post("/api/recipes", json={"name": name, "description": description, "game": game or (self.game or ""),
                                                 "params": params or {}, "steps": steps})
        r.raise_for_status()
        return {"saved": "recipe_" + name, "note": "available as a tool in every conversation for this game from now on"}

    def _run_recipe(self, r, args, context):
        vals = {**{k: v for k, v in args.items()}, "session_id": context.get("session_id", "")}
        fill = lambda x: (vals.get(x[1:-1], x) if re.fullmatch(r"\{\w+\}", x) else re.sub(r"\{(\w+)\}", lambda m: str(vals.get(m[1], m[0])), x)) \
            if isinstance(x, str) else [fill(y) for y in x] if isinstance(x, list) else {k: fill(y) for k, y in x.items()} if isinstance(x, dict) else x
        out = []
        for st in r["steps"]:
            a = fill(st.get("args", {}))
            res = getattr(self, st["tool"])(**a) if hasattr(self, st["tool"]) and not st["tool"].startswith("_") else \
                (lambda j: (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")})(
                    self._job(st["tool"], a, worker=(a.get("session_id") or "").rsplit("-", 1)[0] or None))
            out.append({"tool": st["tool"], "result": res})
        return {"recipe": r["name"], "steps": out}

    def recall(self, query):
        hits = self.api.get("/api/kb/search", params={"q": query, "game": self.game or "", "k": 6}).json()
        return {"hits": hits} if hits else {"hits": [], "note": "nothing in the knowledge base yet; search the web"}

    # --- reverse-engineering library (gbox/re_lab.py): playbooks + per-title dossiers that grow with every task
    def _re_gid(self, game=""):
        q = game or getattr(self, "context_game", "") or self.game or ""
        if re.fullmatch(r"[0-9a-f]{16}", q or ""):
            return q
        if not q:
            raise ValueError("which game? pass game (title or game_id); none is running in this conversation")
        items = self.api.get("/api/catalog/best", params={"q": q, "limit": 1}).json()
        if not items:
            raise ValueError(f"no game matches {q!r}")
        return items[0]["game_id"]

    def re_playbook(self, op="list", query="", id="", lesson="", outcome="worked"):
        if op == "list":
            return {"playbooks": self.api.get("/api/re/playbooks", params={"q": query}).json(),
                    "next": "re_playbook op=get id=<the best match>"}
        if op == "get":
            r = self.api.get(f"/api/re/playbooks/{id}")
            return {"text": r.json().get("text")} if r.status_code == 200 else {"error": f"no playbook {id!r}: op=list first"}
        if op == "learn":
            r = self.api.post(f"/api/re/playbooks/{id}/lessons", json={"lesson": lesson, "outcome": outcome, "game": self.game or ""})
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
        return {"error": "op: list | get | learn"}

    def re_dossier(self, op="read", game="", kind="note", address="", name="", role="", status="hypothesis", evidence=None,
                   question=""):
        gid = self._re_gid(game)
        if op == "read":
            return {"game_id": gid, "text": self.api.get(f"/api/re/dossier/{gid}").json().get("text")}
        if op == "record":
            return self.api.post(f"/api/re/dossier/{gid}/findings", json={"kind": kind, "address": str(address or ""), "name": name,
                                 "role": role, "status": status, "evidence": evidence or [], "question": question}).json()
        return {"error": "op: read | record"}

    def re_study(self, game="", source="auto", session_id="", analyze=True):
        gid = self._re_gid(game)
        if source == "ram" and session_id:
            session_id = resolve_read_session(session_id, gid, self.api.get("/api/sessions").json(),
                                              getattr(self, "context_session_id", ""))
        d = self.api.get(f"/api/re/dossier/{gid}").json()
        ex = d.get("executable")
        if not ex or source == "ram":
            if source == "ram" and session_id and (bad := self._live_session(session_id)):
                return bad
            j = self._job("re_executable", {"game_id": gid, "source": source, "session_id": session_id}, node="linux", limit=3600)
            if j.get("state") != "succeeded":
                return {"error": f"re_executable {j.get('state')}: {j.get('error')}",
                        "next": "if the disc route fails, get the game to gameplay and use source=ram with its session_id"}
            ex = j["output"]
            self.api.post(f"/api/re/dossier/{gid}/study", json={"executable": ex})
        an = d.get("analysis")
        if analyze and (not an or an.get("elf_sha256") != ex.get("sha256")):
            j = self._job("analyze_binary", {"binary_path": ex["elf_path"], "processor": ex.get("processor")}, node="linux", limit=3600)
            if j.get("state") != "succeeded":
                return {"executable": ex, "error": f"Ghidra analysis {j.get('state')}: {j.get('error')}"}
            rc = self.api.get(f"/api/receipts/{j['receipt_id']}").json() if j.get("receipt_id") else {}
            sha = next((a.get("sha256") for a in rc.get("artifacts", []) if a.get("name") == "analysis.json"), None)
            from . import re_lab
            a = self.api.get(f"/api/artifacts/{sha}", timeout=300).json() if sha else {}
            an = re_lab.summarize_analysis(a, sha) | {"elf_sha256": ex.get("sha256")} if a else \
                {"functions": j["output"].get("functions"), "strings": j["output"].get("strings"), "elf_sha256": ex.get("sha256")}
            self.api.post(f"/api/re/dossier/{gid}/study", json={"analysis": an})
        text = self.api.get(f"/api/re/dossier/{gid}").json().get("text")
        return {"game_id": gid, "elf_path": ex.get("elf_path"), "processor": ex.get("processor"), "dossier": text,
                "next": "re_playbook op=list query=<your task>; record findings with re_dossier op=record"}

    def remember(self, text, title=""):
        r = self.api.post("/api/kb", json={"text": text, "title": title, "source": "agent", "game": self.game or "", "kind": "fact"}).json()
        return {"saved": r.get("added", 0)}

    def offer_controls(self, controls, title=""):
        ok = [c for c in controls if c.get("label") and (c.get("max_for") or c.get("tool") and isinstance(c.get("input"), dict))]
        if not ok:
            return {"error": "each control needs label, tool and input (or max_for: the label of a slider whose maximum it sets)"}
        bad = [c["tool"] for c in ok if c.get("tool") and c["tool"] not in WORKER_TOOLS]
        if bad:
            return {"error": f"controls can only run {sorted(WORKER_TOOLS)}; not {bad}"}
        return {"offered": [c["label"] for c in ok], "note": "the operator now has these controls in the chat",
                "_cards": {"kind": "controls", "title": title, "items": [{**c, "kind": c.get("kind", "slider")} for c in ok]}}

    def browse(self, url, op="open"):
        j = self._job("browse", {"op": op, "url": url}, node="windows", limit=60)
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def show_asset(self, query=""):
        pk = self.api.get("/api/uap", params={"q": query}).json()
        if not pk and query:
            words = query.lower().split()
            pk = [p for p in self.api.get("/api/uap").json() if any(w in p["package"] for w in words)]
        if not pk:
            return {"error": f"no asset package matches {query!r}", "packages": [p["package"] for p in self.api.get("/api/uap").json()]}
        return {"shown": [p["package"] for p in pk[:3]], "stats": pk[:3],
                "_cards": [{"type": "cards", "kind": "asset", "items": [{"package": p["package"], **{k: v for k, v in p.items() if k != "package"}}]}
                           for p in pk[:3]]}

    def image_search(self, query, n=8, gif=False):
        r = httpx.get(f"{self.searx}/search", params={"q": query, "format": "json", "categories": "images", "safesearch": 1,
                                                       "language": "en", "engines": "google images,bing images,pinterest"}, timeout=30).json()
        out = []
        for x in r.get("results", []):
            img = x.get("img_src") or ""
            if not img.startswith("http") or img.lower().endswith(".svg") or (gif and ".gif" not in img.lower() and "giphy" not in img and "tenor" not in img):
                continue
            out.append({"title": x.get("title"), "url": x.get("url"), "img": img, "thumb": x.get("thumbnail_src") or img})
            if len(out) >= max(1, min(n, 16)):
                break
        return {"images": [{"title": o["title"], "url": o["url"]} for o in out], "_cards": {"kind": "gif" if gif else "images", "items": out}}

    def show_gif(self, query):
        r = self.image_search(f"{query} reaction gif", n=1, gif=True)
        return r if r["images"] else {"error": "no gif found"}

    def search_games(self, query, platform=""):
        items = self.api.get("/api/catalog/best", params={"q": query, "limit": 12}).json()
        if platform:
            items = [g for g in items if g.get("platform") == platform] or items
        return {"best_first": True, "games": [{k: g.get(k) for k in ("game_id", "title", "system", "platform", "core", "year")} for g in items[:10]]}

    def launch_game(self, game_id, where="local", debug=False, mod=""):
        node = {"spark": "linux", "local": self.local_worker or "auto"}.get(where, where)
        r = self.api.post(f"/api/games/{game_id}/launch", params={"node": node, "debug": bool(debug), **({"mod": mod} if mod else {})}).json()
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

    def debugger(self, session_id, op, address=None, kind="exec", count=24):
        args = {"kind": kind, "count": count}
        if address not in (None, ""):
            args["address"] = self._addr(address)
        r = self._rpc(session_id, f"debug_{op}", args)
        if op == "disasm":
            return [f"{x['addr']:08X}  {x['mnemonic']} {x['operands']}" for x in r]
        if isinstance(r, dict) and r.get("regs"):
            r["regs"] = {k: f"{v:08X}" for k, v in r["regs"].items()}
        return r

    def find_code_that_writes(self, session_id, address, label, length=2, trigger_key=""):
        from pathlib import Path
        from .bridge import Bridge
        br = Bridge(str(self.api.base_url).rstrip("/"), self.api.headers["authorization"].split()[-1], session_id, log=lambda *a: None)
        def trigger():
            if trigger_key:
                br.api.post(f"/api/sessions/{session_id}/input", json={"events": [{"key": trigger_key, "down": True}]})
                time.sleep(0.15)
                br.api.post(f"/api/sessions/{session_id}/input", json={"events": [{"key": trigger_key, "down": False}]})
        addr = self._addr(address)
        read = lambda: br.rpc("read_memory", address=addr, length=int(length))
        info = br.rpc("info")
        local = Path(__file__).resolve().parent.parent / "gbox-data" / "analysis"
        local.mkdir(parents=True, exist_ok=True)
        r = br.trace_writer(addr, int(length), trigger, info.get("game_id") or info.get("title", "?"), label,
                            analysis_dir_local=local, analysis_dir_worker=self.analysis_share, read_value=read)
        if r.get("decompiled"):
            r["decompiled"] = r["decompiled"][:2500]
        return r

    def cheats(self, session_id, op="list", index=None, codes=None, desc="", query=""):
        validate_cheat_call(op, index, codes)
        j = self.api.post("/api/jobs", json={"tool": "cheats", "require_worker": session_id.split("-")[0],   # the session's worker
                                             "input": {"session_id": session_id, "op": op, "index": index, "codes": codes or [],
                                                       "desc": desc, "query": query}}).json()
        t = time.time()
        while j.get("state") in ("queued", "running") and time.time() - t < 120:
            time.sleep(0.5)
            j = self.api.get(f"/api/jobs/{j['id']}").json()
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def memory_search(self, session_id, op="start", type="u32", value=None, cmp="changed", ranges=None):
        j = self._job("memory_search", {"session_id": session_id, "op": op, "type": type, "value": value, "cmp": cmp,
                                        "ranges": ranges or []}, worker=session_id.rsplit("-", 1)[0])
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def pick(self, session_id, x, y):
        j = self._job("pick", {"session_id": session_id, "x": x, "y": y}, worker=session_id.rsplit("-", 1)[0])
        r = (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}
        if r.get("package"):
            r["_cards"] = {"kind": "asset", "items": [{"package": r["package"]}]}
        return r

    def pso_inventory(self, session_id, op="list", code="", count=1, value=None):
        j = self._job("pso_inventory", {"session_id": session_id, "op": op, "code": code, "count": count, "value": value},
                      worker=session_id.rsplit("-", 1)[0])
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def pso_item_search(self, query):
        words = query.lower().split()
        items = self.api.get("/api/pso/items", params={"version": "gc" if "episode" in (self.game or "").lower() else "dcv2"}).json()
        hit = [i for i in items if all(w in i["name"].lower() for w in words)] or [i for i in items if any(w in i["name"].lower() for w in words)]
        return {"items": hit[:25]}

    def pso_drops(self, session_id, op="status", factor=2.0, boxes=True, code=""):
        j = self._job("pso_drops", {"session_id": session_id, "op": op, "factor": factor, "boxes": boxes, "code": code}, worker=session_id.rsplit("-", 1)[0])
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def pso_mods(self, session_id, op="status", on=True, value=999999, code="", count=1, equip=False, name="", target="", rare=False):
        j = self._job("pso_mods", {"session_id": session_id, "op": op, "on": on, "value": value, "code": code, "count": count,
                                   "equip": equip, "name": name, "target": target, "rare": rare},
                      worker=session_id.rsplit("-", 1)[0])
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def re_mods(self, session_id, op="status", item="", count=0, target="", on=True, seconds=0, character="", items=None,
                fire_rate="", damage=None, reset=False, multiplier=None, kind="", force=None, direction="", speed=None):
        inp = {"session_id": session_id, "op": op, "item": item, "count": count, "target": target, "on": on, "seconds": seconds,
               "character": character, "items": items or [], "fire_rate": fire_rate, "reset": reset, "kind": kind,
               "direction": direction}
        for k, v in (("multiplier", multiplier), ("force", force), ("speed", speed)):
            if v is not None:
                inp[k] = v
        if damage is not None:
            inp["damage"] = damage
        j = self._job("re_mods", inp, worker=session_id.rsplit("-", 1)[0])
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def re_inventory(self, session_id, op="get", item="", amount=0, slot=-1, character="", items=None):
        inp = {"session_id": session_id, "op": op, "item": str(item or ""), "amount": int(amount or 0),
               "slot": int(slot if slot is not None else -1), "character": character or "", "items": items or []}
        j = self._job("re_inventory", inp, worker=session_id.rsplit("-", 1)[0])
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def re6(self, op="status", session_id="", **kw):
        inp = {"op": op, "session_id": session_id, **{k: v for k, v in kw.items() if v not in (None, "", [])}}
        j = self._job("re6", inp, worker=session_id.rsplit("-", 1)[0] if session_id else None, limit=1800) if session_id \
            else self._job("re6", inp, node="windows", limit=1800)
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def re4r(self, op="status", session_id="", **kw):
        inp = {"op": op, **{k: v for k, v in kw.items() if v not in (None, "", [])}}
        j = self._job("re4r", inp, node="windows", limit=3600)
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def zelda(self, session_id, op="list", item="", count=0, button="", on=True):
        j = self._job("zelda", {"session_id": session_id, "op": op, "item": item, "count": count, "button": button, "on": on},
                      worker=session_id.rsplit("-", 1)[0])
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def gta_mods(self, session_id, op="status", on=True, value=None, button=None, max_height=None, count=None, behaviour=None,
                 height=None, radius=None, model=None, explosion=None):
        inp = {"session_id": session_id, "op": op, "on": on, "value": value, "button": button, "max_height": max_height,
               "count": count, "behaviour": behaviour, "height": height, "radius": radius, "model": model, "explosion": explosion}
        j = self._job("gta_mods", {k: v for k, v in inp.items() if v is not None}, worker=session_id.rsplit("-", 1)[0])
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def ac_mods(self, session_id, op="build", part="", slot="", parts=None, value=0, query="", goal="", force=False):
        j = self._job("ac_mods", {"session_id": session_id, "op": op, "part": part, "slot": slot, "parts": parts or [], "value": value,
                                  "query": query, "goal": goal, "force": force}, worker=session_id.rsplit("-", 1)[0])
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def zelda_oot(self, session_id, op="state", place="", item="", c_button=0, kit="", factor=1.0, cutscene=False):
        j = self._job("zelda_oot", {"session_id": session_id, "op": op, "place": place, "item": item, "c_button": c_button,
                                    "kit": kit, "factor": factor, "cutscene": cutscene}, worker=session_id.rsplit("-", 1)[0])
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def autoplay(self, session_id, op="status", mission="", assist=False):
        j = self._job("autoplay", {"session_id": session_id, "op": op, "mission": mission, "assist": assist}, worker=session_id.rsplit("-", 1)[0])
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def mod(self, session_id, op="list", name="", desc="", changes=None, capture=False):
        j = self._job("mod", {"session_id": session_id, "op": op, "name": name, "desc": desc, "changes": changes or [],
                              "capture": bool(capture)}, worker=session_id.rsplit("-", 1)[0])
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def game_link(self, op, host, guest, trigger=None, win=None, lose=None, on_win="god_hit", on_lose="god_miss"):
        j = self._job("game_link", {"op": op, "host": host, "guest": guest, "trigger": trigger or {}, "win": win or {},
                                    "lose": lose or {}, "on_win": on_win, "on_lose": on_lose}, worker=host.rsplit("-", 1)[0])
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def bevy_scene(self, items, name="scene", camera=None, screenshot=True):
        j = self._job("bevy_scene", {"name": name, "items": items, "camera": camera or {}, "screenshot": bool(screenshot)}, "windows", 3600)
        out = j.get("output") or {}
        if j["state"] != "succeeded":
            return {"state": j["state"], "error": j.get("error")}
        res = {k: out.get(k) for k in ("scene", "screenshot", "pid")}
        try:                                                   # the screenshot as an image in the chat sidebar
            arts = self.api.get(f"/api/receipts/{j['receipt_id']}").json().get("artifacts", [])
            res["artifact"] = next((a["sha256"] for a in arts if a["name"] == "bevy.png"), None)
        except Exception:
            pass
        return res

    def scene_capture(self, session_id):
        j = self._job("scene_capture", {"session_id": session_id}, worker=session_id.split("-")[0], limit=900)
        if j["state"] != "succeeded":
            return {"state": j["state"], "error": j.get("error")}
        arts = self.api.get(f"/api/receipts/{j['receipt_id']}").json().get("artifacts", [])
        self._job("session_op", {"session_id": session_id, "op": "resume"}, worker=session_id.split("-")[0], limit=30)
        return {"glb": j["output"]["glb"], "summary": j["output"].get("summary"), "resumed": True,
                "artifact": next((a["sha256"] for a in arts if a["name"] == "frame.png"), None)}

    def open_in_blender(self, character="", package=""):
        if package:
            r = self.api.post(f"/api/uap/{package}/clipboard")
            return r.json() | {"note": "on the gBox clipboard: Ctrl+Shift+V in Blender"} if r.status_code == 200 else {"error": r.text[:300]}
        return self.characters(op="blender", character=character)

    def analyze_binary(self, binary_path, processor=None):
        j = self._job("analyze_binary", {"binary_path": binary_path, "processor": processor or None}, limit=3600)
        return {"state": j["state"], "error": j.get("error"), "output": j.get("output"), "receipt": j.get("receipt_id")}

    def ghidra_script(self, binary_path, script, args=None, processor=None):
        j = self._job("ghidra_script", {"binary_path": binary_path, "script": script, "args": args or [], "processor": processor or None},
                      limit=3600)
        res = {"state": j["state"], "error": j.get("error"), "output": j.get("output")}
        try:
            arts = self.api.get(f"/api/receipts/{j['receipt_id']}").json().get("artifacts", [])
            log = next((a["sha256"] for a in arts if a["name"] == "ghidra_script.log"), None)
            if log:
                res["log_tail"] = self.api.get(f"/api/artifacts/{log}").text[-3000:]
        except Exception:
            pass
        return res

    def video(self, op="search", query="", url="", n=8, at=0.0):
        j = self._job("video", {"op": op, "query": query or (self.game and op == "search" and self.game) or "", "url": url,
                                "n": n, "at": at}, "linux", 900)
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def file_mod(self, game_id, op="list", name="", changes=None):
        j = self._job("file_mod", {"game_id": game_id, "op": op, "name": name, "changes": changes or {}}, "windows", 7200)
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def rom_export(self, op="export", mod_id="", game_id="", mods=None, name=""):
        j = self._job("rom_export", {"op": op, "mod_id": mod_id, "game_id": game_id, "mods": mods or [], "name": name},
                      "linux", 7200)
        res = (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}
        if op == "export" and res.get("files"):          # keep the chat reply short: what's there and where
            res = {k: res.get(k) for k in ("title", "game", "platform", "image", "rel_dir", "patches", "cheat_files",
                                           "components", "warning", "note")}
        return res

    def script_patch(self, session_id, op="status", preset=""):
        j = self._job("script_patch", {"session_id": session_id, "op": op, "preset": preset}, worker=session_id.rsplit("-", 1)[0])
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

    def unreal_script(self, path, op="summary", cls="", function="", query=""):
        node = "windows" if path.startswith(("//", "\\")) else None   # UNC disc folders are read by the Windows worker
        j = self._job("unreal_script", {"path": path, "op": op, "cls": cls, "function": function, "query": query}, node)
        return (j.get("output") or {}).get("result") or {"state": j["state"], "error": j.get("error")}

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

    def _live_session(self, session_id):
        """None if the session is running, else an error naming the running ones (LLMs mistype ids)."""
        live = [x for x in self.api.get("/api/sessions").json() if x.get("state") == "running"]
        if session_id in {x["session_id"] for x in live}:
            return None
        return {"error": f"no such session {session_id!r}; running sessions: " +
                         (", ".join(f"{x['session_id']} ({x.get('title')})" for x in live) or "none")}

    def look_at_screen(self, session_id, question="Describe what is on screen."):
        if bad := self._live_session(session_id):
            return bad
        j = self._job("get_frame", {"session_id": session_id})
        if j["state"] != "succeeded":
            return {"error": f"frame capture failed: {j.get('error') or j.get('state')}"}
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

    def characters(self, op="list", character="", session_id="", game="", slot="player", kind="", x=None, y=None,
                   from_clipboard=False, a="", b="", one_way=False, near="", size=0.0):
        require_character(op, character)
        if session_id and (bad := self._live_session(session_id)):
            return bad  # preserve the requested live target; never silently relaunch a different session
        if not session_id and not game and op in ("collect", "extract", "use", "add", "swap", "place", "unplace"):   # the chat's game
            game = getattr(self, "context_game", "") or ""
        inp = {"op": op, "character": character, "session_id": session_id, "game": game, "slot": slot,
               "kind": kind or ("object" if op == "extract" else "character"), "x": x, "y": y, "from_clipboard": bool(from_clipboard),
               "a": str(a or ""), "b": str(b or ""), "one_way": bool(one_way), "near": near or "", "size": float(size or 0)}
        # extract / add / blender write the collection: they run where it lives (the Spark)
        j = self._job("characters", inp, limit=14400 if op == "collect" else 3600, node=None if op == "use" and session_id else "linux")
        result = (j.get("output") or {}).get("result") or {"state": j.get("state"), "error": j.get("error")}
        if op in ("use", "live_use"):
            outcome = native_swap_result({"state": j.get("state"), "error": j.get("error"), "result": result})
            result = result | {"native_swap_verified": outcome["verified"]}
            if not outcome["verified"]:
                result["next"] = outcome["reason"]
        return result

    def rea_tools(self, query="", name=""):
        from .rea_tool import discover, DiscoverIn
        out = discover(DiscoverIn(query=query, name=name), None)
        if name:
            out["tools"] = [{k: t[k] for k in ("gbox_name", "description", "inputSchema", "effects", "examples")} for t in out["tools"]]
        return out

    def read_rea_result(self, sha256, pointer="", offset=0, limit=20):
        job = self._job("read_rea_result", {"sha256": sha256, "pointer": pointer, "offset": offset, "limit": limit}, node="linux")
        return job.get("output") or {"state": job.get("state"), "error": job.get("error")}

    def run_tool(self, name, input, worker_id=None, node=None):
        worker = worker_id or (getattr(self, "rea_worker", None) if name.startswith("rea_") and not node else None)
        j = self._job(name, input, worker=worker, node=node, limit=1140 if name.startswith("rea_") else 900)
        if name.startswith("rea_") and j.get("worker_id"):
            self.rea_worker = j["worker_id"]
        output = j.get("output")
        if name.startswith("rea_") and isinstance(output, dict) and isinstance(output.get("result"), dict):
            # MCP text duplicates structured content; put the useful evidence
            # first within the model's context budget, retaining its artifact ID.
            output = dict(output, result=output["result"].get("structuredContent") or output["result"])
            if j["output"]["result"].get("_gbox_truncated"):
                output["_gbox_truncated"] = True
                output["full_result_artifact"] = output.get("evidence_sha256")
        return {"state": j.get("state", "failed"), "error": j.get("error") or j.get("detail"), "output": output,
                "receipt": j.get("receipt_id"), "worker_id": j.get("worker_id")}

    # --- conversation loop ---
    def run(self, messages: list[dict], emit, context: dict, max_steps: int = 40) -> dict:
        """messages: OpenAI-style history (mutated). emit(event) streams steps to the UI. Returns usage totals."""
        self.local_worker = context.get("local_worker")
        self.parent_request_id = context.get("request_id")
        self.context_game = context.get("game_id") or context.get("game_title") or ""
        latest = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        plain = latest.split("\n[context:", 1)[0].strip() if isinstance(latest, str) else ""
        if re.fullmatch(r"(?:hi|hello|hey|hey there|good morning|good afternoon|good evening)[!?.\s]*", plain, re.I):
            game = context.get("game_title")
            answer = f"Hi! What would you like to do with {game}?" if game else "Hi! What would you like to do in gBox?"
            messages.append({"role": "assistant", "content": answer})
            emit({"type": "assistant", "text": answer})
            return {"usage": {"in": 0, "out": 0}, "tools": {}}
        continued = False
        if len(messages) >= 3 and messages[-1].get("role") == "user" and messages[-2].get("role") == "tool" \
                and str(messages[-2].get("content") or "").startswith("asked;") and messages[-3].get("role") == "assistant":
            # continuation of a questionnaire: the operator's message IS their clicked answer. Rewrite the pending
            # tool result so the ask_user call literally returns the answer, and reframe the user message so the
            # model's "current request" reads unambiguously - weak local models otherwise repeat the question.
            answer = str(messages[-1].get("content") or "").split("\n[context:", 1)[0].strip()
            q = ""
            for tc in messages[-3].get("tool_calls") or []:
                if tc["function"]["name"] == "ask_user":
                    try:
                        q = str(json.loads(tc["function"].get("arguments") or "{}").get("question") or "").strip()
                    except ValueError:
                        pass
                    break
            messages[-2]["content"] = f"the operator answered: {answer}"
            tail = " Go ahead with this." if answer.endswith((".", "!", "?")) else ". Go ahead with this."
            messages[-1]["content"] = f"My answer{(' to the question \"' + q + '\"') if q else ''}: {answer}{tail}"
            continued = True
        sid = context.get("session_id")
        if sid:                                                # the app can hand over a stale id (game relaunched): use the live one
            try:
                live = [x for x in self.api.get("/api/sessions").json() if x.get("state") == "running"]
                if sid not in {x["session_id"] for x in live}:
                    same = [x for x in live if x["session_id"].split("-")[0] == sid.split("-")[0]] or \
                           [x for x in live if context.get("game_title") and x.get("title") == context.get("game_title")]
                    if same:
                        context["session_id"] = same[0]["session_id"]
                        for m in reversed(messages):           # the request's context line carries the id the LLM will copy
                            if m.get("role") == "user" and isinstance(m.get("content"), str) and sid in m["content"]:
                                m["content"] = m["content"].replace(sid, context["session_id"])
                                break
            except Exception:
                pass
        self.context_session_id = context.get("session_id") or ""
        tools, usage, used = tool_specs(), {"in": 0, "out": 0}, {}
        if continued:                                           # this turn answers a questionnaire: no re-asking mid-flow
            tools = [t for t in tools if t["function"]["name"] != "ask_user"]
        self.recipes = {}
        try:                                                   # learned tools for this game (and any-game ones)
            for r in self.api.get("/api/recipes").json():
                g = (r.get("game") or "").lower()
                if not g or g in (context.get("game_title") or "").lower():
                    self.recipes["recipe_" + r["name"]] = r
                    tools.append({"type": "function", "function": {"name": "recipe_" + r["name"], "description": "[learned] " + r["description"],
                                  "parameters": {"type": "object", "properties": {k: {"type": "string", "description": v}
                                                 for k, v in (r.get("params") or {}).items()}, "required": []}}})
        except Exception:
            pass
        for n, sha in enumerate(context.get("images") or [], 1):   # pasted images: the vision model reads them for the LLM
            emit({"type": "tool_call", "name": "vision", "args": {"image": sha}})
            question = next((m["content"] for m in reversed(messages) if m.get("role") == "user" and isinstance(m.get("content"), str)), "")
            try:
                png = self.api.get(f"/api/artifacts/{sha}").content
                if not self.vision:
                    raise RuntimeError("no vision model configured (agent.vision_model)")
                r = httpx.post(f"{self.llm_url}/chat/completions", timeout=300, json={"model": self.vision, "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "The operator attached this image to their message to a game-lab assistant. Describe everything "
                                             "relevant: UI, text (transcribe it), game scene, errors, highlighted or annotated areas. "
                                             f"Their message: {question[:1500]}"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}]}).json()
                desc = r["choices"][0]["message"]["content"].strip()
            except Exception as e:
                desc = f"(could not analyse the image: {e})"
            emit({"type": "tool_result", "name": "vision", "text": desc[:4000]})
            # into the operator's own message: chat models answer from it reliably (a separate system note gets ignored)
            last = next((m for m in reversed(messages) if m.get("role") == "user" and isinstance(m.get("content"), str)), None)
            note = (f"\n\n[Attached image {n}. You cannot see pixels; this is what the vision model read in it, use it as what "
                    f"the image shows: {desc[:3000]}]")
            if last:
                last["content"] += note
            else:
                messages.append({"role": "user", "content": note.strip()})
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
        seen: dict[str, str] = {}
        bm = {"sid": context.get("session_id"), "before": None, "tools": [], "calls": [], "verified": False}   # bookmark of this request
        q = next((x["content"] for x in reversed(messages) if x.get("role") == "user" and isinstance(x.get("content"), str)), "")
        try:                                                   # knowledge base first: answers gBox already found before
            ask = q.split("\n[context:")[0][:1000]            # search the request, not the context blob (it matched every chat)
            hits = self.recall(ask)["hits"] if ask else []
        except Exception:
            hits = []
        g = (self.game or "").lower()                          # only this game's knowledge (or game-independent facts):
        hits = [h for h in hits if (not (h.get("game") or "") and h.get("kind") != "answer")   # another game's answers were being parroted
                or (g and g[:24] in (h.get("game") or "").lower()) or ((h.get("game") or "").lower()[:24] in g and h.get("game"))]
        hits = [h for h in hits if h.get("score", 1) >= 0.55]
        if hits:
            emit({"type": "tool_call", "name": "recall", "args": {"query": q[:120]}})
            emit({"type": "tool_result", "name": "recall", "text": json.dumps(hits, default=str)[:4000]})
            messages.append({"role": "system", "content": "KNOWLEDGE BASE - reference notes, NOT a reply: never repeat an earlier answer "
                             "as your answer; act on the operator's CURRENT request with tools ('answer' entries may be unverified, "
                             "'fact'/'wiki' are stronger). Use them to skip web searches they already answer:\n"
                             + "\n---\n".join(f"[{h['kind']}] {h['title']} ({h['source']}): {h['text'][:900]}" for h in hits)})
        tool_names = {t["function"]["name"] for t in tools}     # tools the model may call this turn
        for _ in range(max_steps):
            for attempt in range(3):                           # retry transient runner OOMs and malformed tool calls
                r = httpx.post(f"{self.llm_url}/chat/completions", timeout=600,
                               json={"model": self.model, "messages": messages, "tools": tools,
                                     "temperature": 0.2 + 0.25 * attempt}).json()
                if "choices" in r:
                    break
                error = json.dumps(r).lower()
                if "out of memory" in error and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                if "error parsing tool call" not in error or attempt == 2:
                    break
            if "choices" not in r:
                raise RuntimeError(f"LLM error: {json.dumps(r)[:300]}")
            u = r.get("usage") or {}
            usage["in"] += u.get("prompt_tokens", 0)
            usage["out"] += u.get("completion_tokens", 0)
            m = r["choices"][0]["message"]
            calls = m.get("tool_calls") or []
            messages.append({"role": "assistant", "content": m.get("content") or "", **({"tool_calls": calls} if calls else {})})
            if not calls:
                answer = re.sub(r"(?s)<think>.*?</think>", "", m.get("content") or "").strip()
                emit({"type": "assistant", "text": answer})
                if bm["tools"]:                                     # major change: before/after save states + bookmark
                    q0 = next((x["content"] for x in reversed(messages) if x.get("role") == "user" and isinstance(x.get("content"), str)), "")
                    after = self._bookmark_state(bm["sid"])
                    request = q0.split("\n\n[Attached")[0].split("\n[context:")[0].strip()
                    emit({"type": "bookmark", "request": request[:300], "answer": answer[:300],
                          "tools": sorted(set(bm["tools"])), "session_id": bm["sid"], "before": bm["before"], "after": after})
                    if bm["calls"]:                                  # every change that worked becomes a switch in Controls
                        try:
                            self.api.post("/api/mods", json={"title": request[:80], "desc": answer[:600], "session_id": bm["sid"],
                                          "calls": bm["calls"], "verified": bm["verified"], "thumb": (after or {}).get("frame") or "",
                                          "state_slot": (after or {}).get("slot")})
                        except Exception:
                            pass
                if used and answer and not answer.startswith("("):    # learned by doing: keep the Q+A for next time
                    q = next((x["content"] for x in reversed(messages) if x.get("role") == "user" and isinstance(x.get("content"), str)), "")
                    self._learn(f"Q: {q[:1500]}\nA (tools: {', '.join(used)}): {answer[:4000]}", "chat", q[:80], "answer")
                return {"usage": usage, "tools": used}
            for c in calls:
                name = c["function"]["name"]
                if name == "ask_user":
                    if name not in tool_names:                  # withheld on answer turns: the operator already answered
                        messages.append({"role": "tool", "tool_call_id": c.get("id", name),
                                         "content": "ask_user is not available in this turn: the operator already answered "
                                                    "your question. Act on their answer now and reply."})
                        continue
                    # questionnaire: show clickable options, wait for the click
                    try:
                        a = json.loads(c["function"].get("arguments") or "{}")
                    except ValueError:
                        a = {}
                    q = str(a.get("question") or "").strip()
                    opts = list(dict.fromkeys(str(o).strip() for o in a.get("options") or []
                                              if o is not None and str(o).strip()))[:8]
                    if not opts:                                    # nothing clickable: fall back to plain text, never an empty box
                        emit({"type": "assistant", "text": q or "What would you like?"})
                        messages.append({"role": "tool", "tool_call_id": c.get("id", name),
                                         "content": "asked; no clickable options were provided"})
                        return {"usage": usage, "tools": used}
                    emit({"type": "choices", "question": q, "options": opts})
                    messages.append({"role": "tool", "tool_call_id": c.get("id", name), "content": "asked; the operator's choice is the next message"})
                    return {"usage": usage, "tools": used}
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except ValueError:
                    args = {}
                emit({"type": "tool_call", "name": name, "args": args})
                used[name] = used.get(name, 0) + 1
                changes_game = _modifies_game(name, args)
                if changes_game and bm["sid"]:
                    bm["tools"].append(name)
                    if bm["before"] is None:
                        bm["before"] = self._bookmark_state(bm["sid"])
                key = name + json.dumps(args, sort_keys=True, default=str)
                if key in seen and not name.startswith("rea_") and name not in ("look_at_screen", "read_memory", "memory_search", "memory_filter", "session_info",
                                                "debugger", "autoplay", "cheats"):          # live-state tools may legitimately repeat
                    result = {"repeat": True, "note": "You already ran exactly this; the result would be the same. Use what you have, "
                              "change the arguments, or try a different tool/approach.", "previous": seen[key][:1500]}
                else:
                    try:
                        if name not in {t["function"]["name"] for t in tools}:
                            raise ValueError(f"unknown tool {name}")
                        if name.startswith("rea_") and name != "rea_tools":
                            result = self.run_tool(name, args)
                        else:
                            result = self._run_recipe(self.recipes[name], args, context) if name in self.recipes else getattr(self, name)(**args)
                        if name == "rea_tools" and args.get("name"):
                            from .rea_tool import CATALOG
                            requested = args["name"].removeprefix("rea_")
                            contract = next((t for t in CATALOG["tools"] if t["name"] == requested), None)
                            direct = "rea_" + requested
                            if contract and direct not in {t["function"]["name"] for t in tools}:
                                tools.append({"type": "function", "function": {"name": direct,
                                              "description": contract["description"], "parameters": contract["inputSchema"]}})
                    except Exception as e:
                        result = {"error": f"{type(e).__name__}: {e}"}
                if isinstance(result, dict) and result.get("_cards"):     # link cards / image thumbnails for the chat
                    cards = result.pop("_cards")
                    for c in cards if isinstance(cards, list) else [cards]:
                        if c["items"]:
                            emit({"type": "cards", **{k: v for k, v in c.items() if k != "type"}})
                text = json.dumps(result, default=str)
                emit({"type": "tool_result", "name": name, "text": text[:4000]})
                if changes_game and bm["sid"] and isinstance(result, dict) and not result.get("error") and result.get("state") != "failed":
                    bm["calls"].append({"tool": name, "input": args})        # replayable as a mod switch
                    bm["verified"] |= '"verified": true' in text or '"landed": true' in text
                if isinstance(result, dict):                        # images for the live sidebar
                    for key, cap in (("frame", "screen capture"), ("artifact", "extracted")):
                        if result.get(key):
                            emit({"type": "media", "sha": result[key], "caption": f"{name}: {cap}"})
                seen[key] = text
                messages.append({"role": "tool", "tool_call_id": c.get("id", name), "content": text[:6000]})
        emit({"type": "assistant", "text": "(stopped: step limit reached — ask me to continue)"})
        return {"usage": usage, "tools": used}


# agent tool names that map 1:1 onto worker job tools (what a chat control may run directly)
WORKER_TOOLS = {"re_inventory", "re6", "re4r", "ac_mods", "gta_mods", "zelda", "re_mods", "pso_mods", "zelda_oot", "poke", "pso_inventory", "pso_drops", "freeze_memory", "write_memory", "graphics", "session_op", "autoplay", "script_patch", "cheats", "mod"}


# tools that change the running game: a request that uses one is bookmarked with save states before and after
MODIFIES = {"re_inventory", "re6", "re4r", "ac_mods", "gta_mods", "zelda", "re_mods", "pso_mods", "zelda_oot", "poke", "write_memory", "freeze_memory", "pso_drops", "pso_inventory", "mod", "script_patch", "cheats", "autoplay"}


def _modifies_game(name: str, args: dict) -> bool:
    """Only actual game changes earn a before/after state and a replayable mod card."""
    if name not in MODIFIES:
        return False
    op = str(args.get("op") or "").lower()
    if name == "mod":
        return op == "apply"     # list/verify are reads; save/delete edit files, not the running game
    return op not in {"list", "get", "status", "verify", "inspect", "info", "preview", "roster",
                      "coverage", "scan", "plan", "search", "describe", "query"}


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

    # benchmarked on real gBox requests (2026-10-06): these pick wrong tools / echo old answers; gpt-oss:20b was 5/5 at ~7.5 s a step
    WEAK_MODELS = {"nemotron-3-nano:4b", "granite4:tiny-h", "qwen3:0.6b", "qwen3:1.7b", "gemma3:1b", "gemma3:270m", "smollm2:135m"}
    TOOL_MODEL = "gpt-oss:20b"
    VISION_TOOL_MODEL = "gemma4:12b"                         # tools + vision (+ audio, thinking) for screenshot requests

    def post(self, cid: str, text: str, context: dict, api_requests, model: str | None = None, images: "list[str] | None" = None) -> dict:
        with self.lock:
            c = self.get(cid)
            if model == "auto":                # Auto: the fast tool model; a vision+tools model when there are images
                model = self.VISION_TOOL_MODEL if images else self.TOOL_MODEL   # ponytail: two-way pick, add task routing if needed
            elif model in self.WEAK_MODELS:                  # too small to drive tools: use the fast tool model, and say so
                c["events"].append({"type": "assistant", "ts": time.time(),
                                    "text": f"({model} can't drive gBox's tools reliably - using {self.TOOL_MODEL}, which is as fast and gets them right.)"})
                model = self.TOOL_MODEL
            if model:
                c["model"] = model
            c["title"] = c.get("title") or text.splitlines()[0][:80]
            c["updated"] = time.time()
            self._remember_game(c, context.get("game_id"), context.get("game_title"))
            if c["busy"]:                                    # queue it: runs as soon as the current request finishes
                c.setdefault("queue", []).append({"text": text, "context": context, "images": images, "model": model})
                c["events"].append({"type": "queued", "text": text, "position": len(c["queue"]), "ts": time.time()})
                self.store.put("chat", cid, c)
                return c
            ctx_line = f"\n[context: {json.dumps(context)}]" if context else ""
            c["messages"].append({"role": "user", "content": text + ctx_line})
            c["events"].append({"type": "user", "text": text, "ts": time.time(), **({"images": images} if images else {})})
            c["busy"] = True
            self.store.put("chat", cid, c)
        threading.Thread(target=self._turn, args=(cid, text, context | ({"images": images} if images else {}), api_requests),
                         daemon=True).start()
        return c

    GAP_ERR = re.compile(r'error|failed|traceback|"status": "missing"|unsupported|not supported|unknown tool|blocked|not attached', re.I)
    GAP_GAVE_UP = re.compile(r"\b(can't|cannot|couldn't|could not|unable to|not able to|no way to|isn't supported|not supported|"
                             r"no (tool|way|pipeline|writer|reader)|missing|blocked|don't have)\b", re.I)

    def _gap_report(self, cid, text, context, api_requests, status, note):
        """The local LLM failed this request: file an inbox report (source "gap") with what was asked, what it tried and
        what failed, so Claude builds the missing tool and the next attempt succeeds."""
        evs = self.get(cid).get("events", [])
        i = max((k for k, e in enumerate(evs) if e.get("type") == "user"), default=-1)
        turn = evs[i + 1:]
        calls = [e for e in turn if e.get("type") == "tool_call"]
        def failed(e):                                # a real error result, not the word "unsupported" in a capability list
            if e.get("type") == "error":
                return True
            t = (e.get("text") or "").strip()
            try:
                d = json.loads(t)
            except ValueError:
                return bool(re.match(r"(error|traceback|failed)", t, re.I))
            return isinstance(d, dict) and bool(d.get("error") or d.get("state") == "failed" or d.get("status") in ("missing", "blocked"))
        errs = [e for e in turn if e.get("type") in ("tool_result", "error") and failed(e)]
        final = next((e.get("text") or "" for e in reversed(turn) if e.get("type") == "assistant"), "")
        if status != "blocked":
            if final and not self.GAP_GAVE_UP.search(final):
                return                                # it recovered and delivered: errors on the way aren't a gap
            if not final and not errs:
                return
        game = context.get("game_title") or ""
        body = "\n".join([
            "## What the operator asked", text.strip(), "",
            f"## Context\ngame: {game or '-'} · session: {context.get('session_id') or '-'} · conversation: {cid}", "",
            "## What gBox's local LLM tried",
            *([f"- `{e.get('name')}` {json.dumps(e.get('args') or {})[:300]}" for e in calls] or ["- (no tool calls)"]), "",
            "## What failed",
            *([f"- {e.get('name') or e.get('type')}: {(e.get('text') or '')[:600]}" for e in errs] or ["- (no tool error)"]),
            *([f"- turn error: {note}"] if note else []), "",
            "## Its final answer", final[:1500] or "(none)", "",
            "## For Claude",
            "Make gBox able to do this next time: build or fix the tool(s) it lacked, make their specs self-describing, test "
            "with a real call, then re-run the request and reply here with what changed."])
        api_requests("create", {"title": f"GAP: {text.splitlines()[0][:90]}", "body": body, "source": "gap", "kind": "text",
                                "parent_request_id": context.get("request_id"), "context": context | {"conversation": cid}})

    def _turn(self, cid, text, context, api_requests):
        c, t0 = self.get(cid), time.time()
        reuse = bool(context.get("resolve_auto_report") and context.get("request_id")
                     and api_requests("get", {"id": context["request_id"]}))
        req = context["request_id"] if reuse else api_requests("create", {"title": text.splitlines()[0][:100],
            "body": text, "source": "gbox-chat", "kind": "text", "context": context | {"conversation": cid}})
        context = context | {"request_id": req, "conversation": cid}
        last_capture = [0.0, 0]
        turn_events = []

        def emit(ev):
            turn_events.append(ev)
            with self.lock:
                cur = self.get(cid)
                cur["events"].append(ev | {"ts": time.time()})
                self.store.put("chat", cid, cur)
            if (reuse and ev.get("type") == "tool_result" and ev.get("name") in
                    {"characters", "mod", "file_mod", "session_op", "re_mods", "re6", "re4r", "gta_mods"}
                    and context.get("session_id") and last_capture[1] < 12 and time.time() - last_capture[0] >= 5):
                last_capture[0], last_capture[1] = time.time(), last_capture[1] + 1
                threading.Thread(target=api_requests, args=("capture", {"id": req, "session_id": context["session_id"],
                    "text": f"Game frame after {ev.get('name')}",
                    "task_step": {"action": ev.get("name"), "attempt": str(last_capture[1]),
                                  "result": (ev.get("text") or "")[:2000], "status": "finished"}}), daemon=True).start()
        try:
            agent = self.make_agent(c.get("model"))
            res = agent.run(c["messages"], emit, context)
            launched = [a for a in getattr(agent, "launched", [])]
            status, note = "done", ""
            native = native_swap_outcome(turn_events)
            if native["required"] and not native["verified"]:
                status, note = "in_progress", native["reason"]
            else:
                required = required_operation_outcome(turn_events, _modifies_game)
                if required["unresolved"]:
                    status, note = "in_progress", required["reason"]
        except Exception as e:
            emit({"type": "error", "text": f"{type(e).__name__}: {e}"})
            res, status, note = {"usage": {"in": 0, "out": 0}, "tools": {}}, "blocked", str(e)
        with self.lock:
            cur = self.get(cid)
            cur["messages"], cur["busy"], cur["updated"] = c["messages"], False, time.time()
            for gid, title in (launched if "launched" in locals() else []):
                self._remember_game(cur, gid, title)
            nxt = cur["queue"].pop(0) if cur.get("queue") else None
            self.store.put("chat", cid, cur)
        if nxt:                                              # next queued request
            threading.Thread(target=self.post, args=(cid, nxt["text"], nxt.get("context") or {}, api_requests, nxt.get("model"),
                                                     nxt.get("images")), daemon=True).start()
        try:
            self._gap_report(cid, text, context, api_requests, status, note)
        except Exception:
            pass
        if req:
            api_requests("metrics", {"id": req, "tokens_in": res["usage"]["in"], "tokens_out": res["usage"]["out"],
                                     "tools": res["tools"], "duration_s": round(time.time() - t0, 1)})
            if reuse:
                final = next((e.get("text") or "" for e in reversed(self.get(cid).get("events") or [])
                              if e.get("type") == "assistant"), "")
                api_requests("reply", {"id": req, "text": final or note or "Resolution attempt ended without a result.",
                    "task_step": {"action": "automatic resolution attempt", "attempt": "1",
                                  "result": final or note or "No result", "status": status}})
                if status in ("blocked", "in_progress"):
                    api_requests("status", {"id": req, "status": "in_progress", "note": note or "Automatic attempt was blocked; further work is needed."})
            else:
                api_requests("status", {"id": req, "status": status, "note": note})
