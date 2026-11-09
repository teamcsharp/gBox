"""`hactool`: unpack a Switch title's containers with the binary the project now ships.

The title packages in this system arrive as `.nsp`/`.nca`, and until now nothing in the project could open one - the
RomFS trees were extracted by tooling outside it, which meant the executable was never available and questions that need
code (how a texture id reaches an `imagepackhd` archive, for one) could not be asked at all.

`hactool 1.4.0` is built from source and installed at `system/tools/bin/hactool` (`tools/bin/hactool` under the project
root). Every function here shells out to it and returns plain data; nothing writes into a title's own folder.
"""
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

TOOL_ENV = "GBOX_HACTOOL"
_WARN = re.compile(r"^\[WARN\].*\n", re.MULTILINE)
_KIND = {"nsp": "pfs0", "nca": "nca", "nso": "nso", "xci": "xci", "romfs": "romfs", "nro": "nro"}


class HactoolError(RuntimeError):
    """The tool could not be found, or it refused the file."""


def _root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def binary() -> pathlib.Path | None:
    """The `hactool` this project ships, or one on PATH. `GBOX_HACTOOL` overrides both."""
    override = os.environ.get(TOOL_ENV)
    if override:
        path = pathlib.Path(override).expanduser()
        return path if path.is_file() else None
    for candidate in (_root() / "tools" / "bin" / "hactool", _root() / "tools" / "bin" / "hactool.exe"):
        if candidate.is_file():
            return candidate
    found = shutil.which("hactool")
    return pathlib.Path(found) if found else None


def keys_path() -> pathlib.Path | None:
    """Where this system keeps the Switch keys: `GBOX_SWITCH_KEYS`, `~/gBox_alt/switch/prod.keys`, then `~/.switch`."""
    override = os.environ.get("GBOX_SWITCH_KEYS")
    if override and pathlib.Path(override).expanduser().is_file():
        return pathlib.Path(override).expanduser()
    for candidate in (pathlib.Path.home() / "gBox_alt" / "switch" / "prod.keys",
                      pathlib.Path.home() / ".switch" / "prod.keys"):
        if candidate.is_file():
            return candidate
    return None


def available() -> dict:
    """What the project can do with Switch containers right now, for a page to show rather than guess at."""
    tool, keys = binary(), keys_path()
    return {"hactool": str(tool) if tool else None, "keys": str(keys) if keys else None,
            "ready": bool(tool and keys), "version": version() if tool else None,
            "note": "build with `make` in hactool-1.4.0 (needs libmbedtls-dev); the binary belongs at "
                    "system/tools/bin/hactool"}


def version() -> str | None:
    tool = binary()
    if tool is None:
        return None
    try:
        done = subprocess.run([str(tool)], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (done.stdout or "") + (done.stderr or "")      # hactool prints its banner on stderr when given no arguments
    match = re.search(r"hactool \(c\) SciresM\.\s*\n(Built:[^\n]*)", out)
    return match[1].strip() if match else "hactool"


def _run(args: list[str], *, timeout: float = 3600) -> str:
    tool = binary()
    if tool is None:
        raise HactoolError(f"hactool is not installed (looked for {TOOL_ENV}, tools/bin/hactool and PATH)")
    try:
        done = subprocess.run([str(tool), *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise HactoolError(f"hactool timed out after {timeout:.0f}s: {' '.join(args[:4])}") from exc
    except OSError as exc:
        raise HactoolError(f"hactool could not be run: {exc}") from exc
    out = _WARN.sub("", (done.stdout or "") + (done.stderr or ""))
    if done.returncode != 0:
        raise HactoolError(f"hactool failed ({done.returncode}): {out.strip()[-400:]}")
    return out


def _key_args(keys: pathlib.Path | None = None) -> list[str]:
    chosen = pathlib.Path(keys) if keys else keys_path()
    if chosen is None or not pathlib.Path(chosen).is_file():
        raise HactoolError("no Switch keys found (expected ~/gBox_alt/switch/prod.keys)")
    return ["-k", str(chosen)]


def list_files(path, *, kind: str | None = None, keys=None, timeout: float = 600) -> list[dict]:
    """The file table of an `nsp`/`nca`/`xci`: name and size, read without extracting anything."""
    target = pathlib.Path(path)
    if not target.is_file():
        raise HactoolError(f"no such title file: {target}")
    out = _run(["-t", _KIND.get(kind or _guess_kind(target), kind or _guess_kind(target)), *_key_args(keys),
                "--listfiles", str(target)], timeout=timeout)
    files = []
    for line in out.splitlines():
        # hactool puts the FIRST file on the "Files:" line and indents the rest, so the pattern is searched for rather
        # than anchored to leading whitespace (anchoring dropped the first, and only the first, member)
        match = re.search(r"([\w.+-]+\.(?:nca|nsp|nro|tik|cert|nacp))\s+([0-9A-Fa-f]{8,16})-([0-9A-Fa-f]{8,16})", line)
        if match:
            start, end = int(match[2], 16), int(match[3], 16)
            files.append({"name": match[1], "offset": start, "size": max(0, end - start)})
    return files


def _guess_kind(path: pathlib.Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    return {"nsp": "pfs0", "nca": "nca", "nso": "nso", "xci": "xci"}.get(suffix, "pfs0")


def unpack_nsp(path, out_dir, *, keys=None, timeout: float = 7200) -> dict:
    """Extract an `nsp`'s `nca` members into `out_dir`. Returns the members with their sizes."""
    target, folder = pathlib.Path(path), pathlib.Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    _run(["-t", "pfs0", *_key_args(keys), "--outdir", str(folder), str(target)], timeout=timeout)
    members = sorted(({"name": p.name, "size": p.stat().st_size} for p in folder.glob("*.nca")),
                     key=lambda row: -row["size"])
    return {"nsp": str(target), "out_dir": str(folder), "members": members}


def extract_exefs(nca_or_nsp, out_dir, *, keys=None, program: str | None = None, timeout: float = 7200) -> dict:
    """Extract a title's executable: `main`, `main.npdm`, `rtld`, `sdk`, `subsdk0`.

    An `nsp` is unpacked to a temporary folder first and its largest `nca` taken as the program unless `program` names
    one, since the program NCA is the one that carries both the exefs and the RomFS. `kips`/`sections` are not
    requested: the exefs is what a code question needs, and pulling the RomFS as well would copy the whole title.
    """
    source, folder = pathlib.Path(nca_or_nsp), pathlib.Path(out_dir)
    if not source.is_file():
        raise HactoolError(f"no such title file: {source}")
    folder.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        nca = source
        if source.suffix.lower() == ".nsp":
            temporary = tempfile.mkdtemp(prefix="hactool-nsp-")
            members = unpack_nsp(source, temporary, keys=keys)["members"]
            if not members:
                raise HactoolError("the nsp held no nca")
            chosen = program or members[0]["name"]
            nca = pathlib.Path(temporary) / chosen
        _run(["-t", "nca", *_key_args(keys), f"--exefsdir={folder}", str(nca)], timeout=timeout)
        files = sorted(({"name": p.name, "size": p.stat().st_size} for p in folder.iterdir() if p.is_file()),
                       key=lambda row: -row["size"])
        if not files:
            raise HactoolError("hactool produced no exefs files (is this the program NCA?)")
        return {"source": str(source), "nca": nca.name, "out_dir": str(folder), "files": files,
                "main": next((row["name"] for row in files if row["name"] == "main"), None)}
    finally:
        if temporary:
            shutil.rmtree(temporary, ignore_errors=True)


def decompress_nso(nso, out, *, timeout: float = 600) -> dict:
    """NSO sections are LZ4-compressed; `--uncompressed` writes the ELF image a code tool can read."""
    source, target = pathlib.Path(nso), pathlib.Path(out)
    if not source.is_file():
        raise HactoolError(f"no such nso: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    out_text = _run(["-t", "nso", f"--uncompressed={target}", str(source)], timeout=timeout)
    sections = []
    for line in out_text.splitlines():
        match = re.match(r"\s+(\.[a-z.]+):\s+([0-9a-f]{8})-([0-9a-f]{8})", line)
        if match:
            sections.append({"name": match[1], "start": int(match[2], 16), "end": int(match[3], 16)})
    return {"nso": str(source), "out": str(target), "bytes": target.stat().st_size, "sections": sections}


def extract_romfs(nca, out_dir, *, keys=None, timeout: float = 14400) -> dict:
    """Extract a program NCA's RomFS. This is the whole title - gigabytes - so callers should ask for it deliberately."""
    target, folder = pathlib.Path(nca), pathlib.Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    _run(["-t", "nca", *_key_args(keys), f"--romfsdir={folder}", str(target)], timeout=timeout)
    return {"nca": str(target), "out_dir": str(folder), "files": sum(1 for _ in folder.rglob("*") if _.is_file())}
