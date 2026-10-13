"""Metal Gear Solid: The Twin Snakes (GC) in a running Dolphin session: which cast models the current stage has
loaded, and a body swap written straight into the loaded copies (the `twin_snakes_live` session tool, used by
`characters op=live_use` / the pick whip through gbox.twin_snakes_swap).

How the game holds a stage in RAM (mgso.rel, docs/twin_snakes.md "In RAM"): each page of a stage is inflated into one
buffer and every file is used in place. A `.kms` model is relocated by the loader (0x806b6be8): its header +0x5c
becomes `address + G`, the array offsets +0x4c..+0x58 become absolute, the mesh / part / strip offsets too, and each
part's three texture strcodes become pointers to the texture entries of the loaded `.tri` sets. The model object
(0x806a7860) caches per mesh the record pointer, part count and per part the flags and texture objects, and the draw
loop (0x806a2a6c) reads the parts, strips, index streams and arrays from the model every frame. So a new body written
over a loaded model shows on the next frame as long as: the mesh-group header and mesh records stay where they are,
no mesh gets more parts than it had, every pointer is absolute (gbox.twin_snakes_swap.relocate), and the bytes fit
the loaded copy. Texture texels are written into the loaded `.tri` set in place (same image, size and format).

Scan: MEM1 (24 MiB) is read in 1 MiB chunks with the emulation paused (Dolphin's GDB stub).
"""
from __future__ import annotations

import base64
import struct

from pydantic import BaseModel

from .models import Permission as P
from .registry import tool

CHUNK = 1 << 20
MEM1 = (0x80000000, 0x81800000)
TPL_MAGIC = 0x0020AF30


def _ram(ad, lo: int | None = None, hi: int | None = None) -> bytes:
    lo, hi = MEM1[0] if lo is None else lo, MEM1[1] if hi is None else hi
    out = bytearray()
    for a in range(lo, hi, CHUNK):
        try:
            out += ad.read_memory(a, min(CHUNK, hi - a))
        except Exception:                                  # noqa: BLE001 - an unreadable chunk reads as zeros
            out += bytes(min(CHUNK, hi - a))
    return bytes(out)


def find_sets(ram: bytes, base: int | None = None, hashes: set[int] | None = None) -> list[dict]:
    """Loaded `.tri` texture sets: a TPL (magic 0x0020AF30, n images) whose header sits `tpl` bytes into a set with n
    entries (+0x10 = n, +0x18 = tpl). -> [{address, hash (the set is named by its textures: first entry strcode),
    textures: [strcodes]}]."""
    base = MEM1[0] if base is None else base
    out = []
    i = ram.find(struct.pack(">I", TPL_MAGIC))
    while i >= 0:
        n = struct.unpack_from(">I", ram, i + 4)[0] if i + 8 <= len(ram) else 0
        if 0 < n < 512:
            for tpl in range(0x20 + 0x80 * n, 0x20 + 0x80 * n + 0x400, 0x20):
                a = i - tpl
                if a >= 0 and struct.unpack_from(">I", ram, a + 0x10)[0] == n and \
                        struct.unpack_from(">I", ram, a + 0x18)[0] == tpl:
                    tex = [struct.unpack_from(">I", ram, a + 0x20 + 0x80 * k + 0x10)[0] & 0xFFFFFF for k in range(n)]
                    if hashes is None or set(tex) & hashes:
                        out.append({"address": base + a, "tpl": tpl, "textures": tex})
                    break
        i = ram.find(struct.pack(">I", TPL_MAGIC), i + 4)
    return out


def loaded(ad) -> dict:
    """The cast models the running stage holds (gbox.twin_snakes_swap.find_loaded over a paused MEM1 read)."""
    from . import twin_snakes_swap as W
    state = (ad.query_runtime() or {}).get("state") if hasattr(ad, "query_runtime") else None
    paused = False
    if state != "PAUSED" and hasattr(ad, "pause"):
        ad.pause()
        paused = True
    try:
        ram = _ram(ad)
    finally:
        if paused and hasattr(ad, "resume"):
            ad.resume()
    models = W.find_loaded(ram, MEM1[0])
    cast = sorted({W.main_key(m["key"]) for m in models} - {None})
    return {"models": [{**m, "address": hex(m["address"]), "hash": f"{m['hash']:06x}"} for m in models], "cast": cast}


def apply(ad, items: list[dict]) -> dict:
    """items: [{kind: model, hash, data (base64 .kms, file offsets)} | {kind: texels, textures: [strcode...],
    offset (in the set file), data (base64)} | {kind: hide, hash}]. Every target is located again in RAM, checked,
    written while paused and read back; on any failure everything written so far is restored."""
    from . import twin_snakes_swap as W
    state = (ad.query_runtime() or {}).get("state") if hasattr(ad, "query_runtime") else None
    if state != "PAUSED" and hasattr(ad, "pause"):
        ad.pause()
        resume = True
    else:
        resume = False
    undo: list[tuple[int, bytes]] = []
    done = []
    try:
        ram = _ram(ad)
        want = {int(it["hash"], 16) if isinstance(it["hash"], str) else int(it["hash"])
                for it in items if it.get("kind") in ("model", "hide")}
        models: dict[int, list] = {}
        for m in W.find_loaded(ram, MEM1[0], hashes=want or None):
            models.setdefault(m["hash"], []).append(m)
        for it in items:
            kind = it.get("kind")
            if kind in ("model", "hide"):
                h = int(it["hash"], 16) if isinstance(it["hash"], str) else int(it["hash"])
                copies = models.get(h) or []
                if not copies and kind == "model" and it.get("required", True):
                    raise ValueError(f"model {h:06x} is not loaded in this stage")
                for m in copies:
                    a = m["address"]
                    if kind == "hide":
                        g = struct.unpack_from(">I", ram, a - MEM1[0] + 0x5C)[0]
                        nmesh, _np, _sub, recs = struct.unpack_from(">HHII", ram, g - MEM1[0] + 8)
                        for i in range(nmesh):
                            ra = recs + 0x48 * i + 0x38
                            old = bytes(ad.read_memory(ra, 2))
                            undo.append((ra, old))
                            ad.write_memory(ra, b"\0\0")
                        done.append({"hide": f"{h:06x}", "address": hex(a)})
                        continue
                    new = base64.b64decode(it["data"])
                    size = int(it.get("size") or 0)
                    if len(new) > size:
                        raise ValueError(f"model {h:06x}: {len(new)} bytes do not fit the loaded {size}")
                    old = bytes(ad.read_memory(a, size))
                    head = base64.b64decode(it.get("expect") or "")
                    if head and (old[4:0x0C] != head[4:0x0C] or old[0x10:0x14] != head[0x10:0x14]):
                        raise ValueError(f"model {h:06x}: the loaded copy is a different model")
                    data = W.relocate(new, a, old)
                    undo.append((a, old))
                    ad.write_memory(a, data)
                    if bytes(ad.read_memory(a, len(data))) != data:
                        raise ValueError(f"model {h:06x}: read-back mismatch")
                    done.append({"model": f"{h:06x}", "address": hex(a), "bytes": len(data)})
            elif kind == "texels":
                sets = find_sets(ram, hashes=set(it["textures"]))
                expect = base64.b64decode(it.get("expect") or "")
                hit = 0
                for s in sets:
                    lo = s["address"] - MEM1[0]
                    if expect and ram[lo + s["tpl"]:lo + s["tpl"] + len(expect)] != expect:
                        continue                           # another layout of the set: leave it alone
                    a = s["address"] + int(it["offset"])
                    data = base64.b64decode(it["data"])
                    old = bytes(ad.read_memory(a, len(data)))
                    undo.append((a, old))
                    ad.write_memory(a, data)
                    done.append({"texels": hex(a), "bytes": len(data)})
                    hit += 1
                if not hit:
                    done.append({"texels": None, "note": "texture set not loaded with this layout"})
    except Exception:
        for a, old in reversed(undo):
            try:
                ad.write_memory(a, old)
            except Exception:                              # noqa: BLE001 - keep restoring the rest
                pass
        raise
    finally:
        if resume and hasattr(ad, "resume"):
            ad.resume()
    return {"written": done, "verified": True}


class TtsLiveIn(BaseModel):
    session_id: str
    op: str = "loaded"                     # loaded | apply
    items: list[dict] = []                 # apply: see apply()


class TtsLiveOut(BaseModel):
    result: dict


@tool("twin_snakes_live", "1.0", TtsLiveIn, TtsLiveOut, capabilities=["runtime", "memory"],
      permissions=[P.MEMORY_WRITE], timeout_s=600)
def twin_snakes_live(inp: TtsLiveIn, ctx):
    """Metal Gear Solid: The Twin Snakes (GC, Dolphin) live side of the character writer: op=loaded lists the cast
    models the running stage holds (for the pick whip); op=apply writes a prepared body (gbox.twin_snakes_swap) into
    the loaded copies, paused, verified and rolled back on any mismatch."""
    from .tools import SESSIONS
    ad, _g = SESSIONS[inp.session_id]
    if inp.op == "loaded":
        return {"result": loaded(ad)}
    if inp.op == "apply":
        return {"result": apply(ad, inp.items)}
    raise ValueError(f"unknown op {inp.op} (loaded | apply)")
