"""`reset_records`: wipe the SAVED Mercenaries / autoplay high scores so a bot run sets a fresh record.

Register with:  from . import merc_record_reset  # noqa: F401  (added to tools._load_tool_modules)

Operator (2026-11-04): "I need the hooks to somehow reset the high scores on these levels from the save so it can set
new scores to be admired." This is the cross-title hook for that. It targets ONLY the score / ranking / best-record
fields of a title and never the unlock / progress / costume data, so a reset never relocks a mode or erases a
campaign. Every save edit is backed up first (reusing each title's own backup + revert), the save's checksum is
verified before any write and recomputed after, and a RAM reset reads every write back. Where a title's record region
is not yet measured the op REFUSES (never guesses at a save offset), carrying the exact measurement recipe instead, so
running it can never corrupt a save.

Per-title record storage (confirmed vs pending):

* RE6 (Xbox 360, 43430819 / 0871eee3b68cdea3) -- CONFIRMED (save, gbox.re6_tool's save map):
  savedata.bin offset 0x235C = The Mercenaries records [solo, duo][10 stages][16 characters] x 12 bytes
  {u8 played, u8 rank (0 = best), u32 score, u8 kills, u8 combo, u8 costume, u8 partner}. Reset zeroes
  played/rank/score/kills/combo of every cell (score fields only), recomputes the file checksum (u32 at 8 =
  big-endian word sum from 12). Unlock masks (0x974 stages / 0x978 characters), mUnlockFlag (0xBC) and campaign
  records (0x164C) are untouched, so nothing relocks. Reuses re6_tool.save_path / save_backup / restore_save.

* RE5 Gold Edition (PS3 BLUS30491 / BLES00816, e7ca89bbeb67360d) -- CONFIRMED (save, gbox.re5_tool / docs/mercenaries.md):
  DATA0.DAT holds the Gold block 0x4BC0..0x566F AFTER the checksummed part (no checksum covers it). A fresh save has
  that whole block zero except three unlock words (0x4BC0 Reunion/Desperate-Escape open, 0x5640 stage mask, 0x565C
  character mask); the Reunion records (stage x character score + rank) fill the rest as you play. Reset zeroes the
  block and re-writes those three unlock words to their fully-open values (0x4BC0 = 1, 0x5640 = 0xFF, 0x565C = 0xFF),
  i.e. a fresh-but-fully-unlocked Reunion with no records. Reuses re5_tool.node_home / save_files / _backup /
  revert_file. The checksummed region (0x10..0x4BBF) is never touched.

* RE4 (Switch, 010099A00BC1E000 / 270a15eb98dab4d7) -- PENDING, PRIORITY. The classic RE4 keeps The Mercenaries
  high scores (a score + a 5-star/A-D rank per character per stage) in its "system data" save, next to the unlock
  bits (on GameCube: pSys = 0x80287E58, unlock bits at +4; the Switch port repackages the same system data).
  Not yet measured on the Switch build: its save path, the system-data file offset of the Merc score array, and/or
  the live RAM address the ranking screen reads. RECIPE below; this op refuses to write until RECORDS[...] is filled.

* RE6 Switch (115f9cdbba115432) / RE5 Switch (52d15709be0fda1a) -- PENDING (save). RE6 Switch SAVEDATA is 0x7050
  bytes, u32 checksum at 0x30 over the words from 0x34 (gbox.re6_switch_unlock knows only mUnlockFlag at 0xE8); the
  Mercenaries records block is the X360 0x235C layout's Switch analogue, not yet located. RE5 Switch: same, not
  mapped. RECIPE below.

* Phantasy Star Online Ep. I & II Plus (GameCube, 436e0bb84d5337d1) -- NO per-level high-score table. The offline
  autoplay campaign (Normal/Hard/...) keeps no Mercenaries-style score board to reset: character level, items and
  quest flags are progress, not records, and must not be wiped. PSO's only true "records" are Challenge Mode clear
  times and Battle Mode results on the memory card; the autoplay does not target those. So this op reports PSO as
  "no resettable high-score records" rather than touching the character save.

Measurement recipe for any PENDING title (then fill RECORDS[game_id] and flip confirmed=True):
  1. Save path: find the title's save on the worker (Switch: the Citron/eden nand save dir for the title id; back it
     up first -- memory gbox-never-delete-operator-files). Keep a copy outside the emulator before anything.
  2. Locate the score field. Two ways:
     a. RAM diff: on the ranking / results screen, job_memory_search a snapshot, note a displayed high score, then
        beat it in a run and diff -- the changed word at the ranking read is the live record. Confirm the save
        offset by diffing the save file before/after the game writes it.
     b. Static: job_ghidra_* / job_rea_* on the title binary for the routine that writes the Merc score to the
        system-data/save manager; its store offset is the record field.
  3. Prove it resets only the score: zero it on a BACKUP copy, load it, confirm the ranking shows no record AND every
     mode/character/stage is still unlocked and campaign progress is intact.
"""
from __future__ import annotations

import shutil
import struct
from pathlib import Path

from pydantic import BaseModel

from .models import Permission as P
from .registry import Unsupported, tool

# ---------------------------------------------------------------------------------------------------------------------
# Per-title record registry. kind: "save_re6" | "save_re5" | "ram" | "none" | "pending".
# confirmed=False => reset() refuses (never guesses a save offset / RAM address).

RECORDS: dict[str, dict] = {
    # RE6 Xbox 360 (Xenia). game_id from gbox.re6.GAME_ID; resolved lazily so this module imports without re6.
    "0871eee3b68cdea3": {
        "title": "Resident Evil 6 (Xbox 360)", "kind": "save_re6", "confirmed": True,
        "records_off": 0x235C, "rec_stride": 12, "rec_count": 2 * 10 * 16, "rec_clear": 8,
        "where": "savedata.bin offset 0x235C: [solo,duo][10 stages][16 characters] x 12 bytes "
                 "{played, rank, u32 score, kills, combo, costume, partner}; checksum u32 at 8 = BE word sum from 12",
        "safe": "unlock masks (0x974/0x978), mUnlockFlag (0xBC) and campaign records (0x164C) untouched",
    },
    # RE5 Gold Edition (PS3, RPCS3).
    "e7ca89bbeb67360d": {
        "title": "Resident Evil 5 Gold Edition (PS3)", "kind": "save_re5", "confirmed": True,
        "block": (0x4BC0, 0x5670),                       # [start, end) zeroed; past the checksummed part
        "keep": [("i32", 0x4BC0, 1), ("u32", 0x5640, 0xFF), ("u32", 0x565C, 0xFF)],   # re-open Reunion fully
        "where": "DATA0.DAT Gold block 0x4BC0..0x566F (not checksummed): Reunion stage x character score+rank",
        "safe": "block re-written to fresh-but-fully-unlocked Reunion (all 8 stages/characters open); the "
                "checksummed region 0x10..0x4BBF is never touched",
    },
    # RE4 Switch -- PRIORITY, pending measurement. Fill records_off (save) or ram_fields once measured.
    "270a15eb98dab4d7": {
        "title": "Resident Evil 4 (Switch) The Mercenaries", "kind": "pending", "confirmed": False,
        "where": "classic RE4 'system data' save (Merc score+rank per character per stage), beside the unlock bits; "
                 "Switch save path + offset not yet measured. Coordinate with the RE4 driver agent.",
        "ram_fields": [],                                 # [(addr, size)] once the live ranking read is located
    },
    # RE6 Switch -- pending (SAVEDATA 0x7050, checksum at 0x30; records block = X360 0x235C analogue, not located).
    "115f9cdbba115432": {
        "title": "Resident Evil 6 (Switch) The Mercenaries", "kind": "pending", "confirmed": False,
        "where": "SAVEDATA (0x7050 bytes, checksum u32 at 0x30 over words from 0x34); Merc records block not located",
    },
    # RE5 Switch -- pending.
    "52d15709be0fda1a": {
        "title": "Resident Evil 5 (Switch) The Mercenaries Reunion", "kind": "pending", "confirmed": False,
        "where": "Switch save; Reunion records block not located",
    },
    # PSO Ep. I & II Plus (GameCube) -- no per-level high-score table to reset.
    "436e0bb84d5337d1": {
        "title": "Phantasy Star Online Episode I & II Plus", "kind": "none", "confirmed": True,
        "where": "no Mercenaries-style per-level high-score board; character level/items/quest flags are PROGRESS, "
                 "not records (never wiped). Only Challenge/Battle records exist and the autoplay does not target them",
    },
}

GAME_IDS = set(RECORDS)


# ---------------------------------------------------------------------------------------------------------------------
# RE6 Xbox 360 (save) -- reuse gbox.re6_tool for the path, backup, checksum and revert.

def re6_count_records(data, spec: dict | None = None) -> int:
    """How many RE6 Mercenaries cells hold a score/rank now (pure; for dry-run reporting)."""
    spec = spec or RECORDS["0871eee3b68cdea3"]
    off, stride, count = spec["records_off"], spec["rec_stride"], spec["rec_count"]
    return sum(1 for i in range(count)
               if struct.unpack_from(">I", data, off + i * stride + 2)[0] or data[off + i * stride]
               or data[off + i * stride + 1])


def re6_clear_records(data: bytearray, spec: dict | None = None) -> int:
    """Zero played/rank/score/kills/combo of every RE6 Mercenaries cell in place (score fields only); returns the
    number of cells that held a record. Does NOT recompute the checksum (the caller does)."""
    spec = spec or RECORDS["0871eee3b68cdea3"]
    off, stride, count, clear = spec["records_off"], spec["rec_stride"], spec["rec_count"], spec["rec_clear"]
    if off + count * stride > len(data):
        raise RuntimeError(f"save is {len(data):#x} bytes: no Mercenaries record block at {off:#x}")
    had = re6_count_records(data, spec)
    for i in range(count):
        r = off + i * stride
        data[r:r + clear] = bytes(clear)
    return had


def _re6_reset(cfg, dry_run: bool) -> dict:
    from . import re6_tool
    spec = RECORDS["0871eee3b68cdea3"]
    sp = re6_tool.save_path(cfg)
    if not sp.is_file():
        raise RuntimeError("no RE6 save yet: start Resident Evil 6 once (it creates the save at the title screen)")
    data = bytearray(sp.read_bytes())
    if struct.unpack_from(">I", data, 8)[0] != re6_tool._save_sum(data):
        raise RuntimeError("RE6 save checksum does not match: not touching it (encrypted copy or another layout)")
    if dry_run:
        return {"file": str(sp), "records_with_a_score": re6_count_records(data, spec), "dry_run": True,
                "where": spec["where"], "safe": spec["safe"]}
    bk = re6_tool.save_backup(cfg)
    if not bk.exists():
        shutil.copytree(sp.parents[2], bk)                # content/43430819 as it was (re6_tool.restore_save reverts it)
    before = bytes(data)
    had = re6_clear_records(data, spec)                   # played, rank, u32 score, kills, combo -> 0
    struct.pack_into(">I", data, 8, re6_tool._save_sum(data))
    sp.write_bytes(bytes(data))
    back = sp.read_bytes()
    return {"file": str(sp), "backup": str(bk), "records_with_a_score": had,
            "bytes_changed": sum(1 for a, b in zip(before, back) if a != b),
            "checksum_ok": struct.unpack_from(">I", back, 8)[0] == re6_tool._save_sum(back),
            "verified": back == bytes(data), "where": spec["where"], "safe": spec["safe"],
            "takes_effect": "the next time RE6 loads its save (restart RE6 from gBox, or load from the title)"}


# ---------------------------------------------------------------------------------------------------------------------
# RE5 Gold Edition (save) -- reuse gbox.re5_tool for the path, backup, checksum and revert.

def re5_clear_block(data: bytearray, spec: dict | None = None) -> bool:
    """Zero the RE5 Gold Reunion record block in place and re-open Reunion fully (keep the three unlock words);
    returns whether the block held any records. Pure; the block is past the checksummed region, so no checksum fix."""
    spec = spec or RECORDS["e7ca89bbeb67360d"]
    lo, hi = spec["block"]
    if hi > len(data):
        raise RuntimeError(f"save is {len(data):#x} bytes: no Gold block at {hi:#x}")
    had = any(data[lo:hi])
    data[lo:hi] = bytes(hi - lo)                          # fresh-save state
    for kind, o, v in spec["keep"]:                       # then re-open Reunion fully (no relock)
        struct.pack_into(">i" if kind == "i32" else ">I", data, o, v)
    return had


def _re5_reset(cfg, serial: str, dry_run: bool) -> dict:
    from . import re5_tool
    spec = RECORDS["e7ca89bbeb67360d"]
    serial = (serial or "BLUS30491").upper().replace("-", "")
    re5_tool.version(serial)                              # refuse unknown serials instead of guessing a layout
    home = re5_tool.node_home(cfg)
    files = re5_tool.save_files(Path(home), serial)
    if not files:
        raise RuntimeError(f"no RE5 save (DATA0.DAT) for {serial} under {Path(home) / 'dev_hdd0' / 'home'}")
    lo, hi = spec["block"]
    out = {"saves": [], "where": spec["where"], "safe": spec["safe"]}
    for p in files:
        data = bytearray(p.read_bytes())
        if hi > len(data):
            out["saves"].append({"file": str(p), "skipped": f"save is {len(data):#x} bytes: no Gold block at {hi:#x}"})
            continue
        had = any(data[lo:hi])
        if dry_run:
            out["saves"].append({"file": str(p), "has_records": had, "dry_run": True})
            continue
        b = re5_tool._backup(p)
        if not b.exists():
            shutil.copy2(p, b)
        before = bytes(data)
        had = re5_clear_block(data, spec)                 # zero the Gold block, re-open Reunion fully (no relock)
        p.write_bytes(bytes(data))
        back = p.read_bytes()
        out["saves"].append({"file": str(p), "backup": str(b), "had_records": had,
                             "bytes_changed": sum(1 for a, c in zip(before, back) if a != c),
                             "verified": back == bytes(data)})
    out["verified"] = all(s.get("verified", False) for s in out["saves"] if not s.get("dry_run") and not s.get("skipped"))
    out["takes_effect"] = "the next time RE5 loads its save (restart RE5 from gBox, or load from the title)"
    return out


# ---------------------------------------------------------------------------------------------------------------------
# RAM reset (RE4 Switch once its ranking read is located): zero each confirmed (addr, size), read back.

def _ram_reset(adapter, spec: dict, dry_run: bool) -> dict:
    fields = spec.get("ram_fields") or []
    if not fields:
        raise Unsupported(f"{spec['title']}: no measured high-score RAM field yet. {spec['where']} "
                          "(fill RECORDS[game_id]['ram_fields'] = [(addr, size)] once located; see the recipe).")
    if dry_run:
        return {"ram_fields": [{"addr": hex(a), "size": n} for a, n in fields], "dry_run": True, "where": spec["where"]}
    done = []
    for addr, n in fields:
        adapter.write_memory(addr, bytes(n))
        back = bytes(adapter.read_memory(addr, n))
        done.append({"addr": hex(addr), "size": n, "verified": back == bytes(n)})
    return {"ram_fields": done, "verified": all(d["verified"] for d in done), "where": spec["where"],
            "takes_effect": "now, and the game's next save records the zeroed high scores"}


# ---------------------------------------------------------------------------------------------------------------------
# revert

def _revert(game_id: str, cfg, serial: str) -> dict:
    spec = RECORDS[game_id]
    if spec["kind"] == "save_re6":
        from . import re6_tool
        return {"reverted": re6_tool.restore_save(cfg), "note": "RE6 save restored from gBox's backup"}
    if spec["kind"] == "save_re5":
        from . import re5_tool
        home = re5_tool.node_home(cfg)
        files = re5_tool.save_files(Path(home), (serial or "BLUS30491").upper())
        return {"saves": [re5_tool.revert_file(p) for p in files]}
    return {"reverted": False, "note": "nothing to revert for this title (RAM reset has no file backup; relaunch "
                                       "restores RAM, and a pending title made no change)"}


# ---------------------------------------------------------------------------------------------------------------------
# dispatch

def run(game_id: str, op: str, cfg, adapter, serial: str = "") -> dict:
    op = (op or "status").strip().lower().replace("-", "_").replace(" ", "_")
    op = {"reset": "reset", "wipe": "reset", "clear": "reset", "reset_high_scores": "reset",
          "reset_scores": "reset", "restore": "revert", "revert_all": "revert"}.get(op, op)
    spec = RECORDS.get(game_id)
    if spec is None:
        raise Unsupported(f"reset_records: no high-score record map for game_id {game_id!r}. "
                          f"Mapped: {', '.join(sorted(RECORDS))}.")
    head = {"op": op, "game_id": game_id, "title": spec["title"], "kind": spec["kind"],
            "confirmed": spec["confirmed"], "where": spec["where"]}
    if op == "status":
        return {**head, "resettable": spec["confirmed"] and spec["kind"] not in ("pending", "none"),
                **({"safe": spec["safe"]} if "safe" in spec else {})}
    if op == "revert":
        return {**head, **_revert(game_id, cfg, serial)}
    if op != "reset":
        raise ValueError("reset_records op: status | reset [dry_run] | revert")
    if spec["kind"] == "none":
        raise Unsupported(f"{spec['title']}: {spec['where']}.")
    if not spec["confirmed"] or spec["kind"] == "pending":
        raise Unsupported(f"{spec['title']}: high-score records are not measured on this build yet, so the reset "
                          f"refuses rather than guess at a save offset and risk the save. {spec['where']}. "
                          "See the measurement recipe in gbox.merc_record_reset.")
    dry = bool(RECORDS[game_id].get("_dry"))
    if spec["kind"] == "save_re6":
        return {**head, **_re6_reset(cfg, dry)}
    if spec["kind"] == "save_re5":
        return {**head, **_re5_reset(cfg, serial, dry)}
    if spec["kind"] == "ram":
        return {**head, **_ram_reset(adapter, spec, dry)}
    raise Unsupported(f"{spec['title']}: unhandled record kind {spec['kind']!r}")


# ---------------------------------------------------------------------------------------------------------------------
# tool

class ResetIn(BaseModel):
    session_id: str = ""    # a running session (resolves game_id, save path/adapter and serial); or game_id below
    game_id: str = ""       # without a session: the catalog game_id to act on
    op: str = "status"      # status | reset | revert
    dry_run: bool = False   # reset: report what would be cleared without writing
    serial: str = ""        # RE5 PS3 without a session: BLUS30491 (default) | BLES00816


class ResetOut(BaseModel):
    result: dict


@tool("reset_records", "1.0", ResetIn, ResetOut, capabilities=["mod"], permissions=[P.FILE_MUTATION, P.MEMORY_WRITE],
      timeout_s=120)
def reset_records_tool(inp: ResetIn, ctx):
    """Reset a title's SAVED Mercenaries / autoplay high scores so the bot's next run sets a fresh record, without
    touching unlocks, progress or costumes. Save edits are backed up and checksummed; unmeasured titles refuse rather
    than guess. ops: status | reset [dry_run] | revert. Confirmed: RE6 (X360), RE5 Gold (PS3). Pending: RE4/RE5/RE6
    Switch. PSO has no resettable high-score board."""
    adapter = None
    serial = inp.serial
    game_id = inp.game_id
    if inp.session_id:
        from .tools import SESSIONS
        adapter, g = SESSIONS[inp.session_id]
        game_id = (g.get("game_id") if isinstance(g, dict) else None) or game_id
        if isinstance(g, dict):
            serial = serial or g.get("serial") or ""
    if not game_id:
        raise ValueError("reset_records: give session_id (a running session) or game_id")
    if inp.op.strip().lower() in ("reset", "wipe", "clear", "reset_scores", "reset_high_scores") and game_id in RECORDS:
        RECORDS[game_id] = {**RECORDS[game_id], "_dry": inp.dry_run}
    try:
        return {"result": run(game_id, inp.op, ctx.config, adapter, serial)}
    finally:
        if game_id in RECORDS:
            RECORDS[game_id].pop("_dry", None)
