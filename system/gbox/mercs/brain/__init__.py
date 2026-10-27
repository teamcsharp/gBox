"""The universal Mercenaries combat brain (operator 2026-10-27: "i want a universal mercenaries engine" and "the goal is
that the aimbot learns enemy activity and builds a database of how to dispatch them and the aimbot improves based on
the ram byte information to keep the bot aware of enemies and where and how to aim to dispatch them").

One title-agnostic core for aim, targeting, ballistics, threat and fire, grown out of the RE5 PS3 combat layer
(gbox/mercs/titles/re5_combat.py, the bot trained over the most rounds). Every title is an adapter: it reads its own RAM
into the normalized snapshot (snapshot.py), runs the brain, and maps the brain's abstract actions (actions.py) to its
own controls. RE5 PS3 and RE5 Switch first, then RE6 Switch, then RE4 GameCube.

    body.py       the target's anatomy (head sphere, body capsule, thighs) and the laser ray's geometry: where a dot
                  sits on a body, the ray's yaw / pitch error to a point, whether a ray runs to him, which rays may steer
    knowledge.py  the hook to the enemy knowledge database: dispatch_plan(title, enemy_class, state, distance, weapon)
                  -> where to aim on him, the range band, the fire mode, the danger; record(outcome) per shot and per
                  damage event. A default provider answers with today's constants until the database registers its own
    snapshot.py   the normalized snapshot every adapter builds, and the enemy tracker (velocities by id)
    actions.py    the abstract actions the brain emits and the control maps that turn them into each title's buttons

The modules here are bot modules (gbox.hot_reload: everything under gbox.mercs reloads in place); knowledge.py keeps its
registered provider across a reload (RELOAD_KEEP).
"""
