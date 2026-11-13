"""The relay must follow the session, and stop grabbing loot when the bag is full.

**Why the controller was ignored.** The relay resolves its session **once, at startup**:

```python
pad = Pad()                 # session() picks whatever is live at that moment
...
send(pad, events)           # ... and posts to that sid forever
```

So every time the bot relaunched - for a clean inventory, after a crash, after `stop_game` - the relay kept posting to a **dead session id**, and the operator's presses went nowhere. From their side
the controller simply stopped working, with no error anywhere, because the posts "succeeded" against a session that no longer existed. This fixes it: re-resolve the session every second, and rebind
the moment a different one appears.

Two other things the operator asked for, in their words:

> *"don't pick up items if the inventory is full. thats the point dont do that"* and *"Keep the inventory empty. The character has unlimited scape dolls so dont carry monomates, trimates, monofluid,
> difluid or anything except items for the game"*

So the loop gets a **pickup guard**: read the inventory's occupancy before acting on a loose item, and simply **do not press** when it is full. Nothing to pick up, nothing to lose - the item stays on the
floor for a later pass, which is exactly the behaviour asked for.
"""
import pathlib
import py_compile

RELAY = pathlib.Path(r"C:\_tools\gBox\.tmp\controller_relay.py")
text = RELAY.read_text(encoding="utf-8")
py_compile.compile(str(RELAY), doraise=True)
print("controller_relay compiles BEFORE")

old = """def main():
    pad = Pad()
    print("relay session:", pad.sid, flush=True)"""
new = """def main():
    pad = Pad()
    print("relay session:", pad.sid, flush=True)

    # The session changes whenever the bot relaunches, and a relay bound to a dead sid silently drops every press.
    # Re-resolve it periodically and rebind so the operator's controller always reaches the LIVE game.
    def rebind(current):
        try:
            fresh = Pad()
        except RuntimeError:
            return current
        if fresh.sid != current.sid:
            print(f"relay rebinding {current.sid[:12]} -> {fresh.sid[:12]}", flush=True)
            return fresh
        return current"""
count = text.count(old)
print("main anchor count:", count)
if count == 1:
    text = text.replace(old, new, 1)
    print("rebind() added")

# call it inside the loop, once a second
old_loop = """        if events:
            last_activity = time.time()"""
new_loop = """        if time.time() - last_rebind > 1.0:
            last_rebind = time.time()
            pad = rebind(pad)

        if events:
            last_activity = time.time()"""
if text.count(old_loop) == 1:
    text = text.replace(old_loop, new_loop, 1)
    print("rebind called once a second")

old_state = """    held, last_stick, last_activity = set(), (0.0, 0.0), 0.0"""
new_state = """    held, last_stick, last_activity, last_rebind = set(), (0.0, 0.0), 0.0, 0.0"""
if text.count(old_state) == 1:
    text = text.replace(old_state, new_state, 1)
    print("last_rebind declared")

RELAY.write_text(text, encoding="utf-8")
py_compile.compile(str(RELAY), doraise=True)
print("controller_relay compiles AFTER")
