"""Builds on this PC (#1639): download a build into this PC's cache without launching it, find its folder, and export it
to a folder the operator picks, by default in the same format as the original game file.

The build_local tool (gbox.tools) runs these on the operator's own worker; the Mods cards and the Builds rows reach it
through POST /api/builds/{game}/{name}/local (gbox.builds).

Export formats (choose() decides, options() labels them for the dialog before the job runs):
  same   the container of the catalog's own file, keeping its file name:
           built as that container already (.iso/.gcm/.bin/.cue + bins/.gdi + tracks/.z64/.zip/...) -> copied;
           .gcz -> written here (Dolphin GCZ: zlib blocks + Adler-32 hashes, no tool needed);
           .cso -> written here (CISO v1, raw deflate blocks);
           .n64 / .v64 -> the .z64 build in the original byte order;
           .zip -> the image zipped under the original's inner name;
           .chd -> chdman createcd (.cue / .gdi / CD .iso) or createdvd (DVD .iso) when chdman is on this PC;
           .rvz / .wia -> dolphin-tool convert; .wbfs -> wit copy --wbfs;
           a folder game (PS3 / Xbox 360 extracted folder) -> the folder; a Wii extracted tree -> rebuilt with dolphin-tool.
         A converter missing on this PC never fails the export: the plain image is written and `notice` says which tool
         would make the original format.
  plain  the uncompressed image the build boots (what gBox launches): .iso / .bin + .cue / .gdi + tracks / .z64 / folder
  patch  BPS (and IPS <= 16 MiB, xdelta when xdelta3 is installed) against the operator's own original file
         (gbox.romexport: the same patch writers as Export ROM hack); a folder build: a patch kit (one .bps per changed
         file). Needs the original on this PC.
  zip    the plain files in one .zip

Everything is written under <dest>/<game title> - <build name>/ (never over the original, never uploaded); every file
is written as <name>.part first and renamed when complete.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
import zipfile
import zlib
from pathlib import Path

FORMATS = ("same", "plain", "patch", "zip")
MARKERS = (".gbox-mod.json", ".gbox-staged-of")
GBOX_DIRS = (".gbox-backup", ".gbox-pending")   # a Switch overlay's edit history (gbox.switch_mods): not game files
ROOT_EXTRAS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".json", ".glb", ".gltf")   # previews / reports gBox writes
FOLDER_IMAGES = (".xex", ".dol", ".self", ".elf")                                    # a launch file inside a folder game
CD_PLATFORMS = {"psx", "ps1", "saturn", "segacd", "megacd", "pcecd", "dreamcast", "dc", "neocd", "3do", "pcfx", "cdi",
                "naomi", "jaguarcd", "amigacd32", "cd32"}
GCZ_MAGIC, GCZ_BLOCK = 0xB10BC001, 0x4000
CSO_MAGIC, CSO_BLOCK = b"CISO", 2048
CHUNK = 1 << 22

# the source container -> (what it is, the program that writes it on this PC; None = gBox writes it itself)
CONTAINERS = {".iso": ("disc image", None), ".gcm": ("GameCube disc image", None), ".bin": ("disc / ROM image", None),
              ".cue": ("cue sheet + tracks", None), ".gdi": ("GD-ROM .gdi + tracks", None),
              ".z64": ("N64 ROM (big-endian)", None), ".n64": ("N64 ROM (little-endian)", None),
              ".v64": ("N64 ROM (byte-swapped)", None), ".zip": ("zip archive", None),
              ".gcz": ("Dolphin GCZ (compressed)", None), ".cso": ("compressed ISO (CSO)", None),
              ".chd": ("MAME CHD (compressed)", "chdman"), ".rvz": ("Dolphin RVZ (compressed)", "dolphin-tool"),
              ".wia": ("Dolphin WIA (compressed)", "dolphin-tool"), ".wbfs": ("WBFS (Wii backup)", "wit")}
SAME_KIND = ({".iso", ".gcm"}, {".cue", ".bin"})                                     # one container, two spellings


# ================================================================ what the build is made of

def is_folder(meta: dict) -> bool:
    img = str(meta.get("image") or "")
    return not img or img.lower().endswith(FOLDER_IMAGES) or Path(img).name.upper() == "EBOOT.BIN"


def _quoted_names(text: str, pattern: str) -> list[str]:
    return [m.group(1) or m.group(2) for m in re.finditer(pattern, text, re.I | re.M)]


def companions(folder: Path, image: str) -> list[str]:
    """The files that make up an image build: the image plus the tracks its .cue / .gdi / .m3u names (relative paths)."""
    img = folder / image
    out = [image]
    ext = img.suffix.lower()
    try:
        text = img.read_text("utf-8", "replace") if ext in (".cue", ".gdi", ".m3u") and img.stat().st_size < 1 << 20 else ""
    except OSError:
        text = ""
    if ext == ".cue":
        names = _quoted_names(text, r'^\s*FILE\s+(?:"([^"]+)"|(\S+))')
    elif ext == ".gdi":
        names = []
        for line in text.splitlines()[1:]:
            m = re.match(r'\s*\d+\s+\d+\s+\d+\s+\d+\s+(?:"([^"]+)"|(\S+))', line)
            if m:
                names.append(m.group(1) or m.group(2))
    elif ext == ".m3u":
        names = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    else:
        names = []
    base = Path(image).parent
    for n in names:
        rel = (base / n).as_posix()
        if ".." not in Path(rel).parts and (folder / rel).is_file() and rel not in out:
            out.append(rel)
    return out


def game_files(folder: Path, meta: dict) -> list[str]:
    """Relative paths of the build's game files (never gBox's marker, staging mark, partial downloads or root previews)."""
    if not is_folder(meta):
        return companions(folder, str(meta["image"]))
    out = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.name in MARKERS or p.name.endswith(".part"):
            continue
        rel = p.relative_to(folder)
        if (len(rel.parts) == 1 and p.suffix.lower() in ROOT_EXTRAS) or rel.parts[0] in GBOX_DIRS:
            continue
        out.append(rel.as_posix())
    return out


# ================================================================ the format plan

def _src_ext(src_name: str) -> str:
    n = str(src_name or "").lower()
    return Path(n).suffix if Path(n).suffix else ""


def choose(fmt: str, src_name: str, image: str, platform: str = "", *, folder: bool = False, chd_cd: bool | None = None) -> dict:
    """What an export of format fmt writes: {format, kind, ext, tool, label}. kind: copy | folder | gcz | cso | byteswap |
    zipimage | chd | dolphin | wit | wii_tree | patch | patch_kit | zip. Pure: the dialog and the worker agree."""
    if fmt not in FORMATS:
        raise ValueError(f"format: one of {', '.join(FORMATS)}")
    src, img = _src_ext(src_name), Path(str(image or "")).suffix.lower()
    plat = str(platform or "").lower()
    plain_ext = "folder" if folder else img or "image"
    if fmt == "plain":
        return {"format": fmt, "kind": "folder" if folder else "copy", "ext": plain_ext, "tool": None,
                "label": "Plain " + ("folder" if folder else f"image ({plain_ext})")}
    if fmt == "zip":
        return {"format": fmt, "kind": "zip", "ext": ".zip", "tool": None, "label": "Zip of the " + ("folder" if folder else f"{plain_ext} files")}
    if fmt == "patch":
        return {"format": fmt, "kind": "patch_kit" if folder else "patch", "ext": ".zip" if folder else ".bps",
                "tool": None, "label": "Patch kit (one .bps per changed file)" if folder else "Patch only (BPS, + IPS / xdelta)"}
    same = {"format": "same", "ext": src or plain_ext, "tool": None}
    what = CONTAINERS.get(src, (src.lstrip(".").upper() or "original", None))[0]
    label = f"Same format as the original ({src or plain_ext}: {what})"
    if folder:
        if plat == "wii" and src in (".iso", ".wbfs", ".rvz", ".wia", ".gcz"):
            return same | {"kind": "wii_tree", "tool": "wit" if src == ".wbfs" else "dolphin-tool", "label": label}
        why = f" (the original is {src}: the extracted folder is what boots)" if src not in ("", ".bin", ".elf") else ""
        return same | {"kind": "folder", "ext": "folder", "label": f"Same format as the original (extracted folder){why}"}
    if src == img or not src or any(src in g and img in g for g in SAME_KIND):
        return same | {"kind": "copy", "ext": img or src, "label": label}
    if src == ".gcz" and img in (".iso", ".gcm"):
        return same | {"kind": "gcz", "label": label}
    if src in (".cso", ".ciso") and img == ".iso":
        return same | {"kind": "cso", "label": label}
    if src in (".n64", ".v64", ".z64") and img in (".n64", ".v64", ".z64"):
        return same | {"kind": "byteswap", "label": label}
    if src == ".zip":
        return same | {"kind": "zipimage", "label": label}
    if src == ".chd" and img in (".cue", ".gdi", ".iso", ".toc"):
        cd = chd_cd if chd_cd is not None else (img != ".iso" or plat in CD_PLATFORMS)
        return same | {"kind": "chd", "tool": "chdman", "chd": "createcd" if cd else "createdvd", "label": label}
    if src in (".rvz", ".wia") and img in (".iso", ".gcm"):
        return same | {"kind": "dolphin", "tool": "dolphin-tool", "label": label}
    if src == ".wbfs" and img in (".iso", ".gcm"):
        return same | {"kind": "wit", "tool": "wit", "label": label}
    return same | {"kind": "copy", "ext": img, "label": f"Same format as the build ({img}): gBox can't write {src} files",
                   "notice": f"The original is a {src} file; gBox has no {src} writer, so the build's own {img} is exported"}


def options(src_name: str, image: str, platform: str = "", *, folder: bool = False, chd_cd: bool | None = None) -> list[dict]:
    """The export dialog's choices, "same" first (the default); a format that can't apply says why (disabled)."""
    out = []
    for f in FORMATS:
        o = choose(f, src_name, image, platform, folder=folder, chd_cd=chd_cd)
        row = {"id": f, "label": o["label"], "ext": o["ext"], "kind": o["kind"], "default": f == "same"}
        if o.get("tool"):
            row["needs"] = o["tool"]
            row["note"] = (f"needs {o['tool']} on this PC; without it the plain "
                           f"{'image' if not folder else 'disc'} is exported and you are told")
        if o.get("notice"):
            row["note"] = o["notice"]
        if f == "patch":
            row["note"] = "needs your original game file on this PC (the patch holds only the changed bytes)"
            if not folder and Path(str(image or "")).suffix.lower() in (".cue", ".gdi", ".m3u"):
                row["disabled"] = "a patch needs a single-image build; this one is several track files"
        out.append(row)
    return out


# ================================================================ writers

def _copy(src: Path, dst: Path, progress=None, done: list | None = None, total: int = 1):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        while blk := fi.read(CHUNK):
            fo.write(blk)
            if done is not None:
                done[0] += len(blk)
                if progress:
                    progress(done[0] / total, f"Writing {dst.name}: {done[0] >> 20}/{total >> 20} MB")
    shutil.copystat(src, tmp)
    os.replace(tmp, dst)


def write_gcz(src: Path, dst: Path, block: int = GCZ_BLOCK, sub_type: int | None = None, progress=None) -> Path:
    """Dolphin GCZ from a plain GameCube / Wii image: header, block pointers (bit 63 = stored), Adler-32 of each stored
    block, zlib blocks; the last block is zero-padded to the block size (Dolphin's reader expects whole blocks)."""
    size = Path(src).stat().st_size
    n = max(1, (size + block - 1) // block)
    if sub_type is None:
        with open(src, "rb") as f:
            head = f.read(0x20)
        sub_type = 1 if len(head) >= 0x1C and struct.unpack_from(">I", head, 0x18)[0] == 0x5D1C9EA3 else 0
    tmp = Path(dst).with_name(Path(dst).name + ".part")
    ptrs, hashes, pos = [], [], 0
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        fo.write(b"\0" * (32 + 12 * n))
        for i in range(n):
            raw = fi.read(block)
            raw += b"\0" * (block - len(raw))
            comp = zlib.compress(raw, 6)
            stored = len(comp) >= block
            data = raw if stored else comp
            ptrs.append(pos | (1 << 63 if stored else 0))
            hashes.append(zlib.adler32(data) & 0xFFFFFFFF)
            fo.write(data)
            pos += len(data)
            if progress and i % 2048 == 0:
                progress(i / n, f"Compressing to GCZ: {i * block >> 20}/{size >> 20} MB")
        fo.seek(0)
        fo.write(struct.pack("<IIQQII", GCZ_MAGIC, sub_type, pos, size, block, n))
        fo.write(struct.pack(f"<{n}Q", *ptrs))
        fo.write(struct.pack(f"<{n}I", *hashes))
    os.replace(tmp, dst)
    return Path(dst)


def write_cso(src: Path, dst: Path, block: int = CSO_BLOCK, progress=None) -> Path:
    """CISO v1 (PSP) from a plain ISO, streamed: raw deflate blocks, a block stored when deflate doesn't shrink it."""
    size = Path(src).stat().st_size
    n = (size + block - 1) // block
    shift = 0 if size < (1 << 31) - (1 << 20) else 2
    header = 0x18
    tmp = Path(dst).with_name(Path(dst).name + ".part")
    index = []
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        fo.write(b"\0" * (header + 4 * (n + 1)))
        for i in range(n):
            pos = fo.tell()
            pad = -pos % (1 << shift)
            if pad:
                fo.write(b"\0" * pad)
                pos += pad
            raw = fi.read(block)
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            comp = c.compress(raw) + c.flush()
            if len(comp) >= len(raw):
                index.append((pos >> shift) | 0x80000000)
                fo.write(raw + b"\0" * (block - len(raw)))
            else:
                index.append(pos >> shift)
                fo.write(comp)
            if progress and i % 8192 == 0:
                progress(i / max(1, n), f"Compressing to CSO: {i * block >> 20}/{size >> 20} MB")
        pos = fo.tell()
        pad = -pos % (1 << shift)
        fo.write(b"\0" * pad)
        index.append((pos + pad) >> shift)
        fo.seek(0)
        fo.write(struct.pack("<4sIQIBBxx", CSO_MAGIC, header, size, block, 1, shift))
        fo.write(struct.pack(f"<{n + 1}I", *index))
    os.replace(tmp, dst)
    return Path(dst)


N64_MAGIC = {".z64": b"\x80\x37\x12\x40", ".v64": b"\x37\x80\x40\x12", ".n64": b"\x40\x12\x37\x80"}


def n64_order(data: bytes, ext: str) -> bytes:
    """Any N64 byte order -> the order of ext (.z64 big-endian, .v64 byte-swapped, .n64 little-endian words)."""
    import numpy as np
    from .romexport import n64_to_z64
    z = n64_to_z64(data)
    if ext == ".v64":
        return np.frombuffer(z, ">u2").astype("<u2").tobytes()
    if ext == ".n64":
        return np.frombuffer(z, ">u4").astype("<u4").tobytes()
    return z


def find_tool(cfg, name: str) -> str | None:
    """chdman / wit / xdelta3 on PATH, else in gBox's runtime folder (runtime/<tool>/, runtime/mame/)."""
    exe = shutil.which(name)
    if exe:
        return exe
    rt = Path(getattr(cfg, "runtime", "") or ".")
    for d in (rt / name, rt / "mame", rt / "tools", rt):
        for n in (name + ".exe", name):
            if (d / n).is_file():
                return str(d / n)
    return None


def _run(argv: list[str], what: str):
    r = subprocess.run(argv, capture_output=True, text=True, timeout=7200)
    if r.returncode:
        raise RuntimeError(f"{what} failed: {(r.stderr or r.stdout)[-400:]}")


def _inner_name(src: Path | None, fallback: str) -> str:
    """The original zip's first image name, so the zipped build keeps the original's naming."""
    try:
        if src and src.is_file():
            with zipfile.ZipFile(src) as z:
                names = [i.filename for i in z.infolist() if not i.is_dir()]
                if names:
                    return Path(max(names, key=lambda n: z.getinfo(n).file_size)).name
    except (OSError, zipfile.BadZipFile):
        pass
    return fallback


def safe(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", str(s or ""))).strip(" .") or "gBox build"


def out_dir(dest: Path, title: str, label: str) -> Path:
    """<dest>/<game title> - <build name>/; (2), (3)... when that folder already holds files."""
    stem = safe(f"{re.sub(r'[(].*', '', title or '').strip() or 'Game'} - {label}")[:150]
    d = Path(dest) / stem
    i = 2
    while d.exists() and any(d.iterdir()):
        d = Path(dest) / f"{stem} ({i})"
        i += 1
    return d


def export(cfg, *, game: dict, rom: Path | None, folder: Path, meta: dict, dest: Path, fmt: str = "same", label: str = "",
           progress=None) -> dict:
    """Write the build in `folder` (this PC's cache copy) to dest in format fmt. Returns {dir, main, files, format,
    kind, ext, notice?, patches?}."""
    prog = progress or (lambda p, m: None)
    dest = Path(dest)
    if not dest.is_absolute():
        raise ValueError("dest must be an absolute folder on this PC")
    if not dest.is_dir():
        raise ValueError(f"{dest} is not a folder on this PC")
    folder = Path(folder)
    src_name = Path(str(rom)).name if rom else str(game.get("source_name") or "")
    fold = is_folder(meta)
    chd_cd = None
    if rom and Path(rom).suffix.lower() == ".chd" and Path(rom).is_file():
        from .chd import ChdError, track_layout
        try:
            chd_cd = bool(track_layout(rom))
        except (ChdError, OSError, ValueError):
            chd_cd = False
    plan = choose(fmt, src_name, str(meta.get("image") or ""), game.get("platform", ""), folder=fold, chd_cd=chd_cd)
    files = game_files(folder, meta)
    if not files:
        raise ValueError("this build has no game files on this PC")
    out = out_dir(dest, game.get("title") or game.get("game_id") or "", label or meta.get("title") or meta.get("name") or folder.name)
    out.mkdir(parents=True)
    res = {"dir": str(out), "format": fmt, "kind": plan["kind"], "ext": plan["ext"], "label": plan["label"],
           "source": src_name, "image": meta.get("image") or "", "notice": plan.get("notice", "")}
    image = folder / str(meta.get("image") or "")
    src_stem = Path(src_name).stem if src_name else ""
    total = sum((folder / f).stat().st_size for f in files) or 1
    done = [0]

    def named(rel: str) -> str:
        """The main image takes the original's file name (its tracks keep theirs: the .cue / .gdi names them)."""
        if src_stem and not fold and rel == meta.get("image") and Path(rel).parent == Path("."):
            return src_stem + Path(rel).suffix
        return rel

    def plain(into: Path, scale=(0.0, 1.0)) -> list[Path]:
        a, b = scale
        made = []
        root = into / (_folder_name(game, rom, folder) if fold else "")
        for rel in files:
            dst = root / named(rel)
            _copy(folder / rel, dst, lambda f, m: prog(a + (b - a) * f, m), done, total)
            made.append(dst)
        return made

    try:
        kind = plan["kind"]
        if kind in ("copy", "folder"):
            made = plain(out)
            res["main"] = str(made[0] if not fold else out / _folder_name(game, rom, folder))
        elif kind == "zip":
            made = [out / ((src_stem or folder.name) + ".zip")]
            tmp = made[0].with_name(made[0].name + ".part")
            root = _folder_name(game, rom, folder) + "/" if fold else ""
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                for i, rel in enumerate(files):
                    prog(0.95 * i / len(files), f"Zipping {rel}")
                    z.write(folder / rel, root + named(rel))
            os.replace(tmp, made[0])
            res["main"] = str(made[0])
        elif kind == "zipimage":
            name = _inner_name(Path(rom) if rom else None, named(meta["image"]))
            if Path(name).suffix.lower() in N64_MAGIC and image.suffix.lower() in N64_MAGIC and Path(name).suffix.lower() != image.suffix.lower():
                data = n64_order(image.read_bytes(), Path(name).suffix.lower())
            else:
                data = None
            made = [out / ((src_stem or image.stem) + ".zip")]
            tmp = made[0].with_name(made[0].name + ".part")
            prog(0.1, f"Zipping {name}")
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                if data is not None:
                    z.writestr(name, data)
                else:
                    z.write(image, name)
                for rel in files[1:]:
                    z.write(folder / rel, rel)
            os.replace(tmp, made[0])
            res["main"] = str(made[0])
        elif kind == "byteswap":
            ext = plan["ext"]
            made = [out / ((src_stem or image.stem) + ext)]
            prog(0.2, f"Writing {made[0].name} ({ext[1:]} byte order)")
            tmp = made[0].with_name(made[0].name + ".part")
            tmp.write_bytes(n64_order(image.read_bytes(), ext))
            os.replace(tmp, made[0])
            res["main"] = str(made[0])
        elif kind == "gcz":
            made = [write_gcz(image, out / ((src_stem or image.stem) + ".gcz"), progress=lambda f, m: prog(0.95 * f, m))]
            res["main"] = str(made[0])
        elif kind == "cso":
            made = [write_cso(image, out / ((src_stem or image.stem) + ".cso"), progress=lambda f, m: prog(0.95 * f, m))]
            res["main"] = str(made[0])
        elif kind in ("chd", "dolphin", "wit"):
            made = _convert(cfg, plan, image, files, folder, out, src_stem, prog, res, named)
        elif kind == "wii_tree":
            made = _wii_tree(cfg, plan, folder, out, src_stem or folder.name, prog, res)
        elif kind in ("patch", "patch_kit"):
            made = _patch(cfg, game, rom, folder, meta, image, out, src_stem, fold, prog, res)
        else:                                              # pragma: no cover - choose() names every kind
            raise ValueError(f"unknown export kind {kind}")
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)       # never a half-written export
        raise
    res["files"] = [{"path": p.relative_to(out).as_posix(), "size": p.stat().st_size}
                    for p in sorted(out.rglob("*")) if p.is_file()][:400]
    res["bytes"] = sum(f["size"] for f in res["files"])
    prog(1.0, f"Exported to {out}")
    return res


def _folder_name(game: dict, rom: Path | None, folder: Path) -> str:
    """A folder game's export keeps the original disc folder's name (PS3: the folder holding PS3_GAME)."""
    if rom:
        from .filemods import game_root, is_folder_game
        if is_folder_game(Path(rom)):
            return game_root(Path(rom)).name
    return safe(game.get("title") or folder.name)


def _convert(cfg, plan, image: Path, files, folder: Path, out: Path, stem: str, prog, res, named) -> list[Path]:
    """chdman / dolphin-tool / wit: the original's container when the program is on this PC, else the plain image."""
    tool = plan["tool"]
    target = out / ((stem or image.stem) + plan["ext"])
    tmp = target.with_name(target.stem + ".part" + target.suffix)
    try:
        if plan["kind"] == "chd":
            exe = find_tool(cfg, "chdman")
            if not exe:
                raise FileNotFoundError("chdman")
            prog(0.05, f"chdman {plan['chd']}: compressing to {target.name} (this takes a while)")
            _run([exe, plan["chd"], "-i", str(image), "-o", str(tmp), "-f"], f"chdman {plan['chd']}")
        elif plan["kind"] == "dolphin":
            from .romexport import _dolphin_tool
            fmt = plan["ext"].lstrip(".")
            args = ["convert", "-i", str(image), "-o", str(tmp), "-f", fmt]
            if fmt in ("rvz", "wia"):
                args += ["-b", "131072", "-c", "zstd" if fmt == "rvz" else "lzma2", "-l", "5"]
            prog(0.05, f"dolphin-tool: converting to {target.name}")
            try:
                _dolphin_tool(cfg, args, [image.parent, out])
            except FileNotFoundError as e:
                raise FileNotFoundError("dolphin-tool") from e
        else:
            exe = find_tool(cfg, "wit")
            if not exe:
                raise FileNotFoundError("wit")
            prog(0.05, f"wit: writing {target.name}")
            _run([exe, "copy", "--wbfs", "--overwrite", str(image), str(tmp)], "wit copy")
        os.replace(tmp, target)
        res["main"] = str(target)
        return [target]
    except FileNotFoundError as e:
        name = str(e.args[0]) if e.args else tool
        res["notice"] = (f"{name} isn't installed on this PC, so the {plan['ext']} file couldn't be made: the plain "
                         f"{image.suffix} image was exported instead (install {name} and export again for {plan['ext']})")
        res["fallback"] = image.suffix
        res["kind"] = "copy"
        total = sum((folder / f).stat().st_size for f in files) or 1
        done, made = [0], []
        for rel in files:
            dst = out / named(rel)
            _copy(folder / rel, dst, lambda f, m: prog(f, m), done, total)
            made.append(dst)
        res["main"] = str(made[0])
        return made


def _wii_tree(cfg, plan, folder: Path, out: Path, stem: str, prog, res) -> list[Path]:
    """A Wii build kept as an extracted tree: dolphin-tool rebuilds the disc (DirectoryBlob) as iso / rvz / wia / gcz;
    .wbfs = that iso through wit. No dolphin-tool: the extracted tree is copied and the notice says so."""
    from .romexport import _dolphin_tool
    dol = next(iter(sorted(folder.rglob("main.dol"))), None)
    if dol is None:
        raise ValueError("this Wii build has no sys/main.dol to rebuild the disc from")
    ext = plan["ext"]
    fmt = "iso" if ext in (".iso", ".wbfs") else ext.lstrip(".")
    iso = out / (stem + ("." + fmt))
    tmp = iso.with_name(iso.stem + ".part" + iso.suffix)
    args = ["convert", "-i", str(dol), "-o", str(tmp), "-f", fmt]
    if fmt in ("rvz", "wia"):
        args += ["-b", "131072", "-c", "zstd" if fmt == "rvz" else "lzma2", "-l", "5"]
    try:
        prog(0.05, f"dolphin-tool: rebuilding the Wii disc as {iso.name}")
        _dolphin_tool(cfg, args, [folder, out])
    except FileNotFoundError:
        res["notice"] = ("dolphin-tool isn't on this PC, so the Wii disc couldn't be rebuilt: the extracted folder was "
                         "exported instead (Dolphin boots its sys/main.dol)")
        res["kind"], res["fallback"] = "folder", "folder"
        made = []
        for p in sorted(folder.rglob("*")):
            if p.is_file() and p.name not in MARKERS and not p.name.endswith(".part"):
                dst = out / stem / p.relative_to(folder)
                _copy(p, dst)
                made.append(dst)
        res["main"] = str(out / stem)
        return made
    os.replace(tmp, iso)
    if ext != ".wbfs":
        res["main"] = str(iso)
        return [iso]
    exe = find_tool(cfg, "wit")
    if not exe:
        res["notice"] = "wit isn't installed on this PC, so no .wbfs could be made: the rebuilt .iso was exported instead"
        res["fallback"] = ".iso"
        res["main"] = str(iso)
        return [iso]
    wbfs = out / (stem + ".wbfs")
    _run([exe, "copy", "--wbfs", "--overwrite", str(iso), str(wbfs)], "wit copy")
    iso.unlink()
    res["main"] = str(wbfs)
    return [wbfs]


def _patch(cfg, game, rom, folder, meta, image, out, stem, fold, prog, res) -> list[Path]:
    """BPS (+ IPS / xdelta) of the build against the operator's own original (gbox.romexport's patch writers)."""
    from . import romexport as RX
    if not rom or not Path(rom).exists():
        raise ValueError("a patch is made against your original game file, and it isn't on this PC: "
                         "choose another format, or export from the PC that has the game")
    stem = stem or image.stem
    if fold:
        base, only = RX._folder_base(cfg, game["game_id"], {"dir": folder, "meta": meta}, Path(rom), prog)
        if base is None:
            raise ValueError("no vanilla copy of this folder game on this PC to diff against (launch it once unmodded)")
        kit = out / (stem + " - patch kit.zip")
        prog(0.3, "Patch kit: one .bps per changed file")
        p = RX._patch_kit(base, folder, kit, only)
        res["patches"] = [p]
        res["main"] = str(kit)
        return [kit]
    if image.suffix.lower() in (".cue", ".gdi", ".m3u"):
        raise ValueError("a patch needs a single-image build; this one is several track files: export it as the same "
                         "format or as a zip")
    prog(0.05, "Reading your original image")
    base = RX.vanilla_image(cfg, game, Path(rom), lambda p, m: prog(0.05 + 0.25 * p / 100, m))
    target = image
    if game.get("platform") in ("n64", "n64dd") and image.suffix.lower() != ".z64":
        target = out / (".target.z64")
        target.write_bytes(n64_order(image.read_bytes(), ".z64"))
    prog(0.35, "Comparing with your original")
    regions = list(RX.diff_regions(base, target))
    res["changed_bytes"] = sum(len(d) for _, d in regions)
    made = []
    bps = out / (stem + ".bps")
    res["patches"] = [RX.make_bps(base, target, bps, meta=f"gBox build {meta.get('name') or ''}", regions=regions)]
    made.append(bps)
    if target.stat().st_size <= RX.IPS_MAX and base.stat().st_size <= RX.IPS_MAX:
        ips = out / (stem + ".ips")
        res["patches"].append(RX.make_ips(base, target, ips, regions=regions))
        made.append(ips)
    prog(0.7, "xdelta3 patch")
    x = RX.make_xdelta(base, target, out / (stem + ".xdelta"))
    if x and x.get("file"):
        res["patches"].append(x)
        made.append(out / x["file"])
    elif x is None:
        res["notice"] = "xdelta3 isn't installed on this PC: BPS" + (" and IPS" if len(made) > 1 else "") + " only"
    if target != image:
        target.unlink()
    res["apply_to"] = {"file": Path(rom).name, "crc32": res["patches"][0].get("source_crc32"), "plain": base.name}
    (out / "README.txt").write_text(
        f"{game.get('title') or game.get('game_id')} - {meta.get('title') or meta.get('name') or ''}\n\n"
        f"Apply {bps.name} (Flips / beat / RomPatcher.js) to {base.name} (crc32 {res['apply_to']['crc32']}), the plain "
        f"image of your own {Path(rom).name}.\nThe patch holds only the bytes that differ from your original.\n",
        encoding="utf-8")
    res["main"] = str(bps)
    return made


# ================================================================ this PC's copy

def locate(cfg, game_id: str, name: str) -> Path | None:
    """This PC's folder of a build: the build itself when complete, else its newest complete staged copy."""
    from . import filemods
    best = None
    for n in filemods.copies_of(cfg, game_id, name):
        d = filemods.mod_dir(cfg, game_id, n)
        marker = d / ".gbox-mod.json"
        if not marker.is_file():
            continue
        if n == name:
            return d
        if best is None or marker.stat().st_mtime > (best / ".gbox-mod.json").stat().st_mtime:
            best = d
    return best


def summary(folder: Path) -> dict:
    meta = json.loads((folder / ".gbox-mod.json").read_text(encoding="utf-8"))
    files = game_files(folder, meta)
    return {"dir": str(folder), "folder": folder.name, "image": meta.get("image") or "",
            "files": len(files), "size": sum((folder / f).stat().st_size for f in files)}
