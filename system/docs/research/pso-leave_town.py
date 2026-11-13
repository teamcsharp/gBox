"""Never stay in town: if the character is in Pioneer 2, warp to a field at once.

The operator cleared the stage and the character came back to the city - **room 20, 20 NPCs, city doors, no enemies, no
gates**. The bot then spent its window walking at doors and boxes that are not in a level at all, and one walk went
**backwards by 522 units** (`walking to TObjDoor (door) 60 -> 582 units`).

The loop already warps to a field when it *starts* in town (`in the city (… entities) - warping to a field`), but nothing
handles **arriving** in town mid-run, which is exactly what clearing a stage does.

So the rule becomes continuous, at the top of the frame:

* **town** = no gates, no enemies, and NPCs present (the city's signature - measured: 20 NPCs, 0 gates, 0 enemies);
* when in town, `go_to_field(pad)` immediately and `continue`, so no other branch gets a turn in a place with nothing to
  do.

That is the behaviour the operator asked for in the plainest terms: *the bot must always be progressing, always
exploring*. Pioneer 2 is not a level; it is a doorway back to one.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

OLD = '''        # The operator types notes into operator-notes.txt; they are read and acted on every iteration.
        read_notes(pad)'''
NEW = '''        # NEVER STAY IN TOWN. Clearing a stage returns the character to Pioneer 2, where there is nothing to fight and
        # nothing to open - the signature is NPCs with no gates and no enemies (measured: room 20, 20 NPCs, 0 gates, 0
        # enemies). The loop only handled starting in town; arriving in it mid-run left the bot walking at doors that
        # are not part of a level, once moving 522 units the wrong way. So warp straight back out.
        _town_state = now if isinstance(globals().get("now"), dict) else state(pad)
        _town_ents = _town_state.get("entities") or []
        _town_npc = sum(1 for e in _town_ents if str(e.get("kind")) == "npc")
        _town_gates = sum(1 for e in _town_ents if str(e.get("kind")) == "gate")
        _town_enemies = sum(1 for e in _town_ents if str(e.get("kind")) == "enemy"
                            and float(e.get("hp") or 0) > 0)
        if _town_npc and not _town_gates and not _town_enemies:
            log(f"  in town ({_town_npc} NPCs, no gates, no enemies) - warping back to a field")
            go_to_field(pad)
            continue

        # The operator types notes into operator-notes.txt; they are read and acted on every iteration.
        read_notes(pad)'''
count = text.count(OLD)
print("read_notes anchor count:", count)
if count != 1:
    raise SystemExit("read_notes anchor not unique")
text = text.replace(OLD, NEW, 1)
print("town detection and immediate warp installed")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
