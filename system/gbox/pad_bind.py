"""gbox.pso_padbind: which XInput slot Dolphin should read.

`DolphinWinAdapter._setup_vpad` puts Player 1 on a virtual pad and writes `Device = XInput/<slot>/Gamepad`. When that
pad cannot be created it returns None and the caller writes the base keyboard INI, which still says `XInput/0/Gamepad`.
On this PC slot 0 is a **phantom virtual pad that reports exactly zero forever** while the operator's real controller is
on another slot, so the fallback binds the game to a dead device: the game ignores every gBox press *and* the operator's
own controller. That is what stopped round 8's cold-boot walk and the Select+L1+R1 chord.

This module is the missing decision, kept pure so it is testable: given the pads that report, which slot should the INI
name? The answer is the slot whose state is not all-zero, i.e. one a person is holding (or one gBox just created), never
a slot that is merely present.
"""
from __future__ import annotations

import re

DEVICE_LINE = re.compile(r"^Device = XInput/(\d)/Gamepad$", re.M)
def alive(state) -> bool:
    """Is this pad state a real device rather than the phantom?

    The discriminator is "exactly zero in every field": gBox's leftover virtual pad on this PC reports all zeros
    forever, while a physical controller's sticks drift by tens to thousands of counts even when untouched (measured
    on the operator's pad: ``lx -160, ly 1387, rx -543, ry 1916``). XInput's deadzone is therefore the wrong test --
    drift is *below* it -- and a button test would miss a player who is not pressing anything at launch.
    """
    if isinstance(state, dict):
        values = (state.get("buttons", 0), state.get("lx", 0), state.get("ly", 0),
                  state.get("rx", 0), state.get("ry", 0), state.get("lt", 0), state.get("rt", 0))
    else:
        values = tuple(state)
    return any(int(v or 0) for v in values)


def live_slots(pads: dict) -> list[int]:
    """The slots that hold a device with any life in it, lowest first."""
    return sorted(s for s, state in pads.items() if alive(state))


def choose_slot(pads: dict, *, created: int | None = None) -> int | None:
    """The slot to bind: gBox's own pad when it exists, else the lowest pad that is not the phantom, else None.

    ``pads`` maps slot -> state for every slot that reports. ``created`` is the slot of the virtual pad gBox made for
    this launch, if any -- that one wins even while idle, because gBox is about to press with it.
    """
    if created is not None and created in pads:
        return created
    live = live_slots(pads)
    return live[0] if live else None


def bind_device(ini: str, slot: int | None) -> str:
    """The INI with GCPad1's device pointed at ``slot`` (unchanged when the slot is None or the line is absent)."""
    if slot is None:
        return ini
    if not DEVICE_LINE.search(ini):
        return ini
    return DEVICE_LINE.sub(f"Device = XInput/{int(slot)}/Gamepad", ini, count=1)


def bind_note(ini: str, slot: int | None, *, created: bool = False) -> str:
    """The INI plus a one-line comment saying why the device was chosen (visible in the file, not just in a log)."""
    if slot is None:
        return ini
    why = ("gBox's virtual pad" if created else "the pad that reports input; slot 0 was idle/dead")
    comment = f"# gBox: Player 1 bound to XInput slot {slot} ({why})\n"
    return comment + bind_device(ini, slot)

def probe_pads() -> dict:
    """{slot: (buttons, lx, ly, rx, ry, lt, rt)} for every XInput slot that reports on this PC now.

    Kept apart from the pure choosers so the decision is testable: this is the only part that touches Windows.
    """
    from . import xinput
    fn = xinput.load()
    if fn is None:
        return {}
    st = [xinput.XInputState() for _ in range(4)]
    out = {}
    for s in range(4):
        if xinput.read(fn, s, st[s]) is None:
            continue
        g = st[s].gamepad
        out[s] = (g.buttons, g.lx, g.ly, g.rx, g.ry, g.lt, g.rt)
    return out