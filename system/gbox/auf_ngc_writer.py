"""007: Agent Under Fire (GameCube, GW7E69) level package writer.

Rebuilds ``maps/*.ngc`` packages read by :mod:`gbox.auf_ngc`, so a character
model (``models/actors/**.gcm``) inside a level's ``restable`` file system can be
replaced.  Every constraint below was read from the owned disc's Bond.elf
(sha256 1a9c0d19..e716f, symbols kept):

``ReadChunkData`` 0x80010A7C
    Compressed chunk: ``buf = malloc(mem_size + 0x40)``; the ``disk_size`` stored
    bytes are read to ``buf + mem_size + 0x40 - disk_size`` and
    ``BOA_ExpandInplace(buf, mem_size, src)`` expands them in place.  So a stream
    must decode exactly ``mem_size`` bytes, ``disk_size <= mem_size + 0x40``, and
    the write cursor must never overtake the unread input (``inplace_ok``).
    Uncompressed chunk: ``malloc(disk_size)`` and a plain read.

``FS_UseResourceTable`` 0x801AEF64 / ``FS_FindResource`` 0x801AEE38
    The restable is used in place: ``name_off``/``data_off`` are relocated by the
    table base, and lookups binary-search the records by ``HashString``
    0x801AEECC (``h = h * 65599 + c`` with ASCII upper case folded, signed char,
    unsigned compare).  Records must therefore stay sorted by hash.  Shipped
    tables put header/records first, then every file 16-byte aligned in record
    order, then (16-aligned) the NUL-terminated names in record order, zero-padded
    to 32.  ``build_restable`` reproduces all 38 shipped tables byte-for-byte.
    Models are fixed up in place (``NGCObject3D::FixupModelData``) with offsets
    relative to the file, so a whole .gcm can be moved to any 16-aligned offset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys

from gbox import auf_ngc as ngc

CHUNK_PAD = 0xCDCDCDCD
INPLACE_SLACK = 0x40          # ReadChunkData: malloc(mem_size + 0x40)
DATA_ALIGN = 16
TABLE_ALIGN = 32
MAX_DIST = 0xFFF
MIN_MATCH, MAX_MATCH = 3, 17  # nibble 1..15 -> 3..17 (nibble 0 is a no-op)

GAME_ID = "65b7187589166b26"

EVIDENCE = {
    "ReadChunkData": 0x80010A7C,
    "BOA_ExpandInplace": 0x8001094C,
    "FS_UseResourceTable": 0x801AEF64,
    "FS_FindResource": 0x801AEE38,
    "HashString": 0x801AEECC,
}


def _align(n: int, a: int) -> int:
    return (n + a - 1) & -a


def hash_string(name: str) -> int:
    """HashString 0x801AEECC: h = h*65599 + c over the lower-cased name."""
    h = 0
    for c in name.encode("latin-1"):
        if 0x41 <= c <= 0x5A:
            c += 0x20
        elif c >= 0x80:
            c -= 0x100
        h = (h * 65599 + c) & 0xFFFFFFFF
    return h


def restable_entries(table: bytes) -> list[tuple[str, bytes]]:
    return [(r.name, table[r.offset:r.offset + r.size]) for r in ngc.parse_restable(table)]


def build_restable(entries) -> bytes:
    """Lay out a restable exactly like the shipped ones (records sorted by hash)."""
    rows = sorted(((hash_string(n), n, bytes(b)) for n, b in entries), key=lambda r: r[0])
    hashes = [r[0] for r in rows]
    if len(set(hashes)) != len(hashes):
        raise ValueError("restable hash collision")
    pos = 0x10 + 16 * len(rows)
    data_offs = []
    for _h, _n, b in rows:
        pos = _align(pos, DATA_ALIGN)
        data_offs.append(pos)
        pos += len(b)
    name_offs = []
    pos = _align(pos, DATA_ALIGN)
    for _h, n, _b in rows:
        name_offs.append(pos)
        pos += len(n.encode("latin-1")) + 1
    out = bytearray(_align(pos, TABLE_ALIGN))
    struct.pack_into(">I", out, 0, len(rows))
    for i, (h, n, b) in enumerate(rows):
        struct.pack_into(">4I", out, 0x10 + 16 * i, name_offs[i], data_offs[i], len(b), h)
        out[data_offs[i]:data_offs[i] + len(b)] = b
        nb = n.encode("latin-1")
        out[name_offs[i]:name_offs[i] + len(nb)] = nb
    return bytes(out)


def boa_compress(data: bytes, depth: int = 24) -> bytes:
    """Greedy LZ encoder for BOA_ExpandInplace (decodes with ``auf_ngc.boa_expand``)."""
    n = len(data)
    out = bytearray()
    head: dict = {}
    prev = [-1] * n
    i = 0

    def insert(k):
        if k + 3 <= n:
            key = data[k:k + 3]
            prev[k] = head.get(key, -1)
            head[key] = k

    while i < n:
        fpos = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if i >= n:
                break
            best, bdist = 0, 0
            if i + MIN_MATCH <= n:
                lim = min(MAX_MATCH, n - i)
                j = head.get(data[i:i + 3], -1)
                tries = depth
                while j >= 0 and tries and i - j <= MAX_DIST:
                    if data[j + best] == data[i + best] if best < lim else False:
                        ln = 0
                        while ln < lim and data[j + ln] == data[i + ln]:
                            ln += 1
                        if ln > best:
                            best, bdist = ln, i - j
                            if ln == lim:
                                break
                    j = prev[j]
                    tries -= 1
            if best >= MIN_MATCH:
                out.append(((bdist & 15) << 4) | (best - 2))
                out.append(bdist >> 4)
                for k in range(i, i + best):
                    insert(k)
                i += best
            else:
                flags |= 1 << bit
                out.append(data[i])
                insert(i)
                i += 1
        out[fpos] = flags
    return bytes(out)


def inplace_ok(stream: bytes, size: int, mem_size: int) -> bool:
    """Replay BOA_ExpandInplace with ReadChunkData's buffer layout."""
    buf = mem_size + INPLACE_SLACK
    r = buf - len(stream)
    if r < 0:
        return False
    w = i = 0
    while w < size:
        flags = stream[i]
        i += 1
        for bit in range(8):
            if w >= size:
                break
            if flags >> bit & 1:
                i += 1
                w += 1
            else:
                b0 = stream[i]
                i += 2
                if b0 & 15:
                    w += (b0 & 15) + 2
            if w > r + i:
                return False
    return True


def encode_chunk(cid: str, payload: bytes, version: float = 1.0, compress: bool = True,
                 size: int | None = None) -> bytes:
    size = len(payload) if size is None else size
    if compress:
        mem = _align(size, 32)
        body = payload[:mem].ljust(mem, b"\0")
        stream = boa_compress(body)
        if len(stream) < mem and inplace_ok(stream, mem, mem):
            hdr = ngc.encode_chunk_id(cid) + struct.pack(">IfIIII", size, version, 1, CHUNK_PAD,
                                                         len(stream), mem)
            return _pad32(hdr + stream)
    hdr = ngc.encode_chunk_id(cid) + struct.pack(">IfIIII", size, version, 0, CHUNK_PAD,
                                                 len(payload), len(payload))
    return _pad32(hdr + payload)


def _pad32(b: bytes) -> bytes:
    return b + b"\0" * (-len(b) % 32)


def write_package(pkg: "ngc.NgcPackage", payloads: dict | None = None, compress: bool = True) -> bytes:
    """Rewrite a package; chunks not in ``payloads`` are copied byte-for-byte."""
    payloads = payloads or {}
    out = bytearray()
    for c in pkg.chunks:
        if c.id in payloads:
            out += encode_chunk(c.id, payloads[c.id], c.version, compress)
        else:
            out += pkg.data[c.offset:c.end]
    return bytes(out)


def replace_resources(pkg: "ngc.NgcPackage", repl: dict, compress: bool = True) -> bytes:
    """Return package bytes with restable files replaced by name (names/hashes kept)."""
    entries = restable_entries(pkg.table)
    have = {n.lower() for n, _ in entries}
    missing = [n for n in repl if n.lower() not in have]
    if missing:
        raise KeyError("not in restable: %s" % ", ".join(missing))
    low = {k.lower(): v for k, v in repl.items()}
    entries = [(n, low.get(n.lower(), b)) for n, b in entries]
    return write_package(pkg, {"restable": build_restable(entries)}, compress)


def check_package(data: bytes, expect: dict | None = None) -> dict:
    """Re-read a written package: chunk walk, in-place safety, restable sort, gcm tiling."""
    pkg = ngc.NgcPackage(data)
    probs = []
    for c in pkg.chunks:
        if c.compressed:
            raw = data[c.data_offset:c.data_offset + c.disk_size]
            if c.disk_size > c.mem_size + INPLACE_SLACK:
                probs.append("%s: disk %d > mem+0x40" % (c.id, c.disk_size))
            elif not inplace_ok(raw, c.mem_size, c.mem_size):
                probs.append("%s: in-place expansion overruns its input" % c.id)
    res = pkg.resources()
    hs = [r.hash for r in res]
    if hs != sorted(hs):
        probs.append("restable records not sorted by hash")
    for r in res:
        if hash_string(r.name) != r.hash:
            probs.append("hash mismatch %s" % r.name)
        if r.offset % DATA_ALIGN:
            probs.append("misaligned %s" % r.name)
        if r.name.startswith("models/actors/") and r.name.endswith(".gcm"):
            g = pkg.table[r.offset:r.offset + r.size]
            try:
                tp = ngc.tile_check(ngc.gcm_info(g))
            except (ValueError, struct.error) as e:
                tp = [str(e)]
            probs += ["%s: %s" % (r.name, p) for p in tp]
    for name, sha in (expect or {}).items():
        got = hashlib.sha256(pkg.read(name)).hexdigest()
        if got != sha:
            probs.append("%s sha %s != %s" % (name, got, sha))
    return {"chunks": [(c.id, c.compressed, c.disk_size, c.mem_size) for c in pkg.chunks],
            "resources": len(res), "problems": probs}


def swap_models(pkg: "ngc.NgcPackage", pairs) -> tuple[bytes, list]:
    """Put each donor .gcm (same level, so its shader ids resolve) in a target's file.

    ``pairs`` is a list of (target, donor) restable names.  Every donor bone hash
    must exist in the target's skeleton, because the target slot's .gca animations
    bind by gcm bone name hash (a donor bone the slot never animates would stay in
    its rest pose); the names (and so the restable hashes) of the targets stay."""
    shd = ngc.shaders(pkg)
    repl, info = {}, []
    for target, donor in pairs:
        tg, dg = pkg.read(target), pkg.read(donor)
        tb = {b["hash"] for b in ngc.skeleton(tg)}
        db = {b["hash"] for b in ngc.skeleton(dg)}
        if not db <= tb:
            raise ValueError("%s: donor %s has %d bone(s) the target slot does not animate"
                             % (target, donor, len(db - tb)))
        m = ngc.mesh(dg)
        if any(x not in shd for x in m["shaders"]):
            raise ValueError("%s references shaders missing from this level" % donor)
        repl[target] = dg
        info.append({"target": target, "donor": donor,
                     "target_sha256": hashlib.sha256(tg).hexdigest(),
                     "donor_sha256": hashlib.sha256(dg).hexdigest(),
                     "bones": len(tb), "donor_triangles": len(m["faces"])})
    return replace_resources(pkg, repl), info


def body_swap(pkg: "ngc.NgcPackage", target: str, donor: str) -> tuple[bytes, dict]:
    out, info = swap_models(pkg, [(target, donor)])
    return out, info[0]


# Multiplayer "Bond (combat)" (models/mp_player_bondcombat.men) wears
# bond_combat_l (35 bones) + bond_head_l (34); the underwater-base thug's body
# (34) and head (34) use only bone hashes of those skeletons.
DEFAULT_LEVEL = "maps/dm1.ngc"
DEFAULT_PAIRS = (("models/actors/bond/bond_combat_l.gcm", "models/actors/thugs/thug_uwb_l.gcm"),
                 ("models/actors/actorheads/bond_head_l.gcm", "models/actors/actorheads/thug_uwb1_l.gcm"))


def build_mod(cache, gcz, name: str, pairs=DEFAULT_PAIRS, level: str = DEFAULT_LEVEL, progress=None) -> dict:
    """A separate disc-image mod: the GCZ unpacked to ISO with ``level`` rebuilt."""
    import tempfile
    import types
    from pathlib import Path
    from . import au_inventory, filemods
    with tempfile.TemporaryDirectory() as td:
        got = au_inventory.extract(str(gcz), [Path(level).name], td)
        src = Path(got[0]["out"]).read_bytes()
    pkg = ngc.NgcPackage(src)
    data, info = swap_models(pkg, pairs)
    chk = check_package(data, {t: i["donor_sha256"] for t, i in zip((p[0] for p in pairs), info)})
    if chk["problems"]:
        raise ValueError("rebuilt %s failed its check: %s" % (level, chk["problems"][:5]))
    b = filemods.build_image(types.SimpleNamespace(cache=Path(cache)), GAME_ID, Path(gcz), name,
                             {level: {"bytes": data}}, progress)
    return b | {"level": level, "level_sha256": hashlib.sha256(data).hexdigest(), "level_size": len(data),
                "source_level_sha256": hashlib.sha256(src).hexdigest(), "swaps": info, "check": chk}




# ---------------------------------------------------------------------------
# Cast-wide replacement: map every actor .gcm in a level to a donor .gcm.
# The donor skeleton must be a subset of the target skeleton (same animation
# hashes); use this for same-game cast randomization.  Cross-game retargeting
# (e.g. WWE wrestlers into AUF) needs a glTF-to-.gcm encoder that is not built
# yet; cast_swap reports which slots were skipped for that reason.


def actor_gcms(pkg: "ngc.NgcPackage") -> list[str]:
    """Return every ``models/actors/**.gcm`` name in the level's restable."""
    return [r.name for r in pkg.resources()
            if r.name.lower().startswith("models/actors/") and r.name.lower().endswith(".gcm")]


def skeleton_bone_hashes(gcm: bytes) -> set[int]:
    return {b["hash"] for b in ngc.skeleton(gcm)}


def compatible_donors(target_gcm: bytes, donor_gcms: dict[str, bytes]) -> list[str]:
    """Donor names whose bone hashes are a subset of the target's bone hashes."""
    tb = skeleton_bone_hashes(target_gcm)
    out = []
    for name, data in donor_gcms.items():
        try:
            db = skeleton_bone_hashes(data)
        except Exception:
            continue
        if db <= tb:
            out.append(name)
    return out


def random_cast_assignments(pkg: "ngc.NgcPackage", donor_names: list[str], seed: int | None = None,
                            filter_prefix: str = "models/actors/") -> dict[str, str]:
    """Randomly assign a donor to every actor .gcm that is compatible with it.

    If a target has no compatible donor, it is left unchanged (not in the
    returned dict).  With ``seed`` the randomization is reproducible."""
    import random
    rng = random.Random(seed)
    targets = actor_gcms(pkg)
    donor_gcms = {n: pkg.read(n) for n in donor_names if n.lower().startswith(filter_prefix.lower())}
    assignments = {}
    for t in targets:
        try:
            tg = pkg.read(t)
        except Exception:
            continue
        ok = compatible_donors(tg, donor_gcms)
        if ok:
            assignments[t] = rng.choice(ok)
    return assignments


def cast_swap(pkg: "ngc.NgcPackage", assignments: dict[str, str],
              progress=None) -> tuple[bytes, dict]:
    """Apply target->donor name assignments inside one level package.

    Returns the rebuilt package bytes and a report dict with ``assignments``
    (target->donor), ``skipped`` (targets with no compatible donor),
    ``unmapped`` (donor names that do not exist), and ``same`` (targets whose
    donor is identical to the original target)."""
    donor_gcms = {}
    unmapped = []
    for donor in set(assignments.values()):
        try:
            donor_gcms[donor] = pkg.read(donor)
        except Exception:
            unmapped.append(donor)
    pairs = []
    skipped = []
    same = []
    for target, donor in assignments.items():
        if donor in unmapped:
            continue
        if donor.lower() == target.lower():
            same.append(target)
            continue
        pairs.append((target, donor))
    if not pairs:
        data = write_package(pkg)
    else:
        data, info = swap_models(pkg, pairs)
    report = {"assignments": {t: d for t, d in assignments.items() if d not in unmapped and t not in same},
              "skipped": skipped, "unmapped": unmapped, "same": same, "pairs": pairs}
    return data, report

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AUF GC .ngc package writer")
    ap.add_argument("ngc")
    ap.add_argument("out")
    ap.add_argument("--replace", nargs=2, action="append", default=[], metavar=("NAME", "FILE"))
    ap.add_argument("--swap", nargs=2, metavar=("TARGET_GCM", "DONOR_GCM"))
    ap.add_argument("--rebuild", action="store_true", help="re-encode restable even with no change")
    ap.add_argument("--mod", metavar="NAME", help="NGC is the owned .gcz; OUT is the cache dir: build a disc mod")
    a = ap.parse_args(argv)
    if a.mod:
        print(json.dumps(build_mod(a.out, a.ngc, a.mod), indent=1, default=str))
        return 0
    pkg = ngc.NgcPackage(open(a.ngc, "rb").read())
    info = {}
    if a.swap:
        data, info = body_swap(pkg, *a.swap)
    elif a.replace:
        data = replace_resources(pkg, {n: open(f, "rb").read() for n, f in a.replace})
    elif a.rebuild:
        data = write_package(pkg, {"restable": build_restable(restable_entries(pkg.table))})
    else:
        data = write_package(pkg)
    with open(a.out, "wb") as fh:
        fh.write(data)
    info.update(check_package(data), sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    print(json.dumps(info, indent=1))
    return 1 if info["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
