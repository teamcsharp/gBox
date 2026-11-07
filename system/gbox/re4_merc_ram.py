"""Mercenaries state read out of RAM, using the layouts from the G4BE08 decompilation.

`adonis-singh/re4` documents both structures with offsets, and both matter:

```
MercResultInfo (MercSysWk + 0x00)      MercSysWork (0xCC bytes)
  score      0x00  final score           score       0x24      combo       0x28   comboTimer 0x2C
  time       0x04  1/100 s remaining     killCnt     0x34      kill        0x38   bonusKill  0x3C
  maxCombo   0x08                        maxCombo    0x40      bonusScore  0x44   addTime    0x4C
  kill       0x0C                        bonusTimer  0x50      mode        0x58   stage      0x5C
  mode       0x10                        flags       0x60      ClearScore  0x78
  rank       0x14  0..5 = N,D,C,B,A,S
  hiScore    0x18  hiMode 0x1C  newRecord 0x20
```

`rank` is the part this system has been guessing from screenshots. It is a small integer the game itself keeps, so a
round report can carry it as RAM evidence rather than a reading of the results screen.

Addresses differ between builds - the live GameCube anchors in `re4_editions.py` are not the static ones in the symbol
map - so this reads through a **base** the caller supplies, and `find_base` checks a candidate list against the structure
rather than trusting any single address.
"""
import struct

RANKS = ("N", "D", "C", "B", "A", "S")
CHARACTERS = ("Leon", "Ada", "Krauser", "HUNK", "Wesker")
STAGES = ("Village", "Castle", "Base", "Waterworld")

RESULT = {"score": (0x00, "u32"), "time": (0x04, "u32"), "max_combo": (0x08, "i32"), "kill": (0x0C, "i32"),
          "mode": (0x10, "i32"), "rank": (0x14, "i32"), "hi_score": (0x18, "u32"), "hi_mode": (0x1C, "i32"),
          "new_record": (0x20, "i32")}
WORK = {"score": (0x24, "u32"), "combo": (0x28, "i32"), "combo_timer": (0x2C, "i32"), "kill_cnt": (0x34, "i32"),
        "kill": (0x38, "i32"), "bonus_kill": (0x3C, "i32"), "max_combo": (0x40, "i32"),
        "bonus_score": (0x44, "i32"), "bonus_display": (0x48, "i32"), "add_time": (0x4C, "i32"),
        "bonus_timer": (0x50, "i32"), "mode": (0x58, "i32"), "stage": (0x5C, "i32"), "flags": (0x60, "u32"),
        "clear_score": (0x78, "u32")}
_FMT = {"u32": "<I", "i32": "<i"}


def rank_name(index) -> str | None:
    """`0..5` as `N,D,C,B,A,S`; None when the value is not a rank the game can hold."""
    try:
        value = int(index)
    except (TypeError, ValueError):
        return None
    return RANKS[value] if 0 <= value < len(RANKS) else None


def _read(mem, address: int, kind: str) -> int:
    raw = mem.rd(address, 4)
    return struct.unpack(_FMT[kind], bytes(raw))[0]


def _block(mem, base: int, table: dict) -> dict:
    return {name: _read(mem, base + offset, kind) for name, (offset, kind) in table.items()}


def result_info(mem, base: int) -> dict:
    """The results block at `base` (MercSysWork + 0x00): score, time, combo, kills, character, **rank**, best score."""
    out = _block(mem, base, RESULT)
    out["rank_name"] = rank_name(out.get("rank"))
    out["character"] = CHARACTERS[out["mode"]] if 0 <= out.get("mode", -1) < len(CHARACTERS) else None
    return out


def work_state(mem, base: int) -> dict:
    """The live work area (MercSysWork + 0x00): the same block plus the combo timer and the stage."""
    out = _block(mem, base, WORK)
    out["character"] = CHARACTERS[out["mode"]] if 0 <= out.get("mode", -1) < len(CHARACTERS) else None
    out["stage_name"] = STAGES[out["stage"]] if 0 <= out.get("stage", -1) < len(STAGES) else None
    return out


def plausible(mem, base: int) -> bool:
    """Does `base` look like the Mercenaries work block? A rank in range and a score that is one.

    Used to test candidate addresses instead of assuming one: a wrong base almost never produces a rank of 0..5 together
    with a sane score, a combo count and a character index.
    """
    try:
        block = result_info(mem, base)
        state = work_state(mem, base)
    except (ValueError, OSError, struct.error):
        return False
    # the resolved NAME, not the raw value: a rank of 9 is a number and not a rank (measured by the test that failed here)
    return (block["rank_name"] is not None and 0 <= block["mode"] < len(CHARACTERS)
            and 0 <= state["stage"] < len(STAGES) and 0 <= block["score"] <= 99_999_999
            and 0 <= state["combo"] <= 9999 and 0 <= state["max_combo"] <= 9999)


def find_base(mem, candidates) -> dict:
    """The first candidate that reads as a Mercenaries work block, with the block itself."""
    tried = []
    for base in candidates:
        tried.append(base)
        if plausible(mem, int(base)):
            return {"base": int(base), "found": True, "tried": tried, "result": result_info(mem, int(base)),
                    "work": work_state(mem, int(base))}
    return {"base": None, "found": False, "tried": tried, "result": None, "work": None}
