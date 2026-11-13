"""Pick the difficulty the character can actually survive, instead of demanding Ultimate at level 5.

Measured last round: Ultimate Forest beasts carry **1556 HP** while the character has **68**, so Ultimate is not a skill or targeting problem - it is unwinnable at that level, and PSO itself gates
Ultimate behind level 80. The objective still wants the whole game on Ultimate, so the answer is not to abandon it but to **earn it**: level on Normal, where the same enemies are killable (a
verified kill landed there), and switch back when the character can take a hit.

The signal is `hp_max`, which the profile already reports and which grows with level: **68 at level 5**. Ultimate's content is designed for a character with several hundred. So:

* `hp_max < ULTIMATE_AT` -> **Normal (0)**, so the bot can actually kill and gain levels;
* `hp_max >= ULTIMATE_AT` -> **Ultimate (3)**, the objective's requirement, applied as soon as it is survivable.

The choice is logged with the reason every session, so the run says which mode it is in and why. `ULTIMATE_AT = 250` is a deliberately cautious first threshold - roughly level 40-50 - chosen so the
bot does not throw itself back into 1556 HP enemies the moment its HP ticks up a little.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old_start = 'def set_ultimate(pad: Pad) -> str:'
if text.count(old_start) != 1:
    raise SystemExit("set_ultimate anchor count: %d" % text.count(old_start))

# find the whole function body to replace
lines = text.splitlines()
start = next(i for i, line in enumerate(lines) if line.startswith("def set_ultimate("))
# the function ends at the next top-level def/assignment
end = start + 1
while end < len(lines) and not (lines[end].startswith("def ") or lines[end].startswith("STAGE_FLAG")
                                or lines[end].startswith("DIFFICULTY_GLOBAL")):
    end += 1
print(f"replacing lines {start + 1}..{end} ({'set_ultimate'})")

NEW = '''ULTIMATE_AT = 250          # hp_max at which Ultimate becomes survivable (level 5 has 68)


def set_difficulty(pad: Pad) -> str:
    """Choose Normal or Ultimate from the character's own max HP, and verify the write.

    Ultimate content is not survivable at 68 HP - the Forest beasts there carry 1556 - so the bot levels on Normal and
    switches to Ultimate once its HP shows it can take hits. The objective wants Ultimate; this is how it is earned
    rather than pretended.
    """
    import struct as _struct

    profile = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {"player_only": True}}, "POST") or {}
    player = profile.get("player") or {}
    hp_max = float(player.get("hp_max") or 0)
    wanted = 3 if hp_max >= ULTIMATE_AT else 0
    label = "Ultimate" if wanted == 3 else "Normal"

    before = call("/api/sessions/%s/rpc" % pad.sid,
                  {"op": "read_memory", "args": {"address": DIFFICULTY_GLOBAL, "length": 4}}, "POST")
    try:
        current = int.from_bytes(bytes.fromhex(before), "big")
    except Exception:                                          # noqa: BLE001
        current = None
    if current == wanted:
        return f"{label} (already, hp_max {hp_max:.0f})"

    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": DIFFICULTY_GLOBAL,
                                       "hex_bytes": _struct.pack(">I", wanted).hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(8):
        time.sleep(0.3)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            break
    time.sleep(0.2)
    after = call("/api/sessions/%s/rpc" % pad.sid,
                 {"op": "read_memory", "args": {"address": DIFFICULTY_GLOBAL, "length": 4}}, "POST")
    try:
        now = int.from_bytes(bytes.fromhex(after), "big")
    except Exception:                                          # noqa: BLE001
        now = None
    verdict = "ok" if now == wanted else "DID NOT STICK"
    return f"{label} for hp_max {hp_max:.0f} ({current} -> {now}) {verdict}"

'''

lines = lines[:start] + NEW.splitlines() + lines[end:]
text = "\n".join(lines) + "\n"

# call it
old_call = '    log(f"  difficulty: {set_ultimate(pad)}")'
new_call = '    log(f"  difficulty: {set_difficulty(pad)}")'
if text.count(old_call) == 1:
    text = text.replace(old_call, new_call, 1)
    print("arming now calls set_difficulty()")
else:
    print("call anchor count:", text.count(old_call))

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
