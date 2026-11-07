"""The RE4 GameCube decompilation as a reference corpus: search it, and read structure offsets out of it.

`adonis-singh/re4` is a byte-identical decompilation of **G4BE08**, the debug build this system's RE4 MercMode rotation
plays. Its headers carry the field offsets (`s16 hp; // 0x320`), which is exactly what a bot needs and exactly what is
missing from a stripped binary: an anchor is (structure layout + a base pointer), and this supplies the first half.

Nothing here builds or runs that project - it is read as text. That keeps it safe to query from a route or an agent.
"""
import os
import pathlib
import re

ROOT_ENV = "GBOX_RE4_REFERENCE"
DEFAULT_ROOT = pathlib.Path.home() / "gBox_alt" / "reference" / "re4-gc-decomp"
FIELD = re.compile(r"^\s*(?:[A-Za-z_][\w:<>,\s*]*?\s+)?([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*;\s*//\s*0x([0-9A-Fa-f]+)")
HEADER = re.compile(r"(?:class|struct)\s+([A-Za-z_]\w*)\s*(?::[^{]*)?\{")


def root() -> pathlib.Path:
    override = os.environ.get(ROOT_ENV)
    return pathlib.Path(override) if override else DEFAULT_ROOT


def available() -> dict:
    """Whether the corpus is present, and what it is - for a page to show rather than guess at."""
    folder = root()
    sources = list(folder.glob("src/**/*.cpp")) + list(folder.glob("src/**/*.c")) if folder.is_dir() else []
    headers = list(folder.glob("include/*.h")) if folder.is_dir() else []
    readme = (folder / "README.md")
    first = ""
    if readme.is_file():
        first = readme.read_text(encoding="utf-8", errors="replace").splitlines()[0][:120]
    return {"root": str(folder), "present": folder.is_dir(), "sources": len(sources), "headers": len(headers),
            "title": first,
            "note": "clone with `git clone --depth 1 https://github.com/adonis-singh/re4.git` into that root; "
                    "this reads it as text and never builds it"}


def _files(pattern: str = "**/*") -> list[pathlib.Path]:
    folder = root()
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob(pattern) if p.is_file() and p.suffix in (".h", ".c", ".cpp", ".hpp"))


def search(text: str, *, limit: int = 40, regex: bool = False) -> list[dict]:
    """Find `text` (or a regex) across the decompilation, one row per matching line with its file and line number."""
    if not text:
        return []
    pattern = re.compile(text if regex else re.escape(text), re.IGNORECASE)
    rows = []
    for path in _files():
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(body.splitlines(), 1):
            if pattern.search(line):
                rows.append({"file": path.relative_to(root()).as_posix(), "line": number, "text": line.strip()[:200]})
                if len(rows) >= limit:
                    return rows
    return rows


def find_struct(name: str) -> dict | None:
    """The definition body of one class/struct, located by name."""
    if not name:
        return None
    for path in _files("include/*.h") + _files("src/**/*.cpp"):
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in HEADER.finditer(body):
            if match.group(1) != name:
                continue
            depth, index = 0, match.end() - 1
            while index < len(body):
                char = body[index]
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return {"name": name, "file": path.relative_to(root()).as_posix(),
                                "body": body[match.end():index]}
                index += 1
    return None


def offsets(name: str) -> dict:
    """The annotated field offsets of one structure: `{field: offset}`, in source order.

    Only fields the decompilation annotates with `// 0xNN` appear - it documents what it has established, so a missing
    field means "not established here", not zero.
    """
    found = find_struct(name)
    if not found:
        return {"name": name, "found": False, "fields": {}, "file": None}
    fields = {}
    for line in found["body"].splitlines():
        match = FIELD.match(line)
        if match:
            fields.setdefault(match.group(1), int(match.group(2), 16))
    return {"name": name, "found": True, "file": found["file"], "fields": dict(sorted(fields.items(),
                                                                                      key=lambda kv: kv[1]))}


def structures() -> list[str]:
    """Every class/struct name the headers define - the index a caller browses before asking for offsets."""
    names = set()
    for path in _files("include/*.h"):
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        names.update(match.group(1) for match in HEADER.finditer(body))
    return sorted(names)
