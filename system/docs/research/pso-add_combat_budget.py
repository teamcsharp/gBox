"""If an enemy cannot be hurt, go through the door instead of standing there forever.

The gate objective never ran in the last windows despite fields carrying 19-24 gates, and the reason is the branch order:

```python
if enemies:
    ... attack ...
else:
    ... walk to the nearest gate ...
```

A room with enemies therefore always takes the attack branch. When the attack lands - two kills are verified - that is correct. When it does not, which is what kept happening (Beasts at 60 HP
across 26 samples), the bot **never reaches the gate code at all** and the room becomes a trap.

So combat gets a **budget**: if the target's HP has not changed after `GIVE_UP_AFTER` consecutive swings, this room is not winnable right now and the bot moves on to a gate. It keeps looking -
an enemy that dies still counts - but it will not stand in front of something invulnerable while the way out is behind it.

That is also how a human plays: fight what you can kill, walk past what you cannot.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# 1. the budget constant next to the other module constants
if "GIVE_UP_AFTER" not in text:
    text = text.replace('ARMED_SESSIONS: set = set()      # armed once per session: re-giving fills the inventory',
                        'ARMED_SESSIONS: set = set()      # armed once per session: re-giving fills the inventory\n'
                        'GIVE_UP_AFTER = 8                # swings with no HP change before leaving the enemy and taking a gate', 1)
    print("GIVE_UP_AFTER declared")

# 2. track unproductive swings per target
old_hp = """            if name in last_enemy_hp and hp < last_enemy_hp[name]:
                log(f"  {name} HIT: {last_enemy_hp[name]:.0f} -> {hp:.0f}")
            last_enemy_hp[name] = hp"""
new_hp = """            if name in last_enemy_hp and hp < last_enemy_hp[name]:
                log(f"  {name} HIT: {last_enemy_hp[name]:.0f} -> {hp:.0f}")
                unproductive = 0
            elif name in last_enemy_hp:
                unproductive += 1
            last_enemy_hp[name] = hp
            if unproductive >= GIVE_UP_AFTER:
                # cannot hurt this one: leave it and take the way out rather than standing in front of it
                log(f"  {name} untouched after {unproductive} swings - leaving it and heading for a gate")
                unproductive = 0
                last_enemy_hp = {}
                tap(pad, "down")
                time.sleep(0.15)
                hold(pad, "down", 0.6)
                walked_out += 1
                time.sleep(0.1)
                continue"""
if text.count(old_hp) != 1:
    raise SystemExit("hp anchor count: %d" % text.count(old_hp))
text = text.replace(old_hp, new_hp, 1)

# 3. counters
old_counters = "    gates_seen, crossed = set(), []"
new_counters = "    gates_seen, crossed = set(), []\n    unproductive, walked_out = 0, 0"
if text.count(old_counters) == 1:
    text = text.replace(old_counters, new_counters, 1)
    print("counters added")

# 4. report it
old_return = '            f"gates approached {len(gates_seen)}, crossed {len(crossed)}")'
new_return = '            f"gates approached {len(gates_seen)}, crossed {len(crossed)}, left {walked_out} unwinnable")'
if text.count(old_return) == 1:
    text = text.replace(old_return, new_return, 1)
    print("return reports unwinnable skips")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
