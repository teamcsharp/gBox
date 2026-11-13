"""After the switch, walk to the door it opened.

Pressing a switch is only half the job: the level wants the character **through** the door. Once the switch is on its
cooldown, the interact list has nothing left to offer - doors were never in it - so the loop fell through to the box
branch and the newly unlocked passage was ignored.

So doors join the priority with rank 2, below a level exit (0) and a switch (1), and above boxes:

```
0  Warp*                                                        level exit
1  TObjDoorKey / TLazerFenceSw / TOKeyGenericSw                 the switch that opens the way
2  TObjDoor / TObjLazerFenceNorm / TOBarrierEnergy01            the way through
```

Order therefore matches how a floor is actually cleared: find the switch, press it, walk through the door it unlocked,
find the teleporter. Doors get the same treatment as switches - walk within reach, then press `A` to open, then move on -
and they are not put on the switch cooldown because a door legitimately needs opening every time it is passed.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

OLD = '''            elif candidate_class in ("TObjDoorKey", "TLazerFenceSw", "TOKeyGenericSw"):
                rank = 1                                  # the switch that opens the way on
            else:
                continue'''
NEW = '''            elif candidate_class in ("TObjDoorKey", "TLazerFenceSw", "TOKeyGenericSw"):
                rank = 1                                  # the switch that opens the way on
            elif candidate_class in ("TObjDoor", "TObjLazerFenceNorm", "TOBarrierEnergy01"):
                rank = 2                                  # the way through, once a switch has opened it
            else:
                continue'''
count = text.count(OLD)
print("rank anchor count:", count)
if count != 1:
    raise SystemExit("rank assignment not unique")
text = text.replace(OLD, NEW, 1)
print("doors added at rank 2")

# the label should say what it is
OLD2 = '''            kind = "level exit" if rank == 0 else "switch"'''
NEW2 = '''            kind = "level exit" if rank == 0 else ("switch" if rank == 1 else "door")'''
count2 = text.count(OLD2)
print("label anchor count:", count2)
if count2 == 1:
    text = text.replace(OLD2, NEW2, 1)
    print("door label added")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
