"""Live injection: put a writer's re-encoded model into the RUNNING game's RAM (pick_replace mode=live).

The swap writers (char_coverage.WRITERS) already re-encode a donor into the game's own model files - fitted on the
slot's skeleton, inside its budgets. This module takes the files a writer changed (the built mod against the game's
own files), turns them into the bytes the game holds in RAM (PRS / Yaz0 decompressed, AFS / BML members, Ninja NJCM
data with its POF0 pointer list) and writes the difference into the live image:

  locate     every changed window is searched in a RAM snapshot (gbox.pick_ram.find_window): exact bytes, or pointer
             words relocated by one constant (the loader's base), never anything looser. All windows of one asset
             must agree on one base; each base is one loaded instance.
  plan       the new bytes, relocated by that base (POF0 offsets when the format has them, else the original's own
             relocated words), as writes {addr, expected, data}. Refused (-> build fallback): a window not found,
             bytes the game changed at runtime inside a replaced range (animation-deformed vertices), a pointer
             layout the relocation can't explain, an executable among the changed files, a model larger than its
             footprint without a declared arena.
  apply      paused (the operator's own pause state is kept), every expected byte is re-read and checked BEFORE any
             write; then written in chunks, read back, and rolled back (and the rollback read back) on any mismatch.
             A frame check after resuming reverts a black / frozen picture.

Dedicated live paths stay where they are and are routed by gbox.pick_tool: SM64 (gbox.live_link hot swap), OoT NPCs
(gbox.oot_hot_swap via characters op=live_use).
"""
from __future__ import annotations

import base64
import gzip
import json
import struct
import time
from pathlib import Path

import numpy as np

from . import pick_ram as R

CONTEXT = 32                                  # bytes of unchanged context kept around every changed range
GAP = 64                                      # changed ranges closer than this are one window
CHUNK = 512                                   # RetroArch WRITE_CORE_MEMORY takes <= 674 bytes per command
MAX_INSTANCES = 4
EXECUTABLES = (".dol", ".elf", ".exe", ".xex", ".self", ".prx", "1st_read.bin", "main.dol", "slus_", "sles_", "scus_",
               "sces_", "slps_", "slpm_")


class Unplaceable(ValueError):
    """The change can't be put into this game's RAM safely (the reason says why; build mode still works)."""


# ---------------------------------------------------------------- assets: what the game holds in RAM

def asset(name: str, orig: bytes, new: bytes, *, orig_ptrs=None, new_ptrs=None, entries=None, whole: bool = False,
          note: str = "") -> dict:
    """One in-RAM image the writer changed. orig/new: bytes as loaded (decompressed). *_ptrs: pointer-word offsets
    (POF0) when the format lists them. entries: [(orig offset, new offset)] other structures point at (the root
    node). whole: the new image replaces the old one entirely (layout changed); else only changed windows are written."""
    return {"name": name, "orig": bytes(orig), "new": bytes(new), "orig_ptrs": sorted(orig_ptrs) if orig_ptrs is not None else None,
            "new_ptrs": sorted(new_ptrs) if new_ptrs is not None else None, "entries": [list(e) for e in entries or []],
            "whole": bool(whole), "note": note}


def is_executable(name: str) -> bool:
    n = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return any(n.endswith(x) if x.startswith(".") else (n == x or n.startswith(x)) for x in EXECUTABLES)


def pof0_decode(body: bytes) -> list[int]:
    """POF0 body -> pointer-field offsets (gbox.ninja.pof0 is the encoder)."""
    out, cur, i = [], 0, 0
    while i < len(body):
        b = body[i]
        k = b >> 6
        if k == 0:
            break
        if k == 1:
            d = b & 0x3F
            i += 1
        elif k == 2:
            d = struct.unpack_from(">H", body, i)[0] & 0x3FFF
            i += 2
        else:
            d = struct.unpack_from(">I", body, i)[0] & 0x3FFFFFFF
            i += 4
        cur += 4 * d
        out.append(cur)
    return out


def ninja_image(nj: bytes, be: bool = False) -> tuple[bytes, list[int]] | None:
    """A Ninja file (NJTL / NJCM / POF0 chunks) -> (NJCM data, its pointer offsets): what the game relocates and
    keeps in RAM (pointers = data offsets + the load address)."""
    e = ">" if be else "<"
    o = nj.find(b"NJCM")
    if o < 0 or o + 8 > len(nj):
        return None
    size = struct.unpack_from("<I", nj, o + 4)[0]          # chunk sizes are little-endian in every Ninja build
    if size > len(nj) - o - 8:
        size = struct.unpack_from(e + "I", nj, o + 4)[0]
    data = nj[o + 8:o + 8 + size]
    p = o + 8 + size
    p += (-p) % 4
    ptrs = []
    if nj[p:p + 4] == b"POF0":
        n = struct.unpack_from("<I", nj, p + 4)[0]
        ptrs = [x for x in pof0_decode(nj[p + 8:p + 8 + n]) if x + 4 <= len(data)]
    return data, ptrs


def _afs(data: bytes) -> list[tuple[int, int]] | None:
    if data[:4] != b"AFS\0" or len(data) < 8:
        return None
    n = struct.unpack_from("<I", data, 4)[0]
    if not 0 < n < 0x10000 or 8 + 8 * n > len(data):
        return None
    ents = [struct.unpack_from("<II", data, 8 + 8 * i) for i in range(n)]
    return ents if all(o + s <= len(data) for o, s in ents) else None


def expand(name: str, orig: bytes, new: bytes, be: bool = False, depth: int = 0) -> tuple[list[dict], list[str]]:
    """A changed file -> the in-RAM assets it holds, plus notes on parts that can't be injected (textures in VRAM,
    executables). Decompresses PRS (.PRS) and Yaz0, splits AFS archives and PSO BML packs, reads Ninja NJCM + POF0."""
    if orig == new:
        return [], []
    if is_executable(name):
        raise Unplaceable(f"{name} is the game's executable: the writer patches code, which is only safe from a fresh "
                          "boot (build mode)")
    notes: list[str] = []
    low = name.lower()
    if depth > 3:
        return [asset(name, orig, new)], notes
    try:
        if orig[:4] == b"Yaz0" and new[:4] == b"Yaz0":
            from .formats.lz import yaz0_decompress
            return expand(name + "#yaz0", yaz0_decompress(orig), yaz0_decompress(new), be, depth + 1)
        if low.endswith(".prs"):
            from .formats.lz import prs_decompress
            return expand(name + "#prs", prs_decompress(orig), prs_decompress(new), be, depth + 1)
        if low.endswith(".bml"):
            from . import ninja
            a, b = ninja.bml(orig, be), ninja.bml(new, be)
            out = []
            for k in sorted(set(a) | set(b)):
                if k not in a or k not in b:
                    notes.append(f"{name}:{k} added/removed (not injectable)")
                    continue
                (ab, at), (bb, bt) = a[k], b[k]
                if ab != bb:
                    sub, n2 = expand(f"{name}:{k}", ab, bb, be, depth + 1)
                    out += sub
                    notes += n2
                if at != bt:
                    notes.append(f"{name}:{k} texture archive changed: textures live in VRAM, not injected")
            return out, notes
    except Unplaceable:
        raise
    except Exception as e:                                   # noqa: BLE001 - an unreadable container is a raw diff
        notes.append(f"{name}: container not decoded ({type(e).__name__}: {e}); compared as raw bytes")
    ea, eb = _afs(orig), _afs(new)
    if ea and eb and len(ea) == len(eb):
        out = []
        for i, ((oa, sa), (ob, sb)) in enumerate(zip(ea, eb)):
            if orig[oa:oa + sa] != new[ob:ob + sb]:
                sub, n2 = expand(f"{name}[{i}]", orig[oa:oa + sa], new[ob:ob + sb], be, depth + 1)
                out += sub
                notes += n2
        return out, notes
    if b"NJCM" in orig[:0x4000] and b"NJCM" in new[:0x4000]:
        a, b = ninja_image(orig, be), ninja_image(new, be)
        if a and b and a[1] and b[1]:
            return [asset(name + "#NJCM", a[0], b[0], orig_ptrs=a[1], new_ptrs=b[1], entries=[(0, 0)],
                          whole=a[1] != b[1] or len(a[0]) != len(b[0]), note="Ninja chunk model (POF0 relocated)")], notes
    if low.endswith((".pvr", ".pvm", ".gvm", ".gvr")):
        return [], notes + [f"{name}: texture archive (VRAM): not injected"]
    return [asset(name, orig, new, whole=len(orig) != len(new))], notes


# ---------------------------------------------------------------- planning against a RAM snapshot

def diff_windows(orig: bytes, new: bytes, context: int = CONTEXT, gap: int = GAP) -> list[tuple[int, int]]:
    """Changed word ranges of two images, with context, merged: [(lo, hi)] offsets into orig (4-aligned)."""
    n = min(len(orig), len(new))
    idx = np.flatnonzero(np.frombuffer(orig[:n], np.uint8) != np.frombuffer(new[:n], np.uint8))
    rng = []
    if len(idx):
        cut = np.flatnonzero(np.diff(idx) > gap)
        rng = list(zip(np.r_[idx[0], idx[cut + 1]].tolist(), (np.r_[idx[cut], idx[-1]] + 1).tolist()))
    if len(new) > len(orig):
        rng.append((len(orig), len(new)))
    out = []
    for lo, hi in rng:
        lo = max(0, (lo - context) & ~3)
        hi = min(max(len(orig), len(new)), (hi + context + 3) & ~3)
        if out and lo <= out[-1][1] + gap:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def _probes(a: dict) -> list[tuple[int, int]]:
    """Windows of the original used to locate an asset: its changed windows (diff), or windows spread over the
    whole image (whole replacement)."""
    orig, new = a["orig"], a["new"]
    if not a["whole"]:
        return [(lo, min(hi, len(orig))) for lo, hi in diff_windows(orig, new) if lo < len(orig)]
    n = len(orig)
    size = min(256, n & ~3)
    if size <= 0:
        return []
    if n - size < 64:
        return [(0, size)]
    k = min(6, n // 4096 + 2)
    return [(s, s + size) for s in sorted({((n - size) * i // (k - 1)) & ~3 for i in range(k)})]


def locate(ram: R.Ram, a: dict, hint: int | None = None) -> list[dict]:
    """Loaded instances of an asset's original image: [{base, delta, score, windows}] (base = RAM address of its
    first byte; delta = what the loader added to pointer words)."""
    orig = a["orig"]
    probes = _probes(a)
    if not probes:
        return []
    ptr = set(a["orig_ptrs"] or ())
    bases: dict[int, list] = {}
    lo, hi = probes[0]
    first = find_window(ram, orig[lo:hi], {p - lo for p in ptr if lo <= p < hi} if a["orig_ptrs"] is not None else None)
    for c in first:
        bases[c["addr"] - lo] = [(lo, hi, c)]
    out = []
    for base, got in bases.items():
        ok, delta = True, got[0][2]["delta"]
        for lo2, hi2 in probes[1:]:
            v = R.verify_at(ram, base + lo2, orig[lo2:hi2], {p - lo2 for p in ptr if lo2 <= p < hi2} or None,
                            delta or None)
            if v["score"] < 0.9 or (delta and v["delta"] not in (0, delta)):
                ok = False
                break
            delta = delta or v["delta"]
            got.append((lo2, hi2, v))
        if ok:
            out.append({"base": base, "delta": delta or 0, "score": min(g[2]["score"] for g in got), "windows": got})
    if hint is not None:
        out.sort(key=lambda c: (not (c["base"] <= hint < c["base"] + max(len(orig), 1)), -c["score"]))
    else:
        out.sort(key=lambda c: -c["score"])
    return out


def find_window(ram, window, ptr_offs):
    return R.find_window(ram, window, ptr_offs, min_score=0.9)


def _relocate(new: bytes, ptrs, delta: int, e: str) -> bytes:
    b = bytearray(new)
    for p in ptrs or ():
        if p + 4 <= len(b):
            v = struct.unpack_from(e + "I", b, p)[0]          # a listed field is relocated even when 0
            struct.pack_into(e + "I", b, p, (v + delta) & 0xFFFFFFFF)
    return bytes(b)


def _ranges(a: bytes, b: bytes, word: int = 4) -> list[tuple[int, int]]:
    """Word-aligned ranges where a and b differ."""
    out = []
    n = min(len(a), len(b))
    i = 0
    while i < n:
        if a[i:i + word] != b[i:i + word]:
            j = i + word
            while j < n and a[j:j + word] != b[j:j + word]:
                j += word
            out.append((i, min(j, n)))
            i = j
        else:
            i += word
    return out


def plan_instance(ram: R.Ram, a: dict, inst: dict, arenas=(), guard: int = 256) -> dict:
    """The writes that turn one loaded instance into the new image. Raises Unplaceable with the reason."""
    e = ram.e
    orig, new, base, delta = a["orig"], a["new"], inst["base"], inst["delta"]
    cur = ram.read(base, len(orig))
    if a["orig_ptrs"] is not None:                          # pointer words known (POF0)
        expect = _relocate(orig, a["orig_ptrs"], delta, e)
        rel = set(a["orig_ptrs"])
        mism = [o for o in range(0, len(orig) - 3, 4) if expect[o:o + 4] != cur[o:o + 4]]
    else:                                                   # learn the relocated words from the instance itself
        v = R.verify_at(ram, base, orig, None, delta or None)
        rel = set(v["relocated"])
        expect = _relocate(orig, sorted(rel), delta, e)
        mism = v["mismatched"]
    writes, repoints = [], []
    if not a["whole"] and len(new) <= len(orig):
        if a["new_ptrs"] is not None:
            data = _relocate(new, a["new_ptrs"], delta, e)
        else:
            data = bytearray(new)
            for o in sorted(rel):                          # the loader's relocation, learned from this instance
                if o + 4 <= len(new):
                    w, ow = struct.unpack_from(e + "I", new, o)[0], struct.unpack_from(e + "I", orig, o)[0]
                    if not (w == 0 and ow != 0):           # a pointer the writer cleared stays null
                        struct.pack_into(e + "I", data, o, (w + delta) & 0xFFFFFFFF)
            for lo, hi in _ranges(orig, new):
                for o in range(lo & ~3, hi, 4):
                    if o + 4 > len(new) or o in rel:
                        continue
                    w = struct.unpack_from(e + "I", new, o)[0]
                    if delta and w != struct.unpack_from(e + "I", orig, o)[0] and 0 < w < len(new) and w % 4 == 0:
                        # a changed word that reads like an in-file offset where the original had no relocated
                        # pointer: without a pointer table it can't be told from data -> refuse, never guess
                        raise Unplaceable(f"{a['name']}: the word at +{o:#x} may be a new pointer the loader would "
                                          "relocate; this format has no pointer table to tell")
            data = bytes(data)
        for lo, hi in _ranges(expect[:len(data)], data):
            bad = [o for o in mism if lo <= o < hi]
            if bad:
                raise Unplaceable(f"{a['name']}: {len(bad)} word(s) the game changed at runtime lie inside replaced bytes "
                                  f"(first at +{bad[0]:#x}): the in-RAM model isn't a copy of the file there "
                                  "(animated / deformed geometry)")
            writes.append({"addr": base + lo, "expected": cur[lo:hi], "data": data[lo:hi],
                           "label": f"{a['name']}+{lo:#x}"})
        return {"base": base, "delta": delta, "writes": writes, "repoints": [], "placement": "in place",
                "bytes": sum(len(w["data"]) for w in writes)}
    # whole replacement: needs the new image's pointer list
    if a["new_ptrs"] is None:
        raise Unplaceable(f"{a['name']}: the new image's layout differs and its format lists no pointers (POF0): "
                          "it can't be relocated into RAM")
    if mism:
        raise Unplaceable(f"{a['name']}: {len(mism)} word(s) of the loaded model differ from the file (runtime state): "
                          "a whole replacement would discard them")
    entries = [tuple(x) for x in (a["entries"] or [(0, 0)])]
    inside = ram.pointers_to(base + 1, base + len(orig), limit=64, exclude=[(base, base + len(orig))])
    stray = sorted({ram.canon(raw) - base for _at, raw in inside} - {o for o, _n in entries})
    if stray:
        raise Unplaceable(f"{a['name']}: other structures point into the loaded model (+{stray[0]:#x}"
                          f"{' and more' if len(stray) > 1 else ''}): replacing its layout would leave them dangling")
    place = base
    if len(new) > len(orig):
        fr = R.free_region(ram, len(new), list(arenas), guard)
        if not fr:
            raise Unplaceable(f"{a['name']}: the fitted model ({len(new)} bytes) is larger than the loaded one "
                              f"({len(orig)} bytes) and no declared free arena fits it")
        place = fr["start"]
    data = _relocate(new, a["new_ptrs"], delta + (place - base), e)   # pointers = offset + (load address - file key)
    old = ram.read(place, len(data))
    for lo, hi in _ranges(old, data):
        writes.append({"addr": place + lo, "expected": old[lo:hi], "data": data[lo:hi], "label": f"{a['name']}+{lo:#x}"})
    for o_off, n_off in entries:
        if place == base and o_off == n_off:
            continue
        for at, raw in ram.pointers_to(base + o_off, base + o_off + 1,
                                       exclude=[(base, base + len(orig)), (place, place + len(new))]):
            form = raw - (base + o_off)                     # keep the alias form (0x0C.. / 0x8C.. / 0xAC..)
            repoints.append({"addr": at, "expected": struct.pack(e + "I", raw),
                             "data": struct.pack(e + "I", (place + n_off + form) & 0xFFFFFFFF),
                             "label": f"pointer to {a['name']}+{o_off:#x}"})
    if place != base and not repoints:
        raise Unplaceable(f"{a['name']}: moved to {place:#x} but nothing in RAM points at the old root: the game "
                          "would keep drawing the old copy")
    return {"base": base, "delta": delta, "writes": writes, "repoints": repoints,
            "placement": "in place" if place == base else f"arena {place:#x}",
            "bytes": sum(len(w["data"]) for w in writes + repoints)}


def plan(ram: R.Ram, assets: list[dict], hint: int | None = None, arenas=(), max_instances: int = MAX_INSTANCES) -> dict:
    """Every asset located and planned. -> {ok, writes, assets: [{name, instances, reason}], reason}. ok only when
    every asset has at least one placeable instance (a half-swapped model is worse than none)."""
    rows, writes, reasons = [], [], []
    for a in assets:
        row = {"name": a["name"], "orig_bytes": len(a["orig"]), "new_bytes": len(a["new"]), "whole": a["whole"],
               "note": a.get("note", ""), "instances": []}
        found = locate(ram, a, hint)
        if not found:
            row["reason"] = "not in RAM (the game hasn't loaded it, or keeps it in another form)"
            reasons.append(f"{a['name']}: {row['reason']}")
            rows.append(row)
            continue
        for inst in found[:max_instances]:
            try:
                p = plan_instance(ram, a, inst, arenas)
            except Unplaceable as ex:
                row.setdefault("refused", []).append({"base": hex(inst["base"]), "reason": str(ex)})
                continue
            row["instances"].append({"base": hex(p["base"]), "delta": hex(p["delta"]), "placement": p["placement"],
                                     "bytes": p["bytes"], "writes": len(p["writes"]), "repoints": len(p["repoints"]),
                                     "score": round(inst["score"], 4)})
            writes += p["writes"] + p["repoints"]
        if not row["instances"]:
            row["reason"] = (row.get("refused") or [{"reason": "no placeable instance"}])[0]["reason"]
            reasons.append(f"{a['name']}: {row['reason']}")
        rows.append(row)
    ok = bool(assets) and not reasons and bool(writes)
    return {"ok": ok, "writes": _merge(writes), "assets": rows, "reason": "; ".join(reasons) if reasons else
            ("nothing to write (the model in RAM already matches)" if not writes else "")}


def _merge(writes: list[dict]) -> list[dict]:
    """Sorted, non-overlapping writes (an overlap is a planning bug: refuse rather than guess)."""
    ws = sorted(writes, key=lambda w: w["addr"])
    for x, y in zip(ws, ws[1:]):
        if y["addr"] < x["addr"] + len(x["data"]):
            raise Unplaceable(f"overlapping writes at {y['addr']:#x} ({x['label']} / {y['label']})")
    return ws


# ---------------------------------------------------------------- applying (paused, verified, reversible)

def _state(ad) -> str | None:
    try:
        return str((ad.query_runtime() or {}).get("state") or "") or None
    except Exception:                                        # noqa: BLE001
        return None


def _aligned(ram: R.Ram, w: dict) -> dict:
    """Word-swapped devices write whole words: widen a write to 4-aligned bounds with the expected bytes."""
    if not ram.swapped:
        return w
    a, d, x = w["addr"], w["data"], w["expected"]
    lo, hi = a & ~3, (a + len(d) + 3) & ~3
    pre, post = ram.read(lo, a - lo), ram.read(a + len(d), hi - a - len(d))
    return {**w, "addr": lo, "data": pre + d + post, "expected": pre + x + post}


def _write(ad, ram: R.Ram, addr: int, data: bytes, chunk: int) -> int:
    n = 0
    for k in range(0, len(data), chunk):
        part = data[k:k + chunk]
        r = ad.write_memory(addr + k, ram.device_bytes(addr + k, part))
        got = (r or {}).get("written", len(part)) if isinstance(r, dict) else len(part)
        if got != len(part):
            raise RuntimeError(f"the emulator wrote {got} of {len(part)} bytes at {addr + k:#x}")
        n += len(part)
    return n


def apply(ad, ram: R.Ram, writes: list[dict], *, chunk: int = CHUNK, frame_check=None, revert_on_fail: bool = True,
          progress=None) -> dict:
    """Write a plan into the running game. All-or-nothing: paused, expected bytes re-read and checked first, writes
    read back, rollback (read back too) on any failure. The operator's pause state is restored."""
    t0 = time.time()
    writes = [_aligned(ram, w) for w in writes]
    total = sum(len(w["data"]) for w in writes)
    before = _state(ad)
    was_paused = before == "PAUSED"
    paused_here = False
    if not was_paused:
        try:
            r = ad.pause()
            st = (r or {}).get("state") if isinstance(r, dict) else None
            paused_here = True
            if (st or _state(ad)) not in ("PAUSED", None):
                raise RuntimeError(f"pause reported {st or _state(ad)}")
        except Exception as ex:                              # noqa: BLE001
            if paused_here:
                try:
                    ad.resume()
                except Exception:                            # noqa: BLE001
                    pass
            raise RuntimeError(f"could not pause the game ({ex}); no model bytes were written") from ex
    rep = {"writes": len(writes), "bytes": total, "verified": False, "rolled_back": False, "paused_by_gbox": paused_here}
    written: list[dict] = []
    try:
        for w in writes:                                     # 1. every expected byte, fresh, before any write
            cur = ram.read_live(ad, w["addr"], len(w["expected"]))
            if cur != w["expected"]:
                k = next(i for i in range(len(cur)) if cur[i] != w["expected"][i]) if len(cur) == len(w["expected"]) else 0
                raise RuntimeError(f"RAM changed since the snapshot at {w['addr'] + k:#x} ({w['label']}): no bytes written")
        done = 0
        for w in writes:                                     # 2. write
            written.append(w)
            done += _write(ad, ram, w["addr"], w["data"], chunk)
            if progress:
                progress(done, total)
        bad = [w for w in writes if ram.read_live(ad, w["addr"], len(w["data"])) != w["data"]]   # 3. read back
        if bad:
            raise RuntimeError(f"read-back mismatch at {bad[0]['addr']:#x} ({bad[0]['label']})")
        rep["verified"] = True
    except Exception as ex:
        rep["error"] = str(ex)
        if written:
            rep["rolled_back"] = True
            for w in reversed(written):
                _write(ad, ram, w["addr"], w["expected"], chunk)
            left = [w for w in written if ram.read_live(ad, w["addr"], len(w["expected"])) != w["expected"]]
            if left:
                rep["rollback_failed"] = [hex(w["addr"]) for w in left]
                raise RuntimeError(f"live write failed ({ex}) and the rollback did not verify at "
                                   f"{', '.join(rep['rollback_failed'][:4])}: the game is left paused") from ex
        if paused_here:
            try:
                ad.resume()
            except Exception:                                # noqa: BLE001
                pass
        raise RuntimeError(f"{ex}" + ("; every written byte was restored" if written else "")) from ex
    if paused_here:
        try:
            ad.resume()
        except Exception as ex:                              # noqa: BLE001
            rep["resume_error"] = str(ex)
    rep["pause_preserved"] = (_state(ad) == "PAUSED") == was_paused if _state(ad) is not None else True
    if frame_check is not None and not was_paused:
        try:
            fc = frame_check()
        except Exception as ex:                              # noqa: BLE001
            fc = {"ok": True, "skipped": str(ex)}
        rep["frame_check"] = fc
        if not fc.get("ok") and revert_on_fail:
            rep["reverted"] = revert(ad, ram, writes, chunk)
            rep["verified"] = False
    rep["seconds"] = round(time.time() - t0, 2)
    return rep


def revert(ad, ram: R.Ram, writes: list[dict], chunk: int = CHUNK) -> dict:
    """Put the expected (original) bytes back, paused, verified."""
    st = _state(ad)
    paused_here = False
    if st != "PAUSED":
        try:
            ad.pause()
            paused_here = True
        except Exception:                                    # noqa: BLE001
            pass
    try:
        for w in reversed(writes):
            _write(ad, ram, w["addr"], w["expected"], chunk)
        ok = all(ram.read_live(ad, w["addr"], len(w["expected"])) == w["expected"] for w in writes)
    finally:
        if paused_here:
            try:
                ad.resume()
            except Exception:                                # noqa: BLE001
                pass
    return {"restored": ok, "writes": len(writes)}


# ---------------------------------------------------------------- the patch artifact (control plane -> session)

def pack(assets: list[dict], meta: dict) -> bytes:
    enc = lambda b: base64.b64encode(b).decode()             # noqa: E731
    rows = [{k: (enc(v) if k in ("orig", "new") else v) for k, v in a.items()} for a in assets]
    return gzip.compress(json.dumps({"format": "gbox-live-patch-v1", **meta, "assets": rows}).encode())


def unpack(blob: bytes) -> tuple[list[dict], dict]:
    d = json.loads(gzip.decompress(blob) if blob[:2] == b"\x1f\x8b" else blob)
    if d.get("format") != "gbox-live-patch-v1":
        raise ValueError("not a gBox live patch")
    rows = d.pop("assets")
    for a in rows:
        a["orig"], a["new"] = base64.b64decode(a["orig"]), base64.b64decode(a["new"])
    return rows, d


def signatures(assets: list[dict], size: int = 64, count: int = 3) -> list[dict]:
    """Small searchable pieces of each asset's original image (learned into the profile: a later pick finds the
    model's RAM address without the patch)."""
    out = []
    for a in assets:
        orig = a["orig"]
        ptr = set(a.get("orig_ptrs") or ())
        offs = R._anchor_offsets(len(orig), ptr, size, count)
        sig = [{"offset": o, "hex": orig[o:o + size].hex()} for o in offs if len(set(orig[o:o + size])) > 4]
        if sig:
            out.append({"name": a["name"], "size": len(orig), "pieces": sig})
    return out


def find_signatures(ram: R.Ram, sigs: list[dict]) -> list[dict]:
    """Learned signatures -> where those model images are loaded now: [{name, base, pieces_found}]."""
    out = []
    for s in sigs:
        bases = {}
        for p in s["pieces"]:
            for c in R.find_window(ram, bytes.fromhex(p["hex"]), None, min_score=1.0, limit=4):
                bases.setdefault(c["addr"] - p["offset"], []).append(p["offset"])
        for b, got in sorted(bases.items(), key=lambda kv: -len(kv[1])):
            if len(got) >= max(1, len(s["pieces"]) - 1):
                out.append({"name": s["name"], "base": b, "size": s["size"], "pieces_found": len(got),
                            "pieces": len(s["pieces"])})
    return out


# ---------------------------------------------------------------- built mod -> assets (control plane)

class _Iso:
    """A cooked (2048-byte sector) ISO9660 image: PS2 DVDs, PS1 / PSP ISOs."""

    def __init__(self, path: Path):
        from .formats import iso9660
        self.f = open(path, "rb")
        self._read = iso9660.file_reader(self.f)
        pvd = self._read(16, 2048)
        if pvd[1:6] != b"CD001":
            self.f.close()
            raise Unplaceable(f"{Path(path).name}: no ISO9660 volume")
        self.files = iso9660.files(self._read, *iso9660.pvd_root(pvd))

    def read(self, name: str) -> bytes:
        lba, size = self.files[name]
        return self._read(lba, size)


def _reader(path: Path):
    p = Path(path)
    suf = p.suffix.lower()
    if suf == ".gdi":
        from .gdrom import GDRom
        return GDRom(str(p))
    if suf in (".iso", ".gcm"):
        with open(p, "rb") as f:
            head = f.read(0x20)
        if head[0x1C:0x20] == b"\xC2\x33\x9F\x3D" or head[0x18:0x1C] == b"\x5D\x1C\x9E\xA3":
            from .gcdisc import GCDisc
            return GCDisc(p)
        return _Iso(p)
    if suf == ".chd":
        from .psxdisc import PSXDisc
        return PSXDisc(str(p))
    if suf == ".bin":
        from .psxdisc import RawBin
        return RawBin(str(p), writable=False)
    raise Unplaceable(f"{p.name}: no reader for this image type (ROM images are patched in place, not as files)")


def _lookup(reader, name: str) -> str | None:
    """A marker's file name as the reader keys it (case, leading slash, ';1')."""
    if name in reader.files:
        return name
    want = name.replace("\\", "/").lstrip("/").split(";")[0].lower()
    return next((k for k in reader.files if k.replace("\\", "/").lstrip("/").split(";")[0].lower() == want), None)


def mod_files(mod_dir: Path, base: Path) -> tuple[list[tuple[str, bytes, bytes]], dict]:
    """(file, original bytes, new bytes) for every file the writer changed, from the mod's marker. base: the game's
    original image (single-image mods) or its unpacked folder (folder mods)."""
    mod_dir, base = Path(mod_dir), Path(base)
    marker = json.loads((mod_dir / ".gbox-mod.json").read_text(encoding="utf-8"))
    files = [f for f in marker.get("files") or [] if not str(f).endswith(" (new)") and f != "@image"]
    out = []
    if marker.get("image"):
        new_r, old_r = _reader(mod_dir / marker["image"]), _reader(base)
        try:
            if not files:                                   # unlisted: compare the two file tables (bounded)
                files = changed_files(old_r, new_r)
            for f in files:
                a, b = _lookup(old_r, f), _lookup(new_r, f)
                if a and b:
                    out.append((f, old_r.read(a), new_r.read(b)))
        finally:
            for r in (new_r, old_r):
                fh = getattr(r, "f", None)
                if fh is not None:
                    fh.close()
    else:
        for f in files:
            if (base / f).is_file():
                out.append((f, (base / f).read_bytes(), (mod_dir / f).read_bytes()))
    if not out:
        raise Unplaceable("the built mod changes no file that exists in the original game")
    return out, marker


def changed_files(old_r, new_r, max_file: int = 64 << 20, budget: int = 1 << 31) -> list[str]:
    """Files whose bytes differ between two disc images (same path in both; huge files skipped)."""
    out, read = [], 0
    for f, ext in new_r.files.items():
        o = old_r.files.get(f)
        if o is None or ext[1] > max_file:
            continue
        if o[1] != ext[1]:
            out.append(f)
            continue
        read += 2 * ext[1]
        if read > budget:
            break
        if old_r.read(f) != new_r.read(f):
            out.append(f)
    return out


def assets_from_files(pairs, be: bool) -> tuple[list[dict], list[str]]:
    assets, notes = [], []
    for name, orig, new in pairs:
        a, n = expand(name, orig, new, be)
        assets += a
        notes += n
    return assets, notes
