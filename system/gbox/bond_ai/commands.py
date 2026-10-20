"""GoldenEye 007 (N64) AI command set from the n64decomp/007 decompilation (#2410, gBrain milestone 1).

GoldenEye's guards, objects and level logic run "AI lists": bytecode of 1-byte commands, each followed by fixed-width
parameters, run by an interpreter (chraiExecute in src/game/chrai.c). The decomp defines every command once in
src/aicommands.def, and the AI_CMD enum in src/bondconstants.h #includes that file, so a command's opcode is its
position among the `_AI_CMD(` / `_AI_DEBUG(` definitions (aliases defined with `_AI_CMD_POLYMORPH` reuse their base
command's opcode). This module reads that file into a machine-readable table (opcode, name, parameters with byte widths,
length, description, aliases) that a bytecode decoder, a bot-behaviour library or a translator to other games can
build on. The table for the decomp revision gBox used is gbox/bond_ai/commands.json.

    python -m gbox.bond_ai.commands <path to 007 repo>/src/aicommands.def [--out gbox/bond_ai/commands.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

WIDTHS = {"BYTE": 1, "DBYTE": 2, "TBYTE": 3, "QBYTE": 4}
PARAM = re.compile(r"\b(QBYTE|TBYTE|DBYTE|BYTE)\s*\(\s*(\w+)\s*\)")
TABLE = Path(__file__).with_name("commands.json")


def _description(lines: list[str]) -> str:
    """The text of a DESCRIPTION banner comment: one string, banner rules and leading '*' removed."""
    out = []
    for raw in lines:
        s = raw.strip().rstrip("\\").strip()
        s = re.sub(r"^/?\*+/?", "", s).strip()
        s = re.sub(r"\*+/?$", "", s).strip()
        if s and not set(s) <= {"*", "/", "=", "-"}:
            out.append(s)
    return "\n".join(out)


def parse(text: str) -> list[dict]:
    """aicommands.def -> [{opcode, name, params: [{name, bytes}], length, description, aliases}] in opcode order."""
    lines = text.splitlines()
    cmds: list[dict] = []
    name, desc, params = None, "", []
    i, skip = 0, 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if skip:                                            # inside #if 0 ... #endif (nested #if counted)
            if s.startswith("#if"):
                skip += 1
            elif s.startswith("#endif"):
                skip -= 1
            i += 1
            continue
        if re.match(r"#\s*if\s+0\b", s):
            skip = 1
            i += 1
            continue
        if line.startswith("#define CMDNAME"):
            name = line.split()[2]
            desc, params = "", []
        elif line.startswith("#define DESCRIPTION"):
            block = []
            i += 1
            while i < len(lines):
                block.append(lines[i])
                if "*/" in lines[i]:
                    break
                i += 1
            desc = _description(block)
        elif line.startswith("#define PARAMS"):
            body = line[len("#define PARAMS"):]
            while body.rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                body = body.rstrip()[:-1] + " " + lines[i]
            body = re.sub(r"/\*.*?\*/", "", body)
            params = [{"name": n, "bytes": WIDTHS[t]} for t, n in PARAM.findall(body)]
        elif line.startswith(("_AI_CMD(", "_AI_DEBUG(")):       # both make an AI_CMD enum entry (bondconstants.h)
            if not name:
                raise ValueError(f"line {i + 1}: a command without a CMDNAME")
            cmds.append({"opcode": len(cmds), "name": name, "params": params,
                         "length": 1 + sum(p["bytes"] for p in params), "description": desc, "aliases": [],
                         **({"debug": True} if line.startswith("_AI_DEBUG(") else {})})
        elif line.startswith("_AI_CMD_POLYMORPH("):
            chunk = line
            while chunk.count("(") > chunk.count(")") and i + 1 < len(lines):
                i += 1
                chunk += " " + lines[i]
            m = re.match(r"_AI_CMD_POLYMORPH\(\s*([^,]*),\s*(\w+)", chunk)
            if m and cmds and cmds[-1]["name"] == name:
                cmds[-1]["aliases"].append(m.group(2))
        i += 1
    return cmds


def table(def_path: Path, source: str = "") -> dict:
    raw = Path(def_path).read_bytes()
    cmds = parse(raw.decode("utf-8", "replace"))
    return {"game": "GoldenEye 007 (N64)", "source": source or "n64decomp/007 src/aicommands.def",
            "aicommands_def_sha256": hashlib.sha256(raw).hexdigest(), "opcode_bytes": 1, "count": len(cmds),
            "note": "opcode = position among the _AI_CMD / _AI_DEBUG definitions (the AI_CMD enum in src/bondconstants.h "
                    "includes aicommands.def); a command is its opcode byte followed by its parameters, big-endian.",
            "commands": cmds}


def load() -> dict:
    return json.loads(TABLE.read_text(encoding="utf-8"))


def by_opcode() -> dict[int, dict]:
    return {c["opcode"]: c for c in load()["commands"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("def_path")
    ap.add_argument("--out", default=str(TABLE))
    ap.add_argument("--source", default="")
    a = ap.parse_args(argv)
    t = table(Path(a.def_path), a.source)
    Path(a.out).write_text(json.dumps(t, indent=1) + "\n", encoding="utf-8")
    print(f"{t['count']} commands -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
