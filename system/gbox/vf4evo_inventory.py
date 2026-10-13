"""Virtua Fighter 4 - Evolution (PS2, SLUS-205.79) owned-source inventory.

The owned build is the HyperSpin CD-type CHD ``Virtua Fighter 4 - Evolution (USA).chd``
(CHD v5, cdlz/cdzl/cdfl). chdman extractcd unpacks it to a raw track image; this module
sniffs the sector stride of that image (2048 / 2352 / 2448) and walks the ISO9660
filesystem without external tools.

Stage 1 deliverable: exact build identity (serial + boot ELF hash), launch prerequisites,
full disc file inventory and a per-archive asset census for the character containers.

Usage:
    python -m gbox.vf4evo_inventory DISC_IMAGE --chd-sha256 <hex> --out manifest.json
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import sys


# ---------------------------------------------------------------- ISO9660 walker

def _pvd_sector(data: bytes, stride: int) -> bytes | None:
    """Return the 2048-byte PVD (sector 16) for the given stride, or None."""
    off = 16 * stride
    if len(data) < off + 2048:
        return None
    s = data[off:off + 2048]
    return s if s[1:6] == b"CD001" else None


def sniff_stride(path: str) -> int:
    """Detect sector stride of a raw CD/DVD image (2048/2352/2448)."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(16 * 2448 + 2048)
    for stride in (2048, 2352, 2448):
        if _pvd_sector(head, stride) is not None:
            return stride
    # Fall back to a size heuristic for pure 2048-byte ISOs whose PVD check failed.
    for stride in (2048, 2352, 2448):
        if size % stride == 0:
            return stride
    raise ValueError(f"{path}: cannot determine sector stride (size {size})")


def _sector(data: bytes, lba: int, stride: int) -> bytes:
    off = lba * stride
    s = data[off:off + stride]
    if stride == 2048:
        return s
    if s[15] == 2:                      # Mode 2 Form 1
        return s[24:24 + 2048]
    return s[16:16 + 2048]              # Mode 1 / Form 2 (data payload)


# ---------------------------------------------------------------- minimal UDF (ECMA-167)

def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _long_ad(b: bytes, o: int) -> tuple[int, int]:
    """long_ad -> (length, lba)."""
    return _u32(b, o), _u32(b, o + 4)


class UdfWalk:
    """Read-only UDF (ECMA-167, non-spared, short_ad) file listing over a 2048-byte-sector image.

    Same interface as IsoWalk: ``files`` maps name -> (lba, size); ``read``/``sha256`` fetch bytes.
    """

    def __init__(self, path: str):
        with open(path, "rb") as f:
            self.data = f.read()
        if len(self.data) < 512 * 2048:
            raise ValueError(f"{path}: too small for a UDF image")
        self.stride = 2048
        anchor = self._sector(256)
        if anchor[0] != 2:
            anchor = self._sector(len(self.data) // 2048 - 1)   # last sector, non-ECMA-167 fallback
        if anchor[0] != 2:
            raise ValueError(f"{path}: no UDF anchor at 256")
        mvds_lba, mvds_len = _u32(anchor, 20), _u32(anchor, 16)
        self.part_start = 0
        self.fsd_lba = None
        for lba in range(mvds_lba, mvds_lba + (mvds_len + 2047) // 2048):
            s = self._sector(lba)
            ident = struct.unpack_from("<H", s, 0)[0]
            if ident == 5:                       # partition descriptor
                self.part_start = _u32(s, 188)
            elif ident == 6:                     # logical volume descriptor
                self.fsd_lba = _u32(s, 172)      # LogicalVolumeContentsUse long_ad (location)
        if self.fsd_lba is None or self.fsd_lba == 0:
            # Some PS2 mastering tools (DVD-ROM GENERATOR) leave the LVD
            # LogicalVolumeContentsUse zero; the FSD is the partition's first sector.
            cand = self.part_start if self._sector(self.part_start)[0] == 0 and \
                struct.unpack_from("<H", self._sector(self.part_start), 0)[0] == 256 else None
            if cand is None:
                for lba in range(self.part_start, len(self.data) // 2048):
                    s = self._sector(lba)
                    if struct.unpack_from("<H", s, 0)[0] == 256 and 0 < _u32(s, 404) < len(self.data) // 2048:
                        cand = lba
                        break
            if cand is None:
                raise ValueError(f"{path}: no file set descriptor")
            self.fsd_lba = cand
        fsd = self._sector(self.fsd_lba)
        root_icb = _long_ad(fsd, 400)            # FileSetDescriptor RootDirectoryICB
        self.files: dict[str, tuple[int, int]] = {}
        self._fe_cache: dict[int, bytes] = {}    # embedded File Entries by ICB offset
        self._walk_dir(root_icb[1], root_icb[0], "")

    def _sector(self, lba: int) -> bytes:
        return self.data[lba * 2048:(lba + 1) * 2048]

    def _fe_here(self, lba: int) -> bool:
        """Is there an allocated File Entry at absolute sector lba?"""
        if not 0 <= lba < len(self.data) // 2048:
            return False
        return struct.unpack_from("<H", self._sector(lba), 0)[0] == 261

    def _read_fe(self, icb_loc: int, length: int, dirbuf: bytes | None = None) -> bytes:
        """File Entry bytes for an ICB: allocated (partition-relative sector) or
        embedded (byte offset in the parent directory stream)."""
        if self._fe_here(self.part_start + icb_loc):
            n = max(1, (length + 2047) // 2048)
            return b"".join(self._sector(self.part_start + icb_loc + i) for i in range(n))
        if dirbuf is not None and 0 <= icb_loc < len(dirbuf):
            return dirbuf[icb_loc:icb_loc + max(2048, length)]
        raise ValueError(f"ICB at {icb_loc} is neither an allocated FE nor an embedded one")

    def _file_entry(self, fe: bytes) -> dict:
        ft = fe[27]                             # ICBTag.FileType (tag 16 + 11)
        info_len = struct.unpack_from("<Q", fe, 56)[0]
        xattr = _u32(fe, 168)
        nalloc = _u32(fe, 172)
        allocs = []
        o = 176 + xattr
        while o + 8 <= 176 + xattr + nalloc:
            allocs.append((_u32(fe, o), _u32(fe, o + 4)))
            o += 8
        return {"file_type": ft, "info_len": info_len, "allocs": allocs}

    def _fe_data(self, fe: bytes) -> bytes:
        meta = self._file_entry(fe)
        parts = []
        for size, loc in meta["allocs"]:
            for i in range((size + 2047) // 2048):
                parts.append(self._sector(self.part_start + loc + i)[:min(2048, size - i * 2048)])
        return b"".join(parts)[: meta["info_len"]]

    def _walk_dir(self, icb_loc: int, length: int, prefix: str, dirbuf: bytes | None = None) -> None:
        if icb_loc == 0 and length == 0:        # "No FSD" ICB
            return
        fe = self._read_fe(icb_loc, length, dirbuf)
        buf = self._fe_data(fe)
        o = 0
        while o < len(buf):
            if o + 38 > len(buf):
                break
            ident = struct.unpack_from("<H", buf, o)[0]
            if ident != 257:
                break
            nl = buf[o + 19]
            impl = struct.unpack_from("<H", buf, o + 36)[0]
            if o + 38 + impl + nl > len(buf):
                break
            icb = _long_ad(buf, o + 20)
            name = buf[o + 38 + impl:o + 38 + impl + nl]
            if name[:1] == b"\x10":            # OSTA compressed unicode (compression id 16)
                name = name[1:].decode("utf-16-be", "ignore")
            else:
                name = name.decode("latin-1", "ignore")
            clean = name.rstrip("\0").rstrip("\x00")
            rec_len = (38 + impl + nl + 3) & ~3
            if rec_len < 38:
                break
            if clean not in ("", ".", ".."):
                try:
                    cfe = self._read_fe(icb[1], icb[0], buf)
                    meta = self._file_entry(cfe)
                    if not self._fe_here(self.part_start + icb[1]):
                        self._fe_cache[icb[1]] = cfe   # embedded (stream offset, not a sector)
                except ValueError:
                    meta = None
                if meta is not None and meta["file_type"] == 4:
                    self._walk_dir(icb[1], icb[0], f"{prefix}{clean}/", buf)
                elif meta is not None:
                    self.files[f"{prefix}{clean}"] = (icb[1], meta["info_len"])
            o += rec_len

    def read(self, name: str) -> bytes:
        icb_loc, _size = self.files[name]
        fe = self._fe_cache.get(icb_loc) or self._read_fe(icb_loc, 2048)
        return self._fe_data(fe)

    def sha256(self, name: str) -> str:
        return hashlib.sha256(self.read(name)).hexdigest()


class IsoWalk:
    """Minimal ISO9660 directory walk over a raw image (file bytes loaded once)."""

    def __init__(self, path: str):
        self.path = path
        self.stride = sniff_stride(path)
        with open(path, "rb") as f:
            self.data = f.read()
        pvd = _pvd_sector(self.data, self.stride)
        if pvd is None:
            raise ValueError(f"{path}: no ISO9660 PVD at sector 16")
        root = pvd[156:156 + 34]
        self.files: dict[str, tuple[int, int]] = {}   # name -> (lba, size)
        self._walk(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "")

    def _walk(self, lba: int, size: int, prefix: str) -> None:
        buf = b"".join(self._sector(i) for i in range(lba, lba + (size + 2047) // 2048))
        o = 0
        while o < len(buf):
            ln = buf[o]
            if ln == 0:
                o = (o // 2048 + 1) * 2048
                continue
            elba, esize = struct.unpack_from("<I", buf, o + 2)[0], struct.unpack_from("<I", buf, o + 10)[0]
            flags, nl = buf[o + 25], buf[o + 32]
            name = buf[o + 33:o + 33 + nl]
            if name not in (b"\0", b"\1"):
                n = name.decode("latin-1").split(";")[0]
                if flags & 2:
                    self._walk(elba, esize, f"{prefix}{n}/")
                else:
                    self.files[f"{prefix}{n}"] = (elba, esize)
            o += ln

    def _sector(self, lba: int) -> bytes:
        return _sector(self.data, lba, self.stride)

    def read(self, name: str) -> bytes:
        lba, size = self.files[name]
        return b"".join(self._sector(lba + i) for i in range((size + 2047) // 2048))[:size]

    def sha256(self, name: str) -> str:
        return hashlib.sha256(self.read(name)).hexdigest()


# ---------------------------------------------------------------- CVM (SEGA AM2 container)

class CVMDisc:
    """SEGA PS2 CVM: ``CVMH`` header (0x800) + ``ZONE`` (0x1800) + an ISO9660 file
    system whose LBA space starts at CVM offset 0x2000. The mastering tool writes the
    PVD at LBA 15 (not 16) and uses null-named directory records for the per-character
    folders, so both quirks are handled here."""

    def __init__(self, data: bytes):
        if data[:4] != b"CVMH":
            raise ValueError("not a CVM (no CVMH magic)")
        self.data = data
        self.base = 0x2000
        self.pvd_lba = None
        for sec in range(4, 32):                # find the PVD in the LBA space
            off = self.base + sec * 2048
            if data[off + 1:off + 6] == b"CD001" and data[off] == 1:
                self.pvd_lba = sec
                break
        if self.pvd_lba is None:
            raise ValueError("CVM has no ISO9660 PVD")
        self.files: dict[str, tuple[int, int]] = {}
        self.dirs: list[str] = []
        self._visited: set[int] = set()
        self._walk_dir(pvd_lba=self.pvd_lba)

    def _walk_dir(self, pvd_lba: int, path: str = "", entry: tuple[int, int] | None = None,
                  parent_lba: int | None = None) -> None:
        if entry is None:
            pvd = self.data[self.base + pvd_lba * 2048:self.base + pvd_lba * 2048 + 2048]
            root = pvd[156:156 + 34]
            lba, size = struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0]
        else:
            lba, size = entry
        if lba in self._visited:
            return
        self._visited.add(lba)
        buf = self._sectors(lba, size)
        o = 0
        while o < len(buf):
            ln = buf[o]
            if ln == 0:
                o = (o // 2048 + 1) * 2048
                continue
            elba, esize = struct.unpack_from("<I", buf, o + 2)[0], struct.unpack_from("<I", buf, o + 10)[0]
            flags, nl = buf[o + 25], buf[o + 32]
            name = buf[o + 33:o + 33 + nl].decode("latin-1").split(";")[0]
            if flags & 2:                       # directory
                if name in ("", "\0", "\1"):
                    if elba == lba or elba == parent_lba:   # "." / ".." records
                        o += ln
                        continue
                    name = f"_dir{elba}"        # SEGA null-named per-character folders
                sub = f"{path}{name}/"
                self.dirs.append(sub)
                self._walk_dir(pvd_lba, sub, (elba, esize), parent_lba=lba)
            elif name not in ("", "\0", "\1"):
                self.files[f"{path}{name}"] = (elba, esize)
            o += ln

    def _sectors(self, lba: int, size: int) -> bytes:
        off = self.base + lba * 2048
        return self.data[off:off + size]

    def read(self, name: str) -> bytes:
        lba, size = self.files[name]
        return self._sectors(lba, size)

    def sha256(self, name: str) -> str:
        return hashlib.sha256(self.read(name)).hexdigest()


# ---------------------------------------------------------------- boot identity

def boot_identity(walk) -> dict:
    """SYSTEM.CNF -> BOOT2 path -> boot ELF sha256. PS2 discs always carry SYSTEM.CNF."""
    out: dict = {"system_cnf": None, "boot_path": None, "boot_elf": None, "boot_sha256": None}
    low = {k.lower(): k for k in walk.files}
    cnf_name = low.get("system.cnf")
    if cnf_name:
        cnf = walk.read(cnf_name).decode("latin-1")
        out["system_cnf"] = cnf
        for line in cnf.splitlines():
            if line.startswith("BOOT2"):
                out["boot_path"] = line.split("=", 1)[1].strip().rstrip("\r").replace("cdrom0:\\", "").replace("\\", "/").lstrip("/")
                if ";" in out["boot_path"]:
                    out["boot_path"] = out["boot_path"].split(";")[0]
                if out["boot_path"] not in walk.files:
                    # try case-insensitive fallback
                    low = {k.lower(): k for k in walk.files}
                    out["boot_path"] = low.get(out["boot_path"].lower(), out["boot_path"])
                out["boot_elf"] = out["boot_path"]
                out["boot_sha256"] = walk.sha256(out["boot_path"])
                out["boot_size"] = walk.files[out["boot_path"]][1]
                break
    return out


# ---------------------------------------------------------------- asset census

def asset_census(walk, min_size: int = 4096) -> dict:
    """Group disc files by extension; report the biggest files as candidate archives."""
    by_ext: dict[str, list[dict]] = {}
    for name, (lba, size) in walk.files.items():
        if size < min_size:
            continue
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else "(none)"
        by_ext.setdefault(ext, []).append({"name": name, "size": size, "lba": lba})
    census = {}
    for ext, rows in sorted(by_ext.items(), key=lambda kv: -sum(r["size"] for r in kv[1])):
        rows.sort(key=lambda r: -r["size"])
        census[ext] = {
            "count": len(rows),
            "total_bytes": sum(r["size"] for r in rows),
            "largest": rows[:12],
        }
    return census


def _is_udf(path: str) -> bool:
    with open(path, "rb") as f:
        f.seek(0, 2)
        if f.tell() < 257 * 2048:
            return False
        f.seek(256 * 2048)
        anchor = f.read(16)
        if anchor[0] == 2:
            return True
        f.seek(18 * 2048)
        return f.read(5)[1:5] == b"BEA01"


def cvm_census(walk) -> dict:
    """Parse every *.cvm container and catalogue its entries.

    Character archives are the ``CH_<code>.MRG_GZ`` entries (gzip-compressed MRG
    bundles); each per-character folder also holds part archives (ATAM/KAHA/JOHA/FACE).
    """
    census = {}
    for name in sorted(n for n in walk.files if n.lower().endswith(".cvm")):
        data = walk.read(name)
        info: dict = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        if data[:4] != b"CVMH":
            info.update({"entries": None, "note": "not a CVMH container"})
            census[name] = info
            continue
        cvm = CVMDisc(data)
        entries = {}
        for ename, (elba, esize) in sorted(cvm.files.items()):
            entries[ename] = {"lba": elba, "size": esize}
        info.update({
            "pvd_lba": cvm.pvd_lba,
            "entry_count": len(entries),
            "dirs": sorted(cvm.dirs),
            "entries": entries,
        })
        # .MRG_GZ payloads are opaque: no gzip/zlib magic, high-entropy heads,
        # byte-identical across both vf4files.cvm copies (deterministic container
        # codec/scramble). Codec identification is the analysis-stage opener.
        mrz_magics = {cvm.read(n)[:2].hex() for n in entries if n.endswith(".MRG_GZ")}
        info["mrg_gz_note"] = (
            f"{len(mrz_magics)} distinct 2-byte heads across {sum(1 for n in entries if n.endswith('.MRG_GZ'))} "
            ".MRG_GZ entries: no gzip/zlib magic, custom SEGA codec (analysis stage)"
        )
        # per-character archive map: <char code> -> CH_ files
        chars: dict[str, list[str]] = {}
        for ename in entries:
            base = ename.rsplit("/", 1)[-1]
            if base.startswith("CH_") and base.endswith(".MRG_GZ"):
                code = base[3:].split(".")[0]
                chars.setdefault(code, []).append(ename)
        info["characters"] = {c: sorted(v) for c, v in sorted(chars.items())}
        census[name] = info
    return census


def inventory(iso: str, chd_sha256: str, out: str | None = None) -> dict:
    udf = _is_udf(iso)
    walk = UdfWalk(iso) if udf else IsoWalk(iso)
    manifest = {
        "game": "Virtua Fighter 4 - Evolution",
        "platform": "ps2",
        "source_sha256": chd_sha256,
        "image": os.path.abspath(iso),
        "image_size": os.path.getsize(iso),
        "filesystem": "udf" if udf else "iso9660",
        "sector_stride": walk.stride,
        "file_count": len(walk.files),
        "files": dict(sorted(walk.files.items(), key=lambda kv: kv[0].lower())),
        "boot": boot_identity(walk),
        "extensions": asset_census(walk),
        "cvm": cvm_census(walk),
    }
    if out:
        with open(out, "w") as f:
            json.dump(manifest, f, indent=1)
    return manifest


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    iso = argv[1]
    rest = argv[2:]
    args = {}
    for i, a in enumerate(rest):
        if "=" in a:
            k, val = a.split("=", 1)
            args[k] = val
        elif a.startswith("--") and i + 1 < len(rest):
            args[a] = rest[i + 1]
    manifest = inventory(iso, args.get("--chd-sha256", ""), args.get("--out"))
    if not args.get("--out"):
        print(json.dumps({k: v for k, v in manifest.items() if k != "files"}, indent=1))
        print(f"files: {manifest['file_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
