"""The fighting engine (docs/fighting_engine.md): one engine for every fighting game gBox autoplays.

A title is its RAM map (profiles/gamedata/<id>-ram.json, gbox-ram-map/1) with a `fight` block that names the map's
fields in the engine's vocabulary (vocab.py) and tags enum values with signatures (an attack's phase, height, limb,
active frames; a defender's state), plus a Title module (titles/) for what RAM can't say: which buttons answer which
attack, the menus. The engine only sees the vocabulary, so what it learns on one title is written in the same terms
for every other.

    vocab.py     names, units, signature tags; check(map) says what a title fills
    world.py     World / Fighter / Attack: one frame of the game, from one batched RAM read
    book.py      what each answer earned against each attack (per move, per attack class), persisted per title
    engine.py    Engine.tick(world) -> keys: threat -> answer (hold / parry / guard) timed in frames -> punish
    runner.py    the frame-synced fight loop (one tick per game frame, reaction latency in frames) and the Sender
    lessons.py   the run log: hits taken with the attacker's state just before, answers and their outcomes
    reflex.py    the onset reflex for titles without a frame clock (DOA2 LE: the attack-input edge)
    survival.py  the endless Survival loop (menus or jump states, safety, hang detection) every title shares
    title.py     the Title base class
    titles/      doa2_dc (Dead or Alive 2 LE, Dreamcast), doa3_xbox (Dead or Alive 3, Xbox native runner)
"""
