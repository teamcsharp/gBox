# The fighting engine (gbox/fightbot)

Operator, 2026-10-20: "On the i9, I want to see DOA 3 with character swapping going through survival mode parrying
and using the autobot DOA engine to parry and crush opponents." And for every bot: "the system should be able to know
what screen is up on the game by the very game hook and ram / hex signature ... Vision analysis to me should be the
last level that we have to fall back to."

One engine plays every fighting game gBox autoplays. A **title** is its RAM map (what the game keeps where, in the
engine's vocabulary, with signatures on enum values) plus a small Title module for what RAM can't say (which buttons
answer which attack, the menus). The engine only sees the vocabulary, so a lesson learned on one title (a hold window,
a feint, a punish) is written down in the same terms for every other. The design follows the Mercenaries engine
(docs/mercenaries_engine.md): title profile = RAM map, a shared vocabulary, signatures tagged on enum values, an engine
tick, a lessons log of hits taken with the attacker's state just before them.

| title | game | how it plays now |
|---|---|---|
| `titles/doa2_dc.py` | Dead or Alive 2 LE (Dreamcast, Flycast) | onset reflex on the attack-input edge, learned hold direction, jump states (gbox/doa2_bot.py, a shim) |
| `titles/doa3_xbox.py` | Dead or Alive 3 (Xbox, USA, native runner) | frame-synced engine, virtual pad on port 4, RAM screens (gbox/doa3_bot.py) |
| (planned) SoulCalibur II (GameCube) | | the SC2 agent's attack record (+0x1690), GI timing and move book map onto the same hooks |

## Layout

| file | what |
|---|---|
| `fightbot/vocab.py` | the names (screen, frame, pN.hp / chara / pos / side / state / move / move_class / move_frame / attack / hit / input / warn), the signature tags, `check(map)` |
| `fightbot/world.py` | `World(frame, screen, p1, p2)`, `Fighter`, `Attack`: one frame from one batched `ram_map` read |
| `fightbot/title.py` | `Title` (reading, side, answers, punish, attacks, outcome, menus) and `Answer` (keys or a string of steps, frames, lead, judge) |
| `fightbot/engine.py` | `Engine.tick(world) -> keys`: threat, answer timed in frames, judgement, punish, offense, latency |
| `fightbot/book.py` | the move book: answer -> tries / reward / misses per move and per attack class, start-to-hit frames, feints; JSON per worker |
| `fightbot/runner.py` | `fight(...)`: one tick per game frame until the fight screen ends; `Sender`: only changes, directions before buttons, threaded for slow sends |
| `fightbot/lessons.py` | the run log (JSONL) and `analyze` (untagged moves seen before hits) |
| `fightbot/reflex.py` | `OnsetReflex`: answer an onset edge at once (titles with no frame clock yet) |
| `fightbot/survival.py` | the endless Survival loop: menus (a fixed route or per screen), jump states, safety top-up, nudges, hang detection |

## The title profile

A RAM map (`profiles/gamedata/<id>-ram.json`, `gbox-ram-map/1`, docs/ram_maps.md) with a `fight` block:

```json
"fight": {
  "title": "gbox.fightbot.titles.doa3_xbox",
  "fps": 60,
  "vocab": {"screen": "driver", "frame": "driver", "p1.move": "p1.move", "p2.move_class": "p2.move_class",
            "p1.input": "p1.input", "p1.hp": null}
}
```

A name maps to a field of the map, `null` (unknown: the engine degrades) or `"driver"` (the Title module computes it).
`python -c "from gbox import ram_map; from gbox.fightbot import vocab; print(vocab.check(ram_map.load('<id>')))"`
reports what a title fills.

### Signatures

As in the Mercenaries engine: a `signatures` object beside `enum` on the field that holds the value (value -> tags),
with `source`, `evidence` and `confidence` (`candidate` / `static` / `live`).

| tag | on | values |
|---|---|---|
| `attack` | move / move_class / attack record | `strike`, `throw`, `hold`, `special` |
| `phase` | " | `startup`, `active`, `recovery` |
| `height` | " / attack height bits | `high`, `mid`, `low` |
| `limb` | " | `punch`, `kick` |
| `active` | " | `[first, last]` active frames, move-relative |
| `lead_f` | " | frames from this value's onset to the first active frame |
| `unblockable` | " | `true` |
| `state` | state / move_class | `neutral`, `guard`, `crouch`, `air`, `hitstun`, `stagger`, `down`, `held`, `holding`, `throwing`, `thrown`, `ko`, `can_act`, `attacking`, `recovery` |
| `hit` | hit result | `landed`, `guarded`, `parried`, `held`, `whiffed` |
| `screen` | the screen field | `title`, `demo`, `menu`, `char_select`, `loading`, `intro`, `fight`, `round_end`, `continue`, `game_over`, `results`, `paused` |

## The tick

```
runner.fight:                                   # every game frame (the frame field moved)
  world = title.read(mem)                       # one batched read
  if world.screen not in (intro, fight, round_end): return world.screen
  keys = engine.tick(world):
      hits      P1 lost health -> hit_taken (attacker's move / class / frame / tags, frames into its move) + book
      threat    P2's move or class carries an attack signature (or an attack record, or a warn edge) -> onset frame,
                frames to its first active frame (start - frame, else lead_f - since, else the book's start-to-hit
                median for that move, else the title's default)
      judge     a pending answer whose window shows an outcome (health moved, a parry) -> book + lessons; paid ->
                the title's punish
      latency   the first frame P1's own input word shows the answer's bits: input frames (from the press) and
                reaction frames (from the attack's onset)
      answer    the title's answers, the book's pick (per move, else per class; feints skipped), pressed lead + lag
                frames before the first active frame, held `frames`
      offense   nothing to answer: the title's attacks, at most every attack_gap frames, learned by damage dealt
  sender.hold(keys)                             # only the changes
```

Latency figures (watch panel, lessons): `lat_input_f` (median frames from sending to the game showing the keys) and
`lat_reaction_f` (median frames from an attack's onset to the game showing the answer). `frames_skipped` counts game
frames the loop never saw.

### What a title can ask of an answer (the SC2 fit check)

| `Answer` field / hook | what it does |
|---|---|
| `seq=((keys, frames), ...)` | a string instead of one chord (P, P, K); `title.lag_f` (the measured input lag) lets a title size a release step (SC2's fresh G press) |
| `confirm_f`, `fallback`, `Title.confirm(answer, w)` | the answer must show (P1's move) within confirm_f frames, else the fallback is pressed at once (SC2: no Guard Impact move -> guard) |
| `hold_off=("b",)` | those keys stay up while P1's own attack is out (SC2: G cancels attack startup) |
| `Fighter.next_attack` | a queued follow-up the title resolved (SC2 strings: +0x52 / +0x60), for answers() to see |
| `Title.long_window` | an attack active longer than this is timed on the book's contact median for that move, not its first active frame |
| `Title.warn_settle` | after a warn edge, wait this many frames for the move it starts, so the book learns per move |
| `Title.outcome` -> met None | the title can't measure (no health mapped): the try counts, never as a whiff, so no false feints |

### Menus as map data

`fight.menus` maps a screen to rules tried in order: `{"press": key}`, `{"wait": true}`, or a cursor walk
`{"cursor": field, "target": n, "next": key, "prev": key, "confirm": key}`, each optionally guarded by `"when"` (a
ram_map condition over the map's fields). A deployed map change retunes the menus without touching code.

### Evidence

The DOA3 deployment saves the game's own frame shortly after a hold that paid (on its own thread, off the fight
loop) to `runtime/fightbot/<map id>/frames/<run>-f<frame>-<answer>-<outcome>.png`, logged as an `evidence` lesson:
real frames for review, never input to a decision.

## Lessons

`gbox.fightbot.lessons.Run(root, map_id)` writes `<root>/<map id>/runs/<run>.jsonl` (`root` = the worker's
`runtime/fightbot`): `run`, `attack`, `answer` / `punish` / `attack` judgements (answer, reward, outcome, sent, seen,
input and reaction frames), `hit_taken`. `python -m gbox.fightbot.lessons analyze <root> <map id>` lists attacker moves
seen just before hits that have no signature yet, with their frames into the move: candidates to check and add to the
map with their evidence.

## Title: Dead or Alive 3 (Xbox, USA), b8edf7040116f3aa

* **Reads:** the adapter's verified channel (`doa3_memory.Channel`): GuestMemory's full proof once (owned PID and
  birth, pinned runner and XBE hashes, the unique verified allocation), then one ReadProcessMemory a read; the anchors
  are re-checked every 2 s and the full proof every 30 s; a failed check closes it.
* **Presses:** gBox's virtual pad on the game's 4th port (`doa3_pad`): the game polls XInputGetState for every port
  with a handle; the runner answers only handles it issued, so a gBox handle in port 4's slot (0x5E5EC8) and the
  buttons in its state buffer (0x5E5E69) are read like a real pad, from the next poll. No window focus, no driver,
  the player's pad (port 1) untouched; the channel can write only those 26 bytes.
* **Frames:** the main loop's ring index (0x85B9C4) advances after the game tasks ran; the performance counter at
  the loop's start (0x85B988) covers frames the poll missed.
* **Fighters:** the 0x68-byte player blocks at 0x484C48: the move (+0x2E), its class from the move table (+0x33),
  the fighter slot (+0x03), the character index (+0x66); the per-player input word in game bits at 0x479CD4.
* **Buttons:** X = Free, Y = Punch, B = Kick, A = Throw (gBox names y, x, a, b); holds = direction + Free (high:
  up-back, mid: back, low: down-back; the mid-kick forward hold is tried too): the book learns which pays.

Live findings (screens, health, attack phases) are added to the map with their evidence as they are confirmed.
