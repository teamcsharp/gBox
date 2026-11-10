"""P1: what PSO's boot screens look like in RAM, the probe that looks for it, and the pad precondition.

Status after round 3: **the boot screens are walked, but RAM does not yet identify them.**

What the round proved live
--------------------------
With a virtual pad bound, real presses walked this session:

    PRESS START -> title main menu -> OFFLINE GAME -> SELECT GAME MODE -> SELECT CHARACTER

and back out with ``B``. Frames confirm each screen; the walk is in the round doc.

``0x80516303`` is **not a screen id.** It is a coarse mode/counter that takes small values and is reused: it read
``1`` at the title main menu *and* ``1`` at SELECT CHARACTER, ``9`` at SELECT GAME MODE, ``22`` after a cancel, and
``0`` at the title. It is still a useful transition signal -- it changes when the screen changes -- but a walk must
never use it to decide *which* screen is up.

What a walk needs instead, and what this module provides
-------------------------------------------------------
A screen signature built from the bytes that actually move between two known screens, and only those:
:func:`stable` + :func:`stable_diff` find them (constancy filtering is what removes animated UI data -- a plain
before/after diff is dominated by it, and ``0x80506274`` looked exactly like a cursor and is a logo counter that
oscillates on its own). :func:`signature` turns a diff's addresses into a comparable vector, and :func:`similarity`
compares two.

A first attempt at a fixed window (``0x80516000``/``0x80516200``/``0x80514500``, 1 KiB) scored **0.99 similarity between
all four screens** -- the windows were almost entirely zero, so they carried no information. The lesson is in the code:
derive the address set from a live diff, do not pick a window by eye.

The precondition that made a walk look dead
-------------------------------------------
The virtual pad is what makes presses land without focus. When a launch binds one, Dolphin's
``User/Config/GCPadNew.ini`` contains ``Options/Always Connected = True`` and ``Device = XInput/<slot>/Gamepad``. When
it does not -- three stale ViGEm pads from earlier sessions were still registered and ``_setup_vpad()`` returns
``None`` silently -- the adapter falls back to the keyboard, ``win_send_keys`` reports ``sent: 0`` while the window is
minimised, and every press is silently dropped. :func:`verify_pad_binding` is the check; run it before any walk.
"""
from __future__ import annotations

import hashlib
import time

# A coarse mode/counter, NOT a screen id (see the module docstring). Kept because its transitions are useful.
MODE_BYTE = 0x80516303
MODE_BYTE_MIRROR = 0x805145F7

# Values observed live, with the screen that was up. The same value appears on different screens: that is the point.
MODES_SEEN = {
    0: ("title",),
    1: ("title main menu", "SELECT CHARACTER"),
    9: ("SELECT GAME MODE",),
    22: ("after a cancel from SELECT GAME MODE",),
}

# The title main menu's items, in the order the screen shows them.
MAIN_MENU_ITEMS = ("ONLINE GAME", "OFFLINE GAME", "OPTIONS", "WEBSITE")

# The offline branch as walked live in round 3.
OFFLINE_PATH = ("PRESS START", "main menu", "OFFLINE GAME", "SELECT GAME MODE", "SELECT CHARACTER")

# Where the adapter writes the pad binding, relative to Dolphin's User folder.
PAD_INI = "Config/GCPadNew.ini"
VPAD_MARKER = "Options/Always Connected = True"


class MenuError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------------ the probe

class Counting:
    """A ``read_memory``-shaped wrapper that counts its calls, so a walk can bound what it costs."""

    def __init__(self, memory):
        self.memory = memory
        self.bytes_read = 0
        self.calls = 0

    def read_memory(self, address, length):
        blob = self.memory.read_memory(address, length)
        self.calls += 1
        self.bytes_read += len(blob or b"")
        return blob


def stable(read, windows, samples: int = 4, gap: float = 0.05, sleep=time.sleep, chunk: int = 1 << 20):
    """(values, constancy) for every byte of ``windows``, keeping only bytes identical in all ``samples`` reads.

    ``windows`` is ``[(base, size), ...]``; ``constancy[i]`` is 1 when byte ``i`` never changed, which is what removes
    animated UI data from the comparison.
    """
    flats = []
    for s in range(samples):
        if s:
            sleep(gap)
        buf = bytearray()
        for base, size in windows:
            off = 0
            while off < size:
                n = min(chunk, size - off)
                blob = read.read_memory(base + off, n)
                if len(blob) != n:
                    raise MenuError(f"short read at {base + off:#x}: {len(blob)} of {n}")
                buf += blob
                off += n
        flats.append(bytes(buf))
    constancy = bytearray(b"\x01") * len(flats[0])
    for flat in flats[1:]:
        if len(flat) != len(constancy):
            raise MenuError("the windows changed size between samples")
        for i in range(len(flat)):
            if constancy[i] and flat[i] != flats[0][i]:
                constancy[i] = 0
    return list(flats[0]), list(constancy)


def stable_diff(a, b, windows) -> list[tuple[int, int, int]]:
    """[(address, value in a, value in b)] for bytes constant in BOTH states and different between them."""
    (va, ca), (vb, cb) = a, b
    out, i = [], 0
    for base, size in windows:
        for k in range(size):
            j = i + k
            if ca[j] and cb[j] and va[j] != vb[j]:
                out.append((base + k, va[j], vb[j]))
        i += size
    return out


def signature(read, addresses, samples: int = 3, gap: float = 0.04, sleep=time.sleep) -> dict:
    """A screen signature over ``addresses`` (a diff's addresses), refusing any byte that is not constant.

    Bytes that vary while the signature is taken are dropped from the vector (and counted), so an animated address
    cannot make two identical screens look different.
    """
    addrs = sorted(set(int(a) for a in addresses))
    rows = []
    for s in range(samples):
        if s:
            sleep(gap)
        rows.append({a: read.read_memory(a, 1)[0] for a in addrs})
    keep = [a for a in addrs if all(r[a] == rows[0][a] for r in rows)]
    vector = bytes(rows[0][a] for a in keep)
    return {"addresses": keep, "vector": vector.hex(), "dropped": len(addrs) - len(keep),
            "sha256": hashlib.sha256(vector).hexdigest(), "count": len(keep)}


def similarity(a: dict, b: dict) -> float:
    """Fraction of bytes that agree over the addresses both signatures kept."""
    common = sorted(set(a["addresses"]) & set(b["addresses"]))
    if not common:
        return 0.0
    va = bytes.fromhex(a["vector"])
    vb = bytes.fromhex(b["vector"])
    ia = {x: va[i] for i, x in enumerate(a["addresses"])}
    ib = {x: vb[i] for i, x in enumerate(b["addresses"])}
    return sum(1 for x in common if ia[x] == ib[x]) / len(common)


def verify_pad_binding(user_dir) -> dict:
    """Does this Dolphin ``User`` folder bind Player 1 to a virtual pad? The precondition for focus-free presses."""
    from pathlib import Path
    p = Path(user_dir) / PAD_INI
    if not p.is_file():
        return {"bound": False, "why": f"{p} is missing"}
    text = p.read_text(errors="replace")
    device = next((line.split("=", 1)[1].strip() for line in text.splitlines()
                   if line.startswith("Device =")), "")
    bound = bool(device.startswith("XInput/") and VPAD_MARKER in text)
    return {"bound": bound, "device": device,
            "why": "" if bound else "Player 1 is on the keyboard: presses need window focus and are dropped when "
                                    "Dolphin is minimised"}
