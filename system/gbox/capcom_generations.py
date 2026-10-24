"""Capcom Generations (Europe) (Disc 1) (PS1) - owned-build source inventory.

Owned source: hyperspin CHD
`collections/Sony Playstation/roms/Capcom Generations (Europe) (Disc 1).chd`
(game_id 5a67d462464d2460), SHA-256
6159ec05950ee85bc202250bdec5b4f251fe23ecd01ac4d9e6a89165b9d14aa5.

Facts in this module are observed from the owned disc image (ISO9660 over raw
2352-byte MODE2/2352 sectors) or come from the gBox assimilation fingerprint of
that exact file (job f8b32583cc3f4d3e: engine Yuke's 0.689, 89 files, boot
executable SLES_018.81, texture format PS1 TIM).  The PS-X EXE header layout is
the published Sony format, not an inference from this parser.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys

from .formats import iso9660 as _iso

OWNED_GAME_ID = "5a67d462464d2460"
OWNED_TITLE = "Capcom Generations (Europe) (Disc 1)"
OWNED_PLATFORM = "psx"
OWNED_SOURCE_PATH = ("/mnt/gbox/hyperspin/Arcade/collections/Sony Playstation/"
                      "roms/Capcom Generations (Europe) (Disc 1).chd")
OWNED_SOURCE_SHA256 = "6159ec05950ee85bc202250bdec5b4f251fe23ecd01ac4d9e6a89165b9d14aa5"
OWNED_ENGINE = "yukes"
OWNED_ENGINE_LABEL = "Yuke's"
OWNED_ENGINE_CONFIDENCE = 0.689
OWNED_BOOT_EXECUTABLE = "SLES_018.81"
OWNED_CONTAINER = "iso9660"
RAW_SECTOR = 2352
LOGICAL_SECTOR = 2048
PSX_EXE_HEADER_SIZE = 0x800
MAX_DEPTH = 8


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_psx_exe(data: bytes) -> dict:
    """Parse a PS-X EXE header (published Sony format).

    Field offsets are the published ones, identical to gbox.re2psx_exe and
    gbox.sd2_inventory: 0x00 magic, 0x10 the ten header words (pc0, gp0,
    t_addr, t_size, d_addr, d_size, b_addr, b_size, sp, stack_size), 0x38 the
    five saved registers (sp, fp, gp, ret, dest) and 0x4C the region string.
    """
    if len(data) < PSX_EXE_HEADER_SIZE:
        raise ValueError("PS-X EXE shorter than a 0x800 header")
    if data[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE (magic %r)" % (data[:8],))
    (pc0, gp0, t_addr, t_size, d_addr, d_size, b_addr, b_size, sp,
     stack_size) = struct.unpack_from("<10I", data, 0x10)
    saved_sp, saved_fp, saved_gp, ret, dest = struct.unpack_from("<5I", data, 0x38)
    region = data[0x4C:0x800].split(b"\0", 1)[0].decode("latin-1")
    if t_size > len(data) - PSX_EXE_HEADER_SIZE:
        raise ValueError("t_size 0x%x exceeds the %d-byte payload" %
                         (t_size, len(data) - PSX_EXE_HEADER_SIZE))
    out = {
        "magic": "PS-X EXE",
        "pc0": pc0, "gp0": gp0,
        "t_addr": t_addr, "t_size": t_size,
        "d_addr": d_addr, "d_size": d_size,
        "b_addr": b_addr, "b_size": b_size,
        "sp": sp, "stack_size": stack_size,
        "s_addr": sp, "s_size": stack_size,
        "saved_sp": saved_sp, "saved_fp": saved_fp, "saved_gp": saved_gp,
        "ret": ret, "dest": dest,
        "region": region,
    }
    out["payload_size"] = len(data) - PSX_EXE_HEADER_SIZE
    out["size"] = len(data)
    out["sha256"] = sha256_bytes(data)
    return out


class Iso9660:
    """ISO9660 reader over a raw 2352-byte (MODE1/MODE2) or cooked 2048-byte image.

    Directory records are parsed by the shared `gbox.formats.iso9660` module, so the
    layout (flags at +25, name length at +32, name at +33) is the same one every
    other disc reader in gBox uses.  Sector decoding follows the PS1 convention:
    MODE2 Form 1/2 sectors carry the user data at offset 24, MODE1 sectors at 16.
    """

    def __init__(self, path: str):
        self.path = path
        self.fh = open(path, "rb")
        self.raw = RAW_SECTOR
        self.raw_header = 24
        self._detect()

    def _detect(self) -> None:
        """Pick the sector layout: raw 2352 bytes/user data at 16 (MODE1) or 24 (MODE2),
        or a cooked 2048-byte image (user data at 0)."""
        for raw in (RAW_SECTOR, LOGICAL_SECTOR):
            self.fh.seek(16 * raw)
            s = self.fh.read(raw)
            if len(s) < raw:
                continue
            for head in (24, 16, 0):
                if s[head + 1:head + 6] == b"CD001":
                    self.raw, self.raw_header = raw, head
                    return
        raise ValueError("no ISO9660 primary volume descriptor found")

    def data(self, lba: int) -> bytes:
        """The 2048 user bytes of one sector."""
        self.fh.seek(lba * self.raw)
        s = self.fh.read(self.raw)
        if self.raw == LOGICAL_SECTOR:
            return s[:LOGICAL_SECTOR]
        mode = s[15] if len(s) > 15 else 0
        if mode == 2:
            return s[24:24 + LOGICAL_SECTOR]
        if mode == 1:
            return s[16:16 + LOGICAL_SECTOR]
        return s[self.raw_header:self.raw_header + LOGICAL_SECTOR]

    def _extent(self, lba: int, size: int) -> bytes:
        n = (size + LOGICAL_SECTOR - 1) // LOGICAL_SECTOR
        return b"".join(self.data(lba + i) for i in range(n))[:size]

    def root(self) -> list:
        """The root directory's entries: {'name', 'lba', 'size', 'is_dir'}."""
        pvd = self.data(16)
        if pvd[0] != 1 or pvd[1:6] != b"CD001":
            raise ValueError("bad primary volume descriptor")
        root_lba, root_size = struct.unpack_from("<I", pvd, 158)[0], struct.unpack_from("<I", pvd, 166)[0]
        return self.entries(root_lba, root_size)

    def entries(self, lba: int, size: int) -> list:
        """The direct children of one directory extent ('.' and '..' excluded, ';1' stripped)."""
        out = []
        for rec in _iso.records(self._extent(lba, size)):
            out.append({"name": rec.name, "lba": rec.lba, "size": rec.size, "is_dir": rec.is_dir})
        return out

    def read(self, entry: dict) -> bytes:
        return self._extent(entry["lba"], entry["size"])

    def close(self) -> None:
        if not self.fh.closed:
            self.fh.close()


def _walk_dir(iso: "Iso9660", entries: list, prefix: str, depth: int) -> list:
    out = []
    if depth > MAX_DEPTH:
        return out
    for e in entries:
        name = prefix + e["name"]
        if e["is_dir"]:
            sub = iso.entries(e["lba"], e["size"])
            out.extend(_walk_dir(iso, sub, name + "/", depth + 1))
        else:
            out.append({"name": name, "lba": e["lba"], "size": e["size"], "is_dir": False})
    return out


def build_manifest(bin_path: str, hash_files: bool = True) -> dict:
    """Walk the owned disc image and build the authoritative source manifest."""
    iso = Iso9660(bin_path)
    try:
        files = _walk_dir(iso, iso.root(), "", 0)
        manifest = {
            "game_id": OWNED_GAME_ID,
            "title": OWNED_TITLE,
            "platform": OWNED_PLATFORM,
            "container": OWNED_CONTAINER,
            "engine": OWNED_ENGINE_LABEL,
            "engine_confidence": OWNED_ENGINE_CONFIDENCE,
            "source_path": OWNED_SOURCE_PATH,
            "source_sha256": OWNED_SOURCE_SHA256,
            "bin_path": bin_path,
            "bin_size": os.path.getsize(bin_path),
            "raw_sector": iso.raw,
            "file_count": len(files),
            "extensions": {},
            "files": [],
        }
        for e in sorted(files, key=lambda x: x["name"]):
            ext = os.path.splitext(e["name"])[1].lower()
            manifest["extensions"][ext] = manifest["extensions"].get(ext, 0) + 1
            rec = {"name": e["name"], "size": e["size"], "lba": e["lba"]}
            data = None
            try:
                data = iso.read(e)
            except Exception as exc:  # truncated image
                rec["read_error"] = str(exc)
            if data is not None:
                if len(data) < e["size"]:
                    rec["truncated"] = True
                if hash_files:
                    rec["sha256"] = sha256_bytes(data)
                if e["name"].upper().startswith("SYSTEM.CNF"):
                    rec["system_cnf"] = data.decode("latin-1", "replace")
                if e["name"].upper().startswith(OWNED_BOOT_EXECUTABLE):
                    try:
                        rec["psx_exe"] = parse_psx_exe(data)
                    except ValueError as exc:
                        rec["psx_exe_error"] = str(exc)
            manifest["files"].append(rec)
    finally:
        iso.close()
    return manifest


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m gbox.capcom_generations DISC.BIN [--out manifest.json]",
              file=sys.stderr)
        return 2
    out_path = None
    if "--out" in args:
        i = args.index("--out")
        out_path = args[i + 1]
        del args[i:i + 2]
    man = build_manifest(args[0])
    text = json.dumps(man, indent=1, default=str)
    if out_path:
        with open(out_path, "w") as f:
            f.write(text)
        print("manifest ->", out_path)
    print("files", man["file_count"], "ext", json.dumps(man["extensions"]))
    for f in man["files"]:
        if "psx_exe" in f:
            print("boot", f["name"], f["size"], f["sha256"], json.dumps(f["psx_exe"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
