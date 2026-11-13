"""A boss arena is a destination, not a failed warp.

`go_to_field()` decides success by entity count alone - `> 60` means "field". But a boss arena has **7** entities (measured: the Dragon's room held 7, including `TBoss1Dragon` and two
`TBoss1DragonColli_C`), so a warp that works perfectly into a boss arena is logged as *"could not reach a field this cycle - playing where we are"* and the loop carries on as if nothing happened.
That is a misleading log at best and a reason to re-warp at worst.

The predicate should recognise what it is standing in:

* a **field** - many entities (the Forest rooms measured 85-91, with `gate` kinds);
* a **boss arena** - few entities but a class containing `Boss`;
* the **city** - ~31 entities, all `npc`/`object`/`player`, no enemies and no gates.

So success means "field or boss arena", and only the city is a failure worth retrying.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

helper = '''
def where_am_i(state_now: dict) -> str:
    """'boss' | 'field' | 'city' - from the entity list alone.

    A boss arena has very few entities (7 in the Dragon's room) while a field has 85-130, so counting is not enough:
    the give-away for a boss is `Boss` in a class name, and for the city it is the absence of gates and enemies.
    """
    entities = state_now.get("entities") or []
    classes = [str(e.get("class")) for e in entities]
    if any("Boss" in name for name in classes):
        return "boss"
    if len(entities) > 60 and any(str(e.get("kind")) == "gate" for e in entities):
        return "field"
    if any(str(e.get("kind")) == "enemy" for e in entities):
        return "field"
    return "city"


'''

anchor = "def go_to_field(pad: Pad) -> bool:"
if text.count(anchor) != 1:
    raise SystemExit("go_to_field anchor count: %d" % text.count(anchor))
if "def where_am_i(" not in text:
    text = text.replace(anchor, helper.lstrip("\n") + anchor, 1)
    print("added where_am_i()")

old_check = """    if len(entities) > 60 and any(str(e.get("kind")) == "gate" for e in entities):
        return True                                     # already in a field"""
new_check = """    if where_am_i(now) in ("field", "boss"):
        return True                                     # a field or a boss arena both count as arrived"""
if text.count(old_check) != 1:
    raise SystemExit("field check anchor count: %d" % text.count(old_check))
text = text.replace(old_check, new_check, 1)

old_wait = """        if count > 60:
            return True
    return False"""
new_wait = """        if where_am_i(after) in ("field", "boss"):
            return True
    return False"""
if text.count(old_wait) != 1:
    raise SystemExit("post-warp anchor count: %d" % text.count(old_wait))
text = text.replace(old_wait, new_wait, 1)

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER - boss arenas count as arrived")
