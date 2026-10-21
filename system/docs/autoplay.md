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

## Playbooks: from boot to gameplay

A playbook is a module with `matches(ad, g)`, `setup(ad) -> [failed ops]` and `play(ad, send, stopped, **kw) -> stats`,
listed in `tools.PLAYBOOKS`. A bot demo boots the game, so a playbook has to get itself from boot to gameplay and back
into gameplay after each round. Each one does it this way:

| | from boot | back into gameplay | when it can't tell |
|---|---|---|---|
| RE4 GameCube (re4_merc_bot + re4_menus) | `matches()` true for the disc in any state; `play()` reads the screen and its cursor from RAM (`re4_menus.screen`: the title task's work area) and presses only `re4_menus.step()`: START on the title, THE MERCENARIES, GAME START, Leon, the Village | results: A; "You Are Dead": Continue Yes; then the same menus | saves the menu moment (a jump state at Select Player, before the hooks); RAM silent for 30 s, or a story game: the run ends, a demo is relaunched into it |
| DOA2 LE Dreamcast (doa2_bot) | `matches()` by game id; RAM's demo flag (0x8C200848) tells title from fight; a timed menu `ROUTE` (Start, Start, right, B...) | the jump state saved in a fight | two jumps that land nowhere drop it; still RAM: Start / B once, then a hang |
| GoldenEye PC port (ge007_bots) | the port boots straight into a bot match (`GE_STARTMP`); the bridge says `in_match` | `menus=True`: Start pulses between matches; the harness starts the next one | the bridge never opened: no playbook |

The rules a new playbook follows:

- `matches()` is true from boot (the disc or game id), not only in gameplay. Otherwise a demo that boots to its title
  gets no playbook.
- Get to gameplay from RAM: name the screen and the cursor, and press only what moves that screen towards gameplay. A
  blind press can pick New Game or Load. On RE4, blind up + A started a story game with the Mercenaries hooks in, and
  Dolphin crashed (2026-10-20).
- Save a menu moment or jump state where the game can be restored cleanly, before any code hooks: a Dolphin state
  saved after RE4's hooks restores into a hang. `jumpstate.save` uses gBox's demo slot, never the operator's.
- Fill the stats dict as you go (the watch panel reads it): `screen`, `cursor`, `menu_presses`, and `ram_progress`,
  which counts up when RAM shows the game moving. The black watch trusts it.
- Off the path for good (a story game, menus RAM can't name)? Return with `stats["hung"] = True` and a reason. A bot
  demo is then relaunched, into its menu moment.
- Name only the keyword arguments you need: `tools._start_playbook` passes `stats`, `prompt`, `ram_prompt`, `style` and
  `game` (the session's game dict, for jump states) to a `play()` that names them.
