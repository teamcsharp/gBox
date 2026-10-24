"""True Crime: New York City (USA) (GameCube) - authoritative owned-build manifest.

Owned source (catalog game_id 1e10f1cdd0e80d6e, platform gamecube, core dolphin):
  <hyperspin>/collections/Nintendo GameCube/roms/True Crime - New York City (USA).gcz
  a Dolphin GCZ disc image (1,209,485,350 bytes), disc id G2CE52 / title "TC2 US".

`read_manifest` reports, for ONE owned build:
  * the container geometry and the sha256 of the container bytes,
  * the disc header (game id, title, DOL offset, FST offset/size),
  * the full FST file table (path, offset, size),
  * the identified native target executable: the FST entry that carries the
    header's DOL offset, hashed from the bytes actually read out of the image,
  * filename extension counts and the first 16 bytes of selected asset files.

Filename extension counts are explicitly NOT format proof - only opening a file
says what a ".g" or ".dat" holds.  The image is opened read-only; no original,
save or library file is ever modified.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from .gcz import GCZ
from .formats.gcfst import disc_header, parse_fst

MAX_FILES = 20000
DEFAULT_PROBE_EXTS = (".g", ".ngc", ".dat", ".gci", ".cib", ".exm", ".sdb", ".gcs")
PROBE_BYTES = 16


def sha256_file(path, chunk: int = 32 << 20) -> str:
    """sha256 of a file, streamed (the disc is 1.2 GB; never load it whole)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(chunk), b""):
            h.update(c)
    return h.hexdigest()


def extension_of(path: str) -> str:
    """Lower-case extension of a path, or "" when there is none."""
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def dol_info(img, dol_offset: int) -> dict:
    """Parse the DOL header at the disc-header DOL offset (the DOL is not an FST file)."""
    h = img.read(dol_offset, 0x100)
    offs = struct.unpack(">18I", h[0:72])
    sizes = struct.unpack(">18I", h[0x90:0x90 + 72])
    size = max((o + s for o, s in zip(offs, sizes) if s), default=0)
    blob = img.read(dol_offset, size)
    return {"offset": dol_offset, "size": size,
            "entry": struct.unpack(">I", h[0xE0:0xE4])[0],
            "sha256": hashlib.sha256(blob).hexdigest()}


def _rows(entries):
    """Normalise parse_fst output to (path, offset, size) triples."""
    out = []
    for e in entries:
        out.append((e[0], e[1], e[2]))
    return out


def read_manifest(gcz_path: str, max_files: int = MAX_FILES,
                  source_sha256: str = "",
                  probe_exts=DEFAULT_PROBE_EXTS, probe_limit: int = 30) -> dict:
    """Authoritative manifest of one owned GCZ build (read-only).

    `source_sha256` may carry an already-streamed container hash so the 1.2 GB
    image is not re-read just to repeat the same digest; the manifest then
    records that the digest was supplied rather than recomputed.
    """
    gcz_path = str(gcz_path)
    with GCZ(gcz_path) as img:
        header = img.read(0, 0x440)
        d = disc_header(header)
        fst = img.read(d["fst_offset"], d["fst_size"])
        rows = _rows(parse_fst(fst, d["fst_offset"]))
        files = [{"path": p, "offset": o, "size": s} for (p, o, s) in rows[:max_files]]
        counts = {}
        for f in files:
            e = extension_of(f["path"])
            counts[e] = counts.get(e, 0) + 1

        # the identified native target: the FST entry carrying the header DOL offset
        target = next((f for f in files if f["offset"] == d["dol_offset"]), None)
        match = "exact_offset"
        if target is None:
            target = next((f for f in files
                           if f["offset"] <= d["dol_offset"] < f["offset"] + f["size"]), None)
            match = "contains_offset"
        main_exec = None
        if target is not None:
            blob = img.read(target["offset"], target["size"])
            main_exec = {
                "path": target["path"], "offset": target["offset"], "size": target["size"],
                "sha256": hashlib.sha256(blob).hexdigest(),
                "head_hex": blob[:PROBE_BYTES].hex(),
                "match": match,
                "header_dol_offset": d["dol_offset"],
                "header_dol_matches_fst": target["offset"] == d["dol_offset"],
            }

        dol = dol_info(img, d["dol_offset"])
        exts = tuple(x.lower() for x in (probe_exts or ()))
        probes = []
        if exts:
            for f in [x for x in files if x["path"].lower().endswith(exts)][:probe_limit]:
                try:
                    head = img.read(f["offset"], PROBE_BYTES)
                except Exception as exc:            # bounded probe, never fatal
                    head = b""
                    print("probe failed", f["path"], exc)
                probes.append({"path": f["path"], "offset": f["offset"], "size": f["size"],
                               "head_hex": head.hex()})
        container = {"format": "gcz", "data_size": img.data_size,
                     "block_size": img.block_size, "num_blocks": img.num_blocks,
                     "sub_type": img.sub_type}

    if source_sha256:
        src_sha, src_method = source_sha256, "supplied (streamed in this session)"
    else:
        src_sha, src_method = sha256_file(gcz_path), "streamed by read_manifest"
    return {
        "game_id": "1e10f1cdd0e80d6e",
        "title": "True Crime - New York City (USA)",
        "platform": "gamecube",
        "source": {"path": gcz_path, "size": Path(gcz_path).stat().st_size,
                   "sha256": src_sha, "sha256_method": src_method},
        "container": container,
        "disc": d,
        "file_count": len(rows),
        "files": files,
        "filename_extension_counts": counts,
        "native_target_executable": main_exec,
        "boot_dol": dol,
        "probed_files": probes,
        "notes": [
            "extension counts are filename-derived, not format-verified",
            "probed_files carry only the first 16 bytes of each file",
            "the owned image is opened read-only; no original is modified",
        ],
    }


def write_manifest(manifest: dict, out_path: str) -> str:
    """Write the manifest as JSON; returns the sha256 of the written file."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(p.read_bytes()).hexdigest()
