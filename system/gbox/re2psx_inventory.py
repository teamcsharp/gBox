"""Resident Evil 2 Dual Shock Edition (PSX) source inventory.

Owned source: hyperspin CHD
`collections/Sony Playstation/roms/Resident Evil 2 - Dual Shock Edition (USA) (Disc 2).chd`
(game 2d8ef2bdbd4a58fd, the Claire disc). The catalog CHD is v5, which
``gbox.psxdisc.CHD`` cannot read, so extract with chdman first
(``chdman extractcd -i <chd> -o disc.cue -ob disc.bin``) and open the .bin
with ``gbox.psxdisc.RawBin`` (ISO9660 over MODE2/2352 sectors).

Layout on this disc: boot ``SLUS_007.56`` (SYSTEM.CNF), ``PL1/PLD/`` (player
models + weapon models), ``PL1/RDT/`` (rooms: backgrounds + enemy models),
``COMMON/`` (BSS/DO2 backgrounds, BGM, door/BIN data), ``PL1/ZMOVIE/`` (STR
movies), ``PL1/VOICE/`` (XAS audio).

Player data container (PLD and PLW share this layout; reference
implementation: OpenBiohazard2 fileio/pld.go):

* u32 dir_offset, u32 dir_count. The directory at dir_offset holds dir_count
  u32 **absolute** section offsets, in order: EDD (animation index), EMR
  (skeleton), MD1 (mesh), TIM (texture). Nothing in the container is
  compressed on the PSX build.
* MD1: u32 section_len, u32 unknown, u32 num_obj; ``num_obj // 2`` object
  headers of 56 bytes (triangle header of 7 u32, then quad header of 7 u32);
  every data offset inside is relative to the end of the 12-byte MD1 header.
  num_obj is twice the number of objects because each object contributes a
  triangle list and a quad list.
* EMR: u16 off_armatures, u16 off_frames, u16 count (bone count),
  u16 elem_size.
* EDD: first u16 pair is {count, offset}; ``offset // 4`` is the number of
  animation headers (4-byte {u16 count, u16 offset} each), followed by
  count 32-bit table elements per header: 12-bit frame id + 20-bit flag.

Character slots on the Claire disc (PL1/PLD), indexed by player id through the
executable's u16 table at 0x800a3fa0 (see :mod:`gbox.re2psx_exe`): PL00 Leon
(scenario B; even ids below 0x0C are Leon variants, 0x08/0x0A his locker
outfits), PL01 Claire (scenario A default, decoded TIM shows her jacket; odd ids
below 0x0C are Claire variants, 0x09 her locker outfit), PL0C Hunk, PL0D Tofu,
PL0E/PL0F the Ada/Sherry partner segments (the room setup saves/restores the main
character's state for ids 0x0E-0x0F), plus PL00CH/PL01CH/PL0BCH/PL0ECH Extreme
Battle select-screen variants. PLXXWNN.PLW files are weapon models (0x12 slots
per character). Enemy models live inside the RDT room archives; the two
CDEMD*.EMS files are cutscene enemy demos.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys

_MD1_OBJ_HEADER = struct.Struct("<7I7I")


def _u16(b: bytes, o: int) -> int:
    return struct.unpack_from("<H", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def parse_tim(data: bytes) -> dict:
    """PSX TIM header summary (header only; no pixel decode)."""
    if len(data) < 0x14:
        raise ValueError("TIM too short")
    magic = _u32(data, 0)
    if magic != 0x10:
        raise ValueError(f"not a TIM (magic 0x{magic:x})")
    bpp = _u32(data, 4) & 0xFF
    colors, cluts = _u16(data, 0x10), _u16(data, 0x12)
    w = h = 0
    if bpp in (8, 9):  # 4bpp / 8bpp: palette between header and image header
        img = 0x14 + colors * cluts * 2
        if len(data) >= img + 0x0C:
            w, h = _u16(data, img + 8), _u16(data, img + 10)
    mult = {8: 4, 9: 2}.get(bpp, 1)
    return {
        "bpp": bpp,
        "w": w * mult,
        "h": h,
        "cluts": cluts,
        "colors": colors,
        "size": len(data),
    }


def parse_md1(data: bytes) -> dict:
    """MD1 mesh section summary."""
    if len(data) < 12:
        raise ValueError("MD1 too short")
    num_obj = _u32(data, 8)
    pairs = num_obj // 2
    hdr_end = 12 + pairs * _MD1_OBJ_HEADER.size
    if hdr_end > len(data):
        raise ValueError("MD1 object headers overrun section")
    vtx = nrm = tri = quad = 0
    tri_tex = quad_tex = 0
    for i in range(pairs):
        f = _MD1_OBJ_HEADER.unpack_from(data, 12 + i * _MD1_OBJ_HEADER.size)
        vtx += f[1] + f[8]
        nrm += f[3] + f[10]
        tri += f[5]
        quad += f[12]
        tri_tex += 1 if f[5] else 0
        quad_tex += 1 if f[12] else 0
    return {
        "num_obj": num_obj,
        "objects": pairs,
        "verts": vtx,
        "normals": nrm,
        "triangles": tri,
        "quads": quad,
        "tri_textures": tri_tex,
        "quad_textures": quad_tex,
        "size": len(data),
    }


def parse_emr(data: bytes) -> dict:
    """EMR skeleton section summary."""
    if len(data) < 8:
        raise ValueError("EMR too short")
    off_arm, off_frames, count, elem = (
        _u16(data, 0), _u16(data, 2), _u16(data, 4), _u16(data, 6)
    )
    return {
        "bones": count,
        "elem_size": elem,
        "off_armatures": off_arm,
        "off_frames": off_frames,
        "size": len(data),
    }


def parse_edd(data: bytes) -> dict:
    """EDD animation index summary.

    N headers of {u16 count, u16 offset} at the start (N = first offset / 4);
    the tables follow the header block contiguously as 32-bit entries of
    12-bit frame id + 20-bit flag (reference: OpenBiohazard2 edd.go).
    """
    if len(data) < 4:
        raise ValueError("EDD too short")
    first_count, first_off = _u16(data, 0), _u16(data, 2)
    n_anims = first_off // 4
    counts = [_u16(data, 4 * i) for i in range(n_anims)]
    total = sum(counts)
    if 4 * n_anims + 4 * total > len(data):
        raise ValueError("EDD tables overrun section")
    max_frame = 0
    base = 4 * n_anims
    for i in range(total):
        v = _u32(data, base + 4 * i)
        max_frame = max(max_frame, v & 0xFFF)
    return {
        "animations": n_anims,
        "first_count": first_count,
        "table_entries": total,
        "max_frame": max_frame,
        "size": len(data),
    }


def read_pld(data: bytes) -> dict:
    """Split a PLD/PLW container into its four sections and summarize them."""
    if len(data) < 8:
        raise ValueError("PLD too short")
    dir_off, count = _u32(data, 0), _u32(data, 4)
    if dir_off + 4 * count > len(data):
        raise ValueError("PLD directory overruns file")
    offs = [_u32(data, dir_off + 4 * i) for i in range(count)]
    out = {"sections": offs}
    for name, (a, b) in zip(("edd", "emr", "md1", "tim"), zip(offs, offs[1:] + [len(data)])):
        sec = data[a:b]
        try:
            out[name] = {
                "edd": parse_edd, "emr": parse_emr,
                "md1": parse_md1, "tim": parse_tim,
            }[name](sec)
        except (ValueError, struct.error) as e:
            out[name] = {"error": str(e), "size": len(sec)}
    return out


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inventory(bin_path: str, parse_models: bool = True) -> dict:
    """Walk the disc image and build the source manifest.

    Returns the manifest; use ``python -m gbox.re2psx_inventory`` to write it.
    """
    from gbox.psxdisc import RawBin

    rb = RawBin(bin_path, writable=False)
    try:
        cnf = rb.read("SYSTEM.CNF").decode("latin-1")
        boot = [ln.split("=", 1)[1].strip().replace("\\", "/").split("/")[-1].split(";")[0]
                for ln in cnf.splitlines() if ln.upper().startswith("BOOT")]
        boot = boot[0] if boot else None
    except KeyError:
        boot = None
    files = {
        "count": len(rb.files),
        "boot": boot,
        "boot_sha256": _sha256(rb.read(boot)) if boot else None,
        "entries": [
            {"name": k, "lba": v[0], "size": v[1]} for k, v in sorted(rb.files.items())
        ],
    }
    out: dict[str, object] = {
        "game_id": "2d8ef2bdbd4a58fd",
        "title": "Resident Evil 2 - Dual Shock Edition (Disc 2, Claire, PSX)",
        "bin": bin_path,
        "iso9660": files,
    }
    plds, plws, emss, tims = [], [], [], []
    for name, (lba, size) in rb.files.items():
        up = name.upper()
        if not (up.endswith(".PLD") or up.endswith(".PLW") or up.endswith(".EMS")
                or up.endswith(".TIM")):
            continue
        data = rb.read(name)
        rec = {"name": name, "size": size, "sha256": _sha256(data)}
        try:
            rec["parsed"] = read_pld(data)
        except ValueError as e:
            rec["error"] = str(e)
        if up.endswith(".PLD"):
            plds.append(rec)
        elif up.endswith(".PLW"):
            plws.append(rec)
        elif up.endswith(".EMS"):
            emss.append(rec)
        else:
            try:
                rec["tim"] = parse_tim(data)
            except ValueError as e:
                rec["error"] = str(e)
            tims.append(rec)
    out["pld"] = plds
    out["plw"] = plws
    out["ems"] = emss
    out["tim"] = tims
    out["counts"] = {
        "pld": len(plds), "plw": len(plws), "ems": len(emss), "tim": len(tims),
        "rdt": sum(1 for n in rb.files if n.upper().endswith(".RDT")),
        "bss": sum(1 for n in rb.files if n.upper().endswith(".BSS")),
        "do2": sum(1 for n in rb.files if n.upper().endswith(".DO2")),
        "str": sum(1 for n in rb.files if n.upper().endswith(".STR")),
    }
    return out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 1:
        print("usage: python -m gbox.re2psx_inventory DISC.BIN [--out manifest.json]",
              file=sys.stderr)
        return 2
    out_path = None
    if "--out" in args:
        i = args.index("--out")
        out_path = args[i + 1]
        del args[i:i + 2]
    man = inventory(args[0])
    text = json.dumps(man, indent=1, default=str)
    if out_path:
        with open(out_path, "w") as f:
            f.write(text)
        print(f"manifest -> {out_path}")
    print(f"files {man['iso9660']['count']} boot {man['iso9660']['boot']} "
          f"pld {man['counts']['pld']} plw {man['counts']['plw']} "
          f"ems {man['counts']['ems']} rdt {man['counts']['rdt']} "
          f"bss {man['counts']['bss']}")
    for p in man["pld"][:3]:
        m = p.get("parsed", {}).get("md1", {})
        e = p.get("parsed", {}).get("emr", {})
        t = p.get("parsed", {}).get("tim", {})
        print(f"  {p['name']}: md1 {m.get('objects')} obj {m.get('verts')}v "
              f"{m.get('triangles')}t {m.get('quads')}q | emr {e.get('bones')} bones "
              f"| tim {t.get('w')}x{t.get('h')} {t.get('bpp')}bpp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
