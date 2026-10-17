"""Inventory of the owned Metal Gear Solid: VR Missions (PS1, USA) build (#1637, favorite afd2fc507bb69843).

Owned source: the QuickSwap archive ``Metal Gear Solid - VR Missions (USA).7z`` (library ``quickswap-root``) with one
CUE and one MODE2/2352 BIN (Redump single track, 492,487,632 bytes).  ``mgs_vr_swap.base_bin(cfg)`` unpacks it once to
``<cache>/modbase/mgs_vr_us/``; this module only reads that image (``psxdisc.RawBin(writable=False)``).

Boot and container chain, all checked against the files by :func:`inventory`:

* ``SYSTEM.CNF`` ``BOOT = cdrom:\\SLUS_009.57;1`` -> ``SLUS_009.57`` (PS-X EXE, the MGS1 GV/GM/GCL engine);
* ``MGS/STAGE.DIR``: ``u32`` header size, then ``{char name[8], u32 sector}`` per stage (``mgs_vr_swap.stage_dir``);
* each stage is a ``.stg`` of streamed and cached entries ``{u16 GV_StrCode hash, u8 mode, u8 ext, u32 size}``
  (``mgs_vr_swap.stage_files``); a DAR entry (ext ``d``) holds flat ``{u16 hash, u8 ext, u8 0, u32 size}`` members
  (``mgs_vr_swap.dar_entries``);
* models are KMD (ext ``k``, ``gbox.mgs_kmd``), motions OAR (``o``), textures PCC (``p``, ``gbox.mgs_pcc``).

The character inventory is every distinct KMD with 16 objects and Snake's object tree (``mgs_vr_swap.TREE``): the
figures the motion bones drive and the writer's slots (``mgs_vr_swap.SLOTS``) address.  :func:`check_build` compares a
manifest with the exact build the existing reader and writer were developed on (:data:`EXPECTED`), so a different
dump, a modded image (``bighead.bin``) or another region fails loudly instead of being treated as the same title.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path

from . import mgs_kmd, mgs_vr_swap, mgs_vr_tool, psxdisc

GAME_ID = "afd2fc507bb69843"
SERIAL = "SLUS-00957"
EXPECTED = {
    "disc_bytes": mgs_vr_swap.DISC_BYTES,
    "boot": "cdrom:\\SLUS_009.57;1",
    "exe": "SLUS_009.57",
    "exe_sha256": "8e8e59a97b5cc7cec137dd782fdeaa09097de1e53b1801c5617aa9132a2fb814",
    "exe_bytes": 643072,
    "stage_dir_sha256": "43dc302a4738e06d86f91ab2a850fe540b205ee3ed3b7133865524bbbf6119f8",
    "stage_dir_bytes": 72593408,
    "stages": 105,
    "player_model": mgs_vr_swap.PLAYER_MODEL,
    "player_kmd_sha256_prefix": "5dda0c64",
}
# The ext byte is the first letter of the file extension; the names below are the ones docs/mgs_vr_decomp.md names.
EXT = {"b": "bin (stage overlay)", "c": "con", "d": "dar (archive)", "e": "efx", "g": "gcx (GCL script)",
       "h": "hzm (hit zones)", "k": "kmd (model)", "l": "lit", "m": "mt3", "o": "oar (motion)", "p": "pcc (texture)",
       "w": "wvx"}
SLOT_OF = {m: slot for slot, row in mgs_vr_swap.SLOTS.items() for m in row["models"]}


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------- source and boot
def parse_7z_listing(text: str) -> list[dict]:
    """``7z l -slt ARCHIVE`` output -> [{path, size, crc32}] of the archive's file members (folders skipped)."""
    blocks, cur, started = [], {}, False
    for line in text.splitlines():
        if line.startswith("----------"):
            started = True
            continue
        if not started:
            continue
        if not line.strip():
            if cur:
                blocks.append(cur)
            cur = {}
            continue
        key, sep, val = line.partition(" = ")
        if sep:
            cur[key.strip()] = val.strip()
    if cur:
        blocks.append(cur)
    return [{"path": b["Path"], "size": int(b.get("Size") or 0), "crc32": (b.get("CRC") or "").lower() or None}
            for b in blocks if "Path" in b and b.get("Folder", "-") != "+"]


def parse_cue(text: str) -> list[dict]:
    """CUE sheet -> [{file, type, tracks: [{number, mode, indexes: {n: 'mm:ss:ff'}}]}]."""
    out = []
    for line in text.splitlines():
        words = line.strip()
        m = re.match(r'FILE\s+"(.+)"\s+(\S+)', words, re.I)
        if m:
            out.append({"file": m.group(1), "type": m.group(2).upper(), "tracks": []})
            continue
        m = re.match(r"TRACK\s+(\d+)\s+(\S+)", words, re.I)
        if m and out:
            out[-1]["tracks"].append({"number": int(m.group(1)), "mode": m.group(2).upper(), "indexes": {}})
            continue
        m = re.match(r"INDEX\s+(\d+)\s+(\d+:\d+:\d+)", words, re.I)
        if m and out and out[-1]["tracks"]:
            out[-1]["tracks"][-1]["indexes"][int(m.group(1))] = m.group(2)
    return out


def parse_system_cnf(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        key, sep, val = line.partition("=")
        if sep and key.strip():
            out[key.strip().upper()] = val.strip()
    return out


def boot_name(cnf: dict) -> str | None:
    """``cdrom:\\SLUS_009.57;1`` -> ``SLUS_009.57`` (ISO path, version suffix dropped)."""
    m = re.match(r"cdrom0?:\\*(.+?)(?:;\d+)?$", cnf.get("BOOT", ""), re.I)
    return m.group(1).replace("\\", "/") if m else None


def exe_header(b: bytes) -> dict:
    """PS-X EXE header: entry pc0, gp0, text address/size, stack and the licence region string."""
    if b[:8] != b"PS-X EXE":
        return {"magic": None, "size": len(b)}
    pc0, gp0, t_addr, t_size = struct.unpack_from("<4I", b, 0x10)
    stack = struct.unpack_from("<I", b, 0x30)[0]
    region = b[0x4C:0x800].split(b"\0")[0].decode("latin-1").strip()      # licence string, up to the text
    return {"magic": "PS-X EXE", "pc0": pc0, "gp0": gp0, "t_addr": t_addr, "t_size": t_size, "stack": stack,
            "region": region, "size": len(b), "fits": 0x800 + t_size <= len(b)}


# ---------------------------------------------------------------------------------------------- stage contents
def stage_entries(data: bytes, off: int) -> tuple[list[dict], int]:
    """Every file of the stage at *off* in STAGE.DIR, DAR members expanded -> (entries, DARs that did not parse).

    An entry is {hash, ext, offset, size, cached, dar}: dar is None for a stage file and the stage-file index of
    the DAR for a member."""
    out, bad = [], 0
    for f in mgs_vr_swap.stage_files(data, off):
        out.append({"hash": f["hash"], "ext": f["ext"], "offset": f["offset"], "size": f["size"],
                    "cached": f["cached"], "dar": None})
        if f["ext"] != "d" or not f["size"]:
            continue
        try:
            members = mgs_vr_swap.dar_entries(data, f["offset"], f["size"])
        except ValueError:
            bad += 1
            continue
        out += [{"hash": e["hash"], "ext": e["ext"], "offset": e["offset"], "size": e["size"], "cached": f["cached"],
                 "dar": f["index"]} for e in members]
    return out, bad


def kmd_summary(b: bytes) -> dict:
    """Object count, parents, faces, vertices and texture names of a KMD; figure = Snake's 16-object tree."""
    model = mgs_kmd.loads(b)
    parents = [o.parent for o in model.objects]
    return {"bones": model.bones, "objects": len(model.objects), "parents": parents,
            "faces": sum(len(o.faces) for o in model.objects),
            "vertices": sum(len(o.vertices) for o in model.objects),
            "textures": sorted({t for o in model.objects for t in o.textures}),
            "figure": len(model.objects) == 16 and parents == list(mgs_vr_swap.TREE)}


def stage_inventory(data: bytes) -> dict:
    """STAGE.DIR -> stages (name, family, offset, entry counts by ext), character figures, other models, motions,
    textures.  Figures and models are keyed by (GV hash, sha256); every site lists the stages that hold that copy."""
    stages, figures, models, motions = [], {}, {}, {}
    ext_total, pcc_total, bad_total = Counter(), 0, 0
    for name, off in sorted(mgs_vr_swap.stage_dir(data).items(), key=lambda kv: kv[1]):
        ents, bad = stage_entries(data, off)
        bad_total += bad
        by_ext = Counter(e["ext"] for e in ents)
        ext_total.update(by_ext)
        pcc_total += by_ext.get("p", 0)
        stages.append({"name": name, "family": mgs_vr_tool.family(name), "offset": off, "sector": off // 2048,
                       "entries": len(ents), "by_ext": dict(sorted(by_ext.items())), "bad_dars": bad})
        for e in ents:
            if not e["size"] or e["ext"] not in ("k", "o"):
                continue
            blob = data[e["offset"]:e["offset"] + e["size"]]
            key = (e["hash"], sha256(blob))
            if e["ext"] == "o":
                row = motions.setdefault(key, {"hash": e["hash"], "sha256": key[1], "bytes": e["size"], "stages": []})
                row["stages"].append(name)
                continue
            try:
                summ = kmd_summary(blob)
            except Exception as exc:                      # a KMD the reader rejects is reported, not skipped silently
                summ = {"error": f"{type(exc).__name__}: {exc}", "figure": False}
            table = figures if summ.get("figure") else models
            row = table.setdefault(key, {"model": e["hash"], "sha256": key[1], "bytes": e["size"],
                                         "slot": SLOT_OF.get(e["hash"]), "sites": [],
                                         **{k: v for k, v in summ.items() if k not in ("parents", "figure")}})
            row["sites"].append({"stage": name, "in_dar": e["dar"] is not None, "cached": e["cached"]})
    for table in (figures, models, motions):
        for row in table.values():
            where = row.get("sites") or row.get("stages")
            row["stage_count"] = len({s["stage"] if isinstance(s, dict) else s for s in where})
    order = lambda t: sorted(t.values(), key=lambda r: (-r["stage_count"], r.get("model", r.get("hash")), r["sha256"]))
    families = Counter(s["family"] for s in stages)
    return {"stages": stages, "families": dict(sorted(families.items())), "ext_counts": dict(sorted(ext_total.items())),
            "ext_names": {k: EXT.get(k, "unnamed") for k in sorted(ext_total)}, "pcc_total": pcc_total,
            "bad_dars": bad_total, "figures": order(figures), "models": order(models), "motions": order(motions)}


# ------------------------------------------------------------------------------------------------ the manifest
def _iso_key(files: dict, want: str) -> str | None:
    want = want.upper()
    return next((k for k in files if k.upper().split(";")[0] == want), None)


def inventory(image, *, archive: str | None = None, archive_sha256: str | None = None, listing: str | None = None,
              cue_text: str | None = None, game: dict | None = None) -> dict:
    """The exact-build manifest of an owned VR Missions image (read only)."""
    image = Path(image)
    disc = psxdisc.RawBin(image, writable=False)
    try:
        cnf_key = _iso_key(disc.files, "SYSTEM.CNF")
        cnf_text = disc.read(cnf_key).decode("latin-1") if cnf_key else ""
        cnf = parse_system_cnf(cnf_text)
        boot = boot_name(cnf)
        exe_key = _iso_key(disc.files, boot or EXPECTED["exe"])
        exe = disc.read(exe_key) if exe_key else b""
        sd_key = _iso_key(disc.files, "MGS/STAGE.DIR")
        sd = disc.read(sd_key) if sd_key else b""
        iso = [{"name": k, "lba": v[0], "size": v[1]} for k, v in sorted(disc.files.items(), key=lambda kv: kv[1][0])]
    finally:
        disc.f.close()
    st = stage_inventory(sd) if sd else {}
    player = next((r for r in st.get("figures", []) if r["model"] == EXPECTED["player_model"]
                   and any(s["stage"] == "init" for s in r["sites"])), None)
    launch = dict((game or {}).get("launch") or {})
    manifest = {
        "game_id": (game or {}).get("game_id", GAME_ID), "title": (game or {}).get("title"),
        "catalog_platform": (game or {}).get("platform"), "serial": SERIAL,
        "source": {"archive": archive, "sha256": archive_sha256,
                   "members": parse_7z_listing(listing) if listing else None},
        "image": {"path": str(image), "bytes": image.stat().st_size, "sha256": file_sha256(image),
                  "cue": parse_cue(cue_text) if cue_text else None},
        "launch": {"core": (game or {}).get("core"), "runtimes": (game or {}).get("runtimes"),
                   "archive_member": launch.get("archive_member"), "kind": launch.get("kind"),
                   "prerequisites": ["7-Zip unpack of the owned .7z to <cache>/modbase/mgs_vr_us (base_bin)",
                                     "RetroArch pcsx_rearmed (catalog auto-install); PS1 BIOS per [retroarch_bios]"]},
        "system_cnf": cnf, "boot": boot,
        "executable": {"name": exe_key, "lba": disc.files.get(exe_key, (None,))[0] if exe_key else None,
                       "bytes": len(exe), "sha256": sha256(exe) if exe else None, "header": exe_header(exe)},
        "stage_dir": {"name": sd_key, "bytes": len(sd), "sha256": sha256(sd) if sd else None,
                      "header_bytes": struct.unpack_from("<I", sd, 0)[0] if sd else None},
        "iso_files": iso,
        "player": player and {"model": player["model"], "sha256": player["sha256"], "bytes": player["bytes"],
                              "objects": player["objects"], "faces": player["faces"], "textures": len(player["textures"])},
        **st,
    }
    manifest["platform_check"] = {
        "psx": bool(exe[:8] == b"PS-X EXE" and boot and cnf.get("BOOT", "").lower().startswith("cdrom")),
        "region": manifest["executable"]["header"].get("region"),
        "catalog_label_ok": (game or {}).get("platform") in (None, "psx")}
    manifest["build_check"] = check_build(manifest)
    return manifest


def check_build(m: dict) -> list[str]:
    """Differences between a manifest and the exact build of EXPECTED ([] = the same owned build)."""
    bad = []
    if m["image"]["bytes"] != EXPECTED["disc_bytes"]:
        bad.append(f"image is {m['image']['bytes']} bytes, not {EXPECTED['disc_bytes']}")
    if m["system_cnf"].get("BOOT") != EXPECTED["boot"]:
        bad.append(f"BOOT {m['system_cnf'].get('BOOT')!r} != {EXPECTED['boot']!r}")
    exe = m["executable"]
    if exe["sha256"] != EXPECTED["exe_sha256"] or exe["bytes"] != EXPECTED["exe_bytes"]:
        bad.append(f"executable {exe['name']} {exe['bytes']} B sha256 {exe['sha256']} is not the US SLUS_009.57")
    sd = m["stage_dir"]
    if sd["sha256"] != EXPECTED["stage_dir_sha256"] or sd["bytes"] != EXPECTED["stage_dir_bytes"]:
        bad.append(f"STAGE.DIR {sd['bytes']} B sha256 {sd['sha256']} differs (modded or other build)")
    if len(m.get("stages", [])) != EXPECTED["stages"]:
        bad.append(f"{len(m.get('stages', []))} stages, not {EXPECTED['stages']}")
    if not m.get("player") or not m["player"]["sha256"].startswith(EXPECTED["player_kmd_sha256_prefix"]):
        bad.append("init.stg player KMD 39213 is missing or not the stock Snake")
    if m.get("bad_dars"):
        bad.append(f"{m['bad_dars']} DAR entries did not parse")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("image", help="unpacked MODE2/2352 .bin (mgs_vr_swap.base_bin)")
    ap.add_argument("--archive")
    ap.add_argument("--archive-sha256")
    ap.add_argument("--listing", help="file with `7z l -slt` output of the archive")
    ap.add_argument("--catalog-json", help="file with the game's catalog body")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    cue = Path(a.image).with_suffix(".cue")
    m = inventory(a.image, archive=a.archive, archive_sha256=a.archive_sha256,
                  listing=Path(a.listing).read_text() if a.listing else None,
                  cue_text=cue.read_text(errors="replace") if cue.is_file() else None,
                  game=json.loads(Path(a.catalog_json).read_text()) if a.catalog_json else None)
    text = json.dumps(m, indent=1, sort_keys=False)
    if a.out:
        Path(a.out).write_text(text)
    print(json.dumps({"build_check": m["build_check"], "stages": len(m.get("stages", [])),
                      "figures": len(m.get("figures", [])), "models": len(m.get("models", [])),
                      "motions": len(m.get("motions", [])), "pcc_total": m.get("pcc_total")}, indent=1))
    return 0 if not m["build_check"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
