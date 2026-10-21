# Autoplay

gBox plays a running game by itself (`autoplay` tool, gbox/tools.py). Modes: a game's own **playbook** (gbox/re4_merc_bot.py,
doa2_bot.py, ge007_bots.py), a PSO **mission**, a **replay** of the operator's recorded run from boot, their **learned**
style (gbox/imitate.py), or **vision** (screen -> model -> buttons). `auto` picks the first that fits, in that order.

## Bot demos on any PC

Operator 2026-10-20: "I want to be able to launch bot demos and watch them even from PCs I am active at ... launch bot
demos on computers that even I am on and be able to chat about the gameplay".

- **Where:** every launch menu offers "🤖 Bot demo on <PC>" for each online PC, the one you are on included: the library
  cards (🤖), the library right-click menu, the Sessions header (🤖 Demo ▾), and in the desktop app the docked game's
  right-click menu and a conversation's game chip (clients/web/viz/bot-demo.js).
- **What it is:** your own launch with autoplay on: `POST /api/games/{id}/launch?node=<PC>&autoplay=true`. It is not an
  agent job, so it never waits for an idle PC (background admission); an agent's demo (`x-gbox-actor: agent`) still is
  one. The launch asks for a jump state (`jump`), so a game with one boots straight into it.
- **Marked:** the control plane records it (`gbox.screensaver.autoplay_on_launch`, kind `bot_demo` by launch job), and
  `GET /api/sessions` says `bot_demo: true`. The Sessions header shows "🤖 Bot demo", keeps Stop and the coach box. A
  relaunch keeps the mark.
- **Autoplay starts by itself:** the screensaver loop starts it once the session is up (`demo: true`, as autoplay, with
  `agent_use` only when an agent launched it). A demo plays on like the screensaver does (a replay goes on in the learned
  style). Touching your pad hands the game to you. Stop ends it.
- **On a PC you are using:** the bot never takes your keyboard. Windows Dolphin input is keystrokes into the docked game,
  so a demo's input is polite (`gbox.adapters.polite_verdict`):
  - with the game's window holding the keyboard, it plays;
  - while you type in gBox (the coach box, a search field) or use another application, its presses wait and only key
    releases go out;
  - after 8 s without mouse or keyboard input, or when a coach note is sent, the game gets the keyboard back.
  A demo brings its window to the front only on a PC idle for a minute.
- **A frozen or black demo is relaunched** (`tools._bad_end`), same game and build on the same PC, into its jump state.
  Every worker-side autoplay request says `x-gbox-actor: autoplay`, so the audit shows autoplay, not the operator. The
  server lets autoplay relaunch only bot demos and agent test sessions, never the operator's own game.
  The black watch trusts RAM: black frames while the playbook's `ram_progress` or round `timer` moves are a fade or a
  load, not a hang.
- **Coaching:** the coach box (gbox/coaching.py) is in every running session's header, so on every bot demo. Each note
  goes on the game's coaching ticket with its moment (frame, save state, RAM). `scripts/agent_ledger.py` prints each new
  note at the inbox hook and lists the ticket first in `list`. The bulk Hermes queue never takes a coaching ticket
  (`hermes_work_queue.is_live_coaching`); MCP `list_requests` leaves it out unless `include_coaching` or `source=coach`.
- **Run lessons:** on a Mercenaries title (its RAM map has a `mercs` block), each coaching note, and each ⚑ report filed
  on one of its sessions (`POST /api/requests/issue`), is also one line of the title's run-lessons log, which the engine
  reads before its next round (`gbox.mercs.lessons`, `gbox-data/mercs/lessons/<map id>.jsonl`). The line is
  `{ts, kind: "coach" | "report", text, session_id, worker, telemetry, captures, summary, request_id, note}`
  (`mercs_bot.LESSON_KEYS`). Other titles, or no engine installed: nothing is written, and the note is filed anyway.
- **Kept mods stay yours:** the Sessions view switches your kept mods on by itself only in your own play. In a bot demo
  or an agent's session the card says "kept · not switched on here by itself", and Turn on still applies it
  (2026-10-20: kept mods landed three times on an agent's RE4 session, and its next stage load froze).

## Playbooks: from boot to gameplay

A playbook is a module with `matches(ad, g)`, `setup(ad) -> [failed ops]` and `play(ad, send, stopped, **kw) -> stats`,
listed in `tools.PLAYBOOKS`. A bot demo boots the game, so a playbook has to get itself from boot to gameplay and back
into gameplay after each round. Each one does it this way:

| | from boot | back into gameplay | when it can't tell |
|---|---|---|---|
| The Mercenaries on any title (mercs_bot) | `matches()` true for a title whose RAM map has a `mercs` block, once the engine is installed and READY; `play()` boots through the block's `menus` module from RAM (the shared `mercs_bot.Boot`) and hands each round to `gbox.mercs.engine.play_round` | the engine returns "round": the same menus again | as RE4 below; "lost" from the engine ends the run (a demo is relaunched) |
| RE4 GameCube (re4_merc_bot + re4_menus) | `matches()` true for the disc in any state; `play()` reads the screen and its cursor from RAM (`re4_menus.screen`: the title task's work area, only when main.dol's code bytes match `re4_menus.SIGNATURES`) and presses only `re4_menus.step()`: START on the title, THE MERCENARIES, GAME START, Leon, the Village | results: A; "You Are Dead": Continue Yes; then the same menus | saves the menu moment (a jump state at Select Player, before the hooks); RAM silent for 30 s, or a story game: the run ends, a demo is relaunched into it |
| DOA2 LE Dreamcast (doa2_bot) | `matches()` by game id; RAM's demo flag (0x8C200848) tells title from fight; a timed menu `ROUTE` (Start, Start, right, B...) | the jump state saved in a fight | two jumps that land nowhere drop it; still RAM: Start / B once, then a hang |
| GoldenEye PC port (ge007_bots) | the port boots straight into a bot match (`GE_STARTMP`); the bridge says `in_match` | `menus=True`: Start pulses between matches; the harness starts the next one | the bridge never opened: no playbook |

The rules a new playbook follows:

- `matches()` is true from boot (the disc or game id), not only in gameplay. Otherwise a demo that boots to its title
  gets no playbook.
- Get to gameplay from RAM: name the screen and the cursor from the game's own state machine, and press only what moves
  that screen towards gameplay. Never vision for this, and never a blind press: one can pick New Game or Load. On RE4,
  blind up + A started a story game with the Mercenaries hooks in, and Dolphin crashed (2026-10-20).
- Check the code before trusting the addresses: compare a few code bytes of the routines the fields come from (RE4:
  `re4_menus.SIGNATURES`). Another build or another game at those addresses names nothing ("unknown") and presses
  nothing.
- Save a menu moment or jump state where the game can be restored cleanly, before any code hooks: a Dolphin state
  saved after RE4's hooks restores into a hang. `jumpstate.save` uses gBox's demo slot, never the operator's.
- Apply code hooks once per boot, at a screen where they hold (RE4: Select Player). The same Dolphin taking the hooks
  again on top of the first set, plus kept mods, froze a stage load (2026-10-20). Calls that run game code (re_mods
  `equip`, give items) wait for a running room: `re_mods_tool.RE4.call` refuses during a load or a menu.
- Fill the stats dict as you go (the watch panel reads it): `screen`, `cursor`, `menu_presses`, and `ram_progress`,
  which counts up when RAM shows the game moving. The black watch trusts it.
- Off the path for good (a story game, menus RAM can't name)? Return with `stats["hung"] = True` and a reason. A bot
  demo is then relaunched, into its menu moment.
- Name only the keyword arguments you need: `tools._start_playbook` passes `stats`, `prompt`, `ram_prompt`, `style` and
  `game` (the session's game dict, for jump states) to a `play()` that names them.

## The Mercenaries on any title (gbox/mercs_bot.py)

Operator 2026-10-20: one system for every Resident Evil Mercenaries, on any console and PC, that knows "what screen is
up on the game by the very game hook and ram / hex signature ... from the internal state machine of the game itself".

- **A title takes part through its RAM map** (`profiles/gamedata/<map id>-ram.json`): a top-level `mercs` block. The
  deployment layer reads `menus` (the module that names the title's screens from RAM: `screen(m, merc=None)`,
  `step(scr)`, `wandered(scr)`), `package` (`[[op, kwargs], ...]`, the re_mods hack package), `early_ops` (the RAM-only
  ops that go in at once: the unlock bits) and `jump_at` (the screen where the menu moment is saved and the hooks go
  in). The engine's own keys sit beside them (docs/mercenaries_engine.md).
- **The profile is found by the session's game** (catalog id or disc id, `ram_map.find`), else by the game's own memory
  (`ram_map.detect`). The playbook runs in the worker beside the emulator: menus are read every 0.25 s; rounds run on
  the engine's frame-synced tick.
- **`play()`**: the early ops, then the boot loop (`mercs_bot.Boot`: one press at a time from `menus.step`, the menu
  moment and the hooks once at `jump_at`). Each time the screen says `playing` it calls
  `engine.play_round(profile, m, send, stopped, stats, lessons)`: "round" goes back to the menus for the next one,
  "lost" ends the run with `stats["hung"]` (a demo is relaunched into its menu moment), "stopped" ends it. Each round's
  frames also go to the tactical map beside the stream (`tactical=`, docs/tactical_map.md). `lessons` is
  `entry -> gbox.mercs.lessons.append(map_id, entry, run=<this run>)`.
- **Until the engine is installed and `engine.READY`**, `mercs_bot.matches()` is false and each title keeps its own
  playbook (RE4: re4_merc_bot, whose menus run on the same `Boot`).
