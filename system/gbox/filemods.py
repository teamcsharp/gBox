"""File-replacement mods for folder games (PS3 disc folders and the like) without touching the original.

A local base copy of the game is made once (cache/modbase/<game_id>); each mod is a tree of hard links to it in which
only the replaced/patched files are real copies (cache/mods/<game_id>/<mod>), so a mod costs only its own files.
Rollback = delete the mod folder. Launch with `launch_game(mod=<name>)`.
"""
import json
import os
import shutil
import time
from pathlib import Path


def game_root(rom: Path) -> Path:
    """The folder that makes up the game: a PS3 disc folder (…/PS3_GAME/USRDIR/EBOOT.BIN -> disc root), else the rom's folder."""
    p = Path(rom)
    if p.name.upper() == "EBOOT.BIN" and p.parent.name.upper() == "USRDIR" and p.parents[1].name.upper() == "PS3_GAME":
        return p.parents[2]
    return p.parent


def base_dir(cfg, game_id: str) -> Path:
    return Path(cfg.cache) / "modbase" / game_id


def mod_dir(cfg, game_id: str, name: str) -> Path:
    return Path(cfg.cache) / "mods" / game_id / name


def ensure_base(cfg, game_id: str, rom: Path, progress=None) -> Path:
    base, src = base_dir(cfg, game_id), game_root(rom)
    done = base / ".gbox-base-complete"
    if done.exists():
        return base
    files = [f for f in src.rglob("*") if f.is_file()]
    total, copied = sum(f.stat().st_size for f in files) or 1, 0
    for f in files:
        t = base / f.relative_to(src)
        if not t.exists() or t.stat().st_size != f.stat().st_size:
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, t)
        copied += f.stat().st_size
        if progress:
            progress(5 + 70 * copied / total, f"base copy {copied / 2**30:.1f} / {total / 2**30:.1f} GB")
    done.write_text(str(src))
    return base


def build(cfg, game_id: str, rom: Path, name: str, changes: dict, progress=None) -> dict:
    """changes: {relative path: {"from": local file} | {"bytes": raw} | {"patch": [{"offset": int, "hex": str}]}}."""
    base = ensure_base(cfg, game_id, rom, progress)
    out = mod_dir(cfg, game_id, name)
    if out.exists():
        shutil.rmtree(out)
    norm = {Path(k).as_posix().lower(): (k, v) for k, v in changes.items()}
    applied = []
    for f in base.rglob("*"):
        if f.name == ".gbox-base-complete":
            continue
        rel = f.relative_to(base)
        t = out / rel
        if f.is_dir():
            t.mkdir(parents=True, exist_ok=True)
            continue
        t.parent.mkdir(parents=True, exist_ok=True)
        hit = norm.pop(rel.as_posix().lower(), None)
        if not hit:
            os.link(f, t)                                  # shared with the base copy: no extra space
            continue
        key, ch = hit
        if "from" in ch:
            shutil.copy2(ch["from"], t)
        elif "bytes" in ch:
            t.write_bytes(ch["bytes"])
        else:
            data = bytearray(f.read_bytes())
            for p in ch.get("patch", []):
                off, b = int(str(p["offset"]), 0), bytes.fromhex(p["hex"])
                if off + len(b) > len(data):
                    raise ValueError(f"{key}: patch at {off:#x} runs past the end of the file")
                data[off:off + len(b)] = b
            t.write_bytes(bytes(data))
        applied.append(key)
    for key, ch in norm.values():                          # new files the game didn't have
        t = out / key
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ch["from"], t) if "from" in ch else t.write_bytes(ch.get("bytes", b""))
        applied.append(key + " (new)")
    (out / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": game_id, "files": applied, "built": time.time()}))
    return {"mod": name, "dir": str(out), "files": applied}


def is_folder_game(rom: Path) -> bool:
    return Path(rom).name.upper() == "EBOOT.BIN"


def gcz_to_iso(src: Path, dst: Path, progress=None):
    """Dolphin GCZ -> plain disc image (header, block pointers with bit 63 = stored, zlib blocks)."""
    import struct
    import zlib
    with open(src, "rb") as f, open(dst, "wb") as out:
        magic, _sub, csize, dsize, bsize, n = struct.unpack("<IIQQII", f.read(32))
        if magic != 0xB10BC001:
            raise ValueError("not a GCZ image")
        ptrs = struct.unpack(f"<{n}Q", f.read(8 * n))
        base = 32 + 12 * n
        for i, p in enumerate(ptrs):
            start = p & ~(1 << 63)
            end = (ptrs[i + 1] & ~(1 << 63)) if i + 1 < n else csize
            f.seek(base + start)
            raw = f.read(end - start)
            out.write(raw if p >> 63 else zlib.decompress(raw))
            if progress and i % 512 == 0:
                progress(5 + 60 * i / n, f"decompressing {Path(src).name}")
        out.truncate(dsize)


def build_image(cfg, game_id: str, rom: Path, name: str, changes: dict, progress=None) -> dict:
    """Single-image games: copy the image (GCZ -> ISO) and apply changes. Keys: "@image" = byte patches on the image;
    a GameCube disc path (e.g. "PSO/ItemPMT.prs") = replace (in its slot when it fits, else moved after the last
    file; the FST entry gets the new offset/size)
    or patch inside that file."""
    rom = Path(rom)
    out_dir = mod_dir(cfg, game_id, name)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    img = out_dir / (rom.stem + (".iso" if rom.suffix.lower() == ".gcz" else rom.suffix))
    if rom.suffix.lower() == ".gcz":
        gcz_to_iso(rom, img, progress)
    else:
        shutil.copy2(rom, img)
    applied, disc = [], None
    with open(img, "r+b") as f:
        for key, ch in changes.items():
            if key == "@image":
                for p in ch.get("patch", []):
                    f.seek(int(str(p["offset"]), 0))
                    f.write(bytes.fromhex(p["hex"]))
                applied.append("@image")
                continue
            if disc is None:
                from .gcdisc import GCDisc
                disc = GCDisc(img)
            if key not in disc.files:
                raise ValueError(f"{key} is not on this disc")
            off, size = disc.files[key]
            if "patch" in ch:
                for p in ch["patch"]:
                    o, b = int(str(p["offset"]), 0), bytes.fromhex(p["hex"])
                    if o + len(b) > size:
                        raise ValueError(f"{key}: patch at {o:#x} runs past the end of the file")
                    f.seek(off + o)
                    f.write(b)
            else:
                data = Path(ch["from"]).read_bytes() if "from" in ch else ch["bytes"]
                from .romexport import gc_put_file          # in its slot, or moved to free space after the last file
                gc_put_file(f, disc, key, data)
            applied.append(key)
    if disc is not None:
        disc.f.close()
    (out_dir / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": game_id, "image": img.name, "files": applied, "built": time.time()}))
    return {"mod": name, "dir": str(out_dir), "image": str(img), "files": applied}


def launch_path(cfg, game_id: str, rom: Path, name: str) -> Path:
    out = mod_dir(cfg, game_id, name)
    if not (out / ".gbox-mod.json").exists():
        raise ValueError(f"no built mod {name!r} for this game")
    meta = json.loads((out / ".gbox-mod.json").read_text())
    if meta.get("image"):
        return out / meta["image"]
    return out / Path(rom).relative_to(game_root(rom))


def _files(d: Path) -> list[dict]:
    return [{"path": p.relative_to(d).as_posix(), "size": p.stat().st_size} for p in sorted(d.rglob("*")) if p.is_file()]


def fetch(cfg, server: str, headers: dict, game_id: str, name: str, progress=None) -> bool:
    """A mod built elsewhere: download it from the central collection (the Spark) into this machine's cache. Resumable:
    files already here with the right size are kept. Returns False if the collection doesn't have it either."""
    import httpx
    r = httpx.get(f"{server}/api/modfiles/{game_id}/{name}", headers=headers, timeout=60)
    if r.status_code == 404:
        return False
    r.raise_for_status()
    files, out = r.json()["files"], mod_dir(cfg, game_id, name)
    total, done = sum(f["size"] for f in files) or 1, 0
    for f in sorted(files, key=lambda f: f["path"] == ".gbox-mod.json"):    # the marker last: a half copy isn't a mod
        dst = out / f["path"]
        if dst.exists() and dst.stat().st_size == f["size"]:
            done += f["size"]
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".part")
        with httpx.stream("GET", f"{server}/api/modfiles/{game_id}/{name}/file/{f['path']}", headers=headers, timeout=None) as s:
            s.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in s.iter_bytes(1 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(20 + int(8 * done / total), f"Fetching mod {name} from the collection: {done >> 20}/{total >> 20} MB")
        os.replace(tmp, dst)
    return (out / ".gbox-mod.json").exists()


def push_missing(cfg, server: str, headers: dict) -> list[str]:
    """Mods this machine built that the central collection lacks: upload them (worker start, in the background)."""
    import httpx
    sent, root = [], Path(cfg.cache) / "mods"
    if not root.exists():
        return sent
    for meta in root.glob("*/*/.gbox-mod.json"):
        d, game_id, name = meta.parent, meta.parent.parent.name, meta.parent.name
        r = httpx.get(f"{server}/api/modfiles/{game_id}/{name}", headers=headers, timeout=60)
        have = {f["path"]: f["size"] for f in r.json().get("files", [])} if r.status_code == 200 else {}
        todo = [f for f in _files(d) if have.get(f["path"]) != f["size"] and not f["path"].endswith(".part")]
        for f in sorted(todo, key=lambda f: f["path"] == ".gbox-mod.json"):
            with open(d / f["path"], "rb") as fh:
                httpx.put(f"{server}/api/modfiles/{game_id}/{name}/file/{f['path']}", content=fh, headers=headers,
                          timeout=None).raise_for_status()
        if todo:
            sent.append(f"{game_id}/{name}")
    return sent


def list_mods(cfg, game_id: str) -> list[dict]:
    d = Path(cfg.cache) / "mods" / game_id
    return [json.loads((m / ".gbox-mod.json").read_text()) for m in sorted(d.iterdir()) if (m / ".gbox-mod.json").exists()] if d.exists() else []


def remove(cfg, game_id: str, name: str) -> bool:
    out = mod_dir(cfg, game_id, name)
    if out.exists():
        shutil.rmtree(out)
        return True
    return False


def _selftest():
    import tempfile
    import types
    td = Path(tempfile.mkdtemp())
    src = td / "lib" / "Game" / "PS3_GAME" / "USRDIR"
    src.mkdir(parents=True)
    (src / "EBOOT.BIN").write_bytes(b"ELF0")
    (src / "data.bin").write_bytes(b"\x00\x01\x02\x03")
    cfg = types.SimpleNamespace(cache=td / "cache")
    r = build(cfg, "g1", src / "EBOOT.BIN", "test", {"PS3_GAME/USRDIR/data.bin": {"patch": [{"offset": 1, "hex": "ff"}]}})
    p = launch_path(cfg, "g1", src / "EBOOT.BIN", "test")
    assert p.read_bytes() == b"ELF0" and (p.parent / "data.bin").read_bytes() == b"\x00\xff\x02\x03"
    assert (src / "data.bin").read_bytes() == b"\x00\x01\x02\x03"                 # original untouched
    assert os.stat(p).st_nlink >= 2 and r["files"] == ["PS3_GAME/USRDIR/data.bin"] # unchanged files are hard links
    assert list_mods(cfg, "g1")[0]["name"] == "test" and remove(cfg, "g1", "test") and not list_mods(cfg, "g1")
    # single-file image: byte patch, original untouched
    rom = td / "lib" / "game.z64"
    rom.write_bytes(bytes(16))
    r = build_image(cfg, "g2", rom, "lives", {"@image": {"patch": [{"offset": "0x4", "hex": "6363"}]}})
    p = launch_path(cfg, "g2", rom, "lives")
    assert p.read_bytes()[4:6] == b"cc" and rom.read_bytes() == bytes(16)
    # GCZ -> ISO round trip (one stored block + one zlib block)
    import struct
    import zlib
    blocks = [b"A" * 32, b"B" * 32]
    c1, c2 = blocks[0], zlib.compress(blocks[1])
    gcz = td / "lib" / "t.gcz"
    gcz.write_bytes(struct.pack("<IIQQII", 0xB10BC001, 0, len(c1) + len(c2), 64, 32, 2) +
                    struct.pack("<QQ", (1 << 63) | 0, len(c1)) + bytes(8) + c1 + c2)
    gcz_to_iso(gcz, td / "t.iso")
    assert (td / "t.iso").read_bytes() == b"A" * 32 + b"B" * 32
    print("filemods selftest ok")


if __name__ == "__main__":
    _selftest()
