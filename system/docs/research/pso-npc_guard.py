"""Never talk to anyone: the dialogue box is what has been freezing the bot.

The operator caught it in a screenshot: the character is standing in a **conversation** - *"This is important. Pay attention to everything around you if you want to survive."* - and nothing moves
because **a dialogue box swallows every input until it is dismissed**. That is the "wedged, no direction moved it, retreated 0.0 units" state that has been burning whole windows: **travelled 0 units over
60 seconds** while the relocation teleport correctly reported `landed` four times.

**Why it kept happening:** the sweep presses `b` then `a` - and `A` is the *talk* button. Any `Npc`/`NPC` class inside the sweep radius gets talked to, and the conversation then blocks movement
indefinitely. The reticle catch-all already excluded NPCs, but the **sweep did not**, so every box and enemy fight near an NPC started one.

Two fixes:

1. **`npc_within(entities, x, z, radius)`** - suppress the sweep when an NPC is close, so a conversation is never started. Melee is not worth a frozen window.
2. **`dismiss_dialog(pad)`** - press `B` (cancel) several times, then check whether the position responds. Used by `unstick` when no direction moves the character, because that is the signature of a
   dialog rather than a wall. If the dialogs are chained, further `B` presses advance through them.

`B` cancels rather than `A` because `A` *advances* a conversation and can start the next line; cancel is what gets out.
"""
import time

NPC_MARKERS = ("Npc", "NPC")


def is_npc(entity) -> bool:
    name = str(entity.get("class") or "")
    return any(marker in name for marker in NPC_MARKERS)


def npc_within(entities, x: float, z: float, radius: float = 25.0):
    """The nearest NPC inside `radius`, or None. Used to suppress the sweep so no conversation starts."""
    best = None
    for entity in entities or []:
        if not is_npc(entity):
            continue
        if entity.get("x") is None or entity.get("z") is None:
            continue
        distance = ((float(entity.get("x") or 0) - x) ** 2 + (float(entity.get("z") or 0) - z) ** 2) ** 0.5
        if distance <= radius and (best is None or distance < best[1]):
            best = (entity, distance)
    return best[0] if best else None


def dismiss_dialog(pad, state_fn, hold_fn, tap_fn, attempts: int = 6) -> bool:
    """Press B until the character can move again. True when it got free.

    `B` cancels, which is what exits a dialog; `A` would advance it and can chain into the next line. The test for
    "free" is movement: a dialog blocks everything, so a forward step that produces no displacement means still
    trapped.
    """
    import math

    for _ in range(attempts):
        tap_fn(pad, "b")
        time.sleep(0.25)
        before = state_fn(pad).get("player") or {}
        start = (float(before.get("x") or 0), float(before.get("z") or 0))
        hold_fn(pad, "up", 0.45)
        time.sleep(0.2)
        after = state_fn(pad).get("player") or {}
        end = (float(after.get("x") or 0), float(after.get("z") or 0))
        if math.dist(start, end) > 2.0:
            return True
    return False
