"""Clear the room before leaving it: interaction yields to enemies that are actually engaged.

The operator: *"The bot needs to walk out the room, but first he needs to dispatch these enemies and then walk out of the
room."*

Interaction-first was added because boxes were consuming every iteration and switches went untouched. But it went too
far the other way: it now outranks enemies, so the bot walks past a live Booma to reach a switch. The rule is **clear the
room, then leave it.**

So the interact block is gated on there being **no engaged enemy** - one within `ENGAGE_RANGE = 40` units, which is
comfortably beyond the real attack reach of 13-30 and so covers anything the character is fighting or about to fight. When
an enemy is that close, the block does not run and the enemy branch handles it as before; once the room is clear, the
switch or teleporter becomes the highest priority again.

That keeps both behaviours the operator asked for, in the order they asked for them.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

OLD = '        interact = []\n'
NEW = (
    '        # CLEAR THE ROOM FIRST. Interaction outranks boxes, but not enemies: the operator asked for the bot to\n'
    '        # "dispatch these enemies and then walk out of the room". Anything within 40 units - well beyond the real\n'
    '        # 13-30 attack reach - counts as engaged, so the enemy branch keeps the turn until the room is clear.\n'
    '        engaged = [e for e in enemies\n'
    '                   if math.hypot(float(e.get("x") or 0) - x, float(e.get("z") or 0) - z) <= 40.0]\n'
    '        interact = []\n'
)
count = text.count(OLD)
print("interact init anchor count:", count)
if count != 1:
    raise SystemExit("interact initialisation not unique")
text = text.replace(OLD, NEW, 1)

OLD2 = '        if interact:\n            interact.sort(key=lambda t: (t[0], t[1]))'
NEW2 = '        if interact and not engaged:\n            interact.sort(key=lambda t: (t[0], t[1]))'
count2 = text.count(OLD2)
print("interact gate anchor count:", count2)
if count2 != 1:
    raise SystemExit("interact gate not unique")
text = text.replace(OLD2, NEW2, 1)
print("interaction now yields to engaged enemies")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
