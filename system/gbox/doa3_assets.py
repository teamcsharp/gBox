"""Bounded native DOA3 asset bundles; no model decoder or game writer is implied."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import uuid

from .doa3_inventory import afs_names, afs_table, fighter_families, sniff, xpr_header
from .doa3_native import XBE_SHA256, PATCHED_XBE_SHA256, _plain_path
from .registry import ToolUnavailable

SCHEMA = "gbox-doa3-native-assets-v1"
MAX_ENTRIES = 8192
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_MEMBER_BYTES = 128 * 1024**2
MAX_EXPORT_BYTES = 512 * 1024**2
MAX_EXPORT_MEMBERS = 1024
XBE_HASHES = {XBE_SHA256, PATCHED_XBE_SHA256}
STATUS = {"raw": True, "decoded": False, "writable": False, "reimportable": False,
          "full_character_replacement": False,
          "reason": "Native AFS/XPR/MDL/CAT bytes are preserved; DOA3 geometry, rig, animation decoding and retarget writing are not implemented"}


def _absolute(path):
    # Normalize dot segments without resolving or following filesystem links.
    return Path(os.path.abspath(path))


def _hash(stream, size=None):
    digest = hashlib.sha256()
    left = size
    while left is None or left:
        block = stream.read(1024**2 if left is None else min(left, 1024**2))
        if not block:
            if left:
                raise ToolUnavailable("DOA3 native asset read was incomplete")
            break
        digest.update(block)
        if left is not None:
            left -= len(block)
    return digest.hexdigest()


def _file_hash(path):
    _plain_path(path)
    with path.open("rb") as stream:
        return _hash(stream)


def _signature(path):
    _plain_path(path)
    stat = path.stat()
    if not path.is_file():
        raise ToolUnavailable("DOA3 native asset source is not a regular file")
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def _safe_name(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", name) or name.endswith((".", " ")) \
            or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ToolUnavailable("DOA3 AFS member has an unsafe native filename")
    return name


def _game_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{16}", value):
        raise ValueError("Native asset provenance requires an exact catalog game ID")
    return value


def _entries(path):
    """Parse only bounded AFS metadata and stream each member's fingerprint."""
    size = _signature(path)[0]
    if not 16 <= size <= MAX_ARCHIVE_BYTES:
        raise ToolUnavailable("DOA3 loadfile.afs exceeds its supported archive bounds")
    with path.open("rb") as stream:
        head = stream.read(8)
        if head[:4] != b"AFS\0":
            raise ToolUnavailable("DOA3 loadfile.afs has no CRI AFS header")
        count = struct.unpack_from("<I", head, 4)[0]
        if not 1 <= count <= MAX_ENTRIES or 16 + count * 8 > size:
            raise ToolUnavailable("DOA3 AFS member table exceeds its supported bounds")
        stream.seek(0)
        table_size = 16 + count * 8
        try:
            table = afs_table(stream.read(table_size), size)
        except (ValueError, struct.error) as error:
            raise ToolUnavailable(f"Invalid DOA3 AFS table: {error}") from error
        for offset, length in zip(table["offsets"], table["sizes"]):
            if length and (offset < table_size or length > MAX_MEMBER_BYTES):
                raise ToolUnavailable("DOA3 AFS member leaves its supported source bounds")
        names_pair = table["name_dir"]
        if names_pair is None:
            first = next((offset for offset, length in zip(table["offsets"], table["sizes"]) if length), 0)
            if first < table_size + 8:
                raise ToolUnavailable("DOA3 AFS has no supported name directory")
            stream.seek(first - 8)
            names_pair = struct.unpack("<II", stream.read(8))
        offset, length = names_pair
        if length != 48 * count or offset < table_size or offset + length > size \
                or any(n and start < offset + length and offset < start + n for start, n in zip(table["offsets"], table["sizes"])):
            raise ToolUnavailable("DOA3 AFS name directory overlaps or leaves the archive")
        stream.seek(offset)
        names = afs_names(stream.read(length), count)
        result = []
        for index, (offset, length, info) in enumerate(zip(table["offsets"], table["sizes"], names)):
            name = _safe_name(info["name"])
            if info["size"] != length:
                raise ToolUnavailable("DOA3 CRI name-directory size differs from its member table")
            stream.seek(offset)
            prefix = stream.read(min(length, 64))
            stream.seek(offset)
            row = {"index": index, "name": name, "offset": offset, "size": length,
                   "sha256": _hash(stream, length), "format": sniff(prefix),
                   "kind": "native_resource", **STATUS}
            if prefix[:4] == b"wwww" or not length:
                row["kind"] = "placeholder"
            elif name.lower().endswith(".mot"):
                row["kind"] = "motion"
            elif name.lower().endswith(".cat"):
                row["kind"] = "model_companion"
            elif prefix[:4] == b"XPR0":
                try:
                    row["xpr"] = xpr_header(prefix)
                except ValueError as error:
                    raise ToolUnavailable(f"Invalid native XPR header in member {index}") from error
                if row["xpr"]["total"] > length:
                    raise ToolUnavailable("DOA3 XPR declared size leaves its AFS member")
                row["kind"] = "model" if row["xpr"]["first_tag"] == "MDL" else "packed_resource"
            if name.lower().startswith("stg") and name.lower().endswith(".xpr"):
                row["role"] = "stage_resource"
            row["placeholder"] = row["kind"] == "placeholder"
            result.append(row)
    return result


def _families(entries):
    families = fighter_families([{**row, "magic": row["format"]} for row in entries])
    for index, family in enumerate(families):
        end = families[index + 1]["bin"] if index + 1 < len(families) else len(entries)
        family["motion_indices"] = [row["index"] for row in entries[family["bin"] + 1:end]
                                    if row["name"] in family["mot"] and row["kind"] == "motion"]
        # Duplicate AFS names occur in the actual disc. Index identity avoids
        # accidentally taking another fighter's same-named motion bank.
        common_names = {"comon.mot", "anime_cm.bin", f"c_{family['nick']}.mot"}
        family["shared_indices"] = [row["index"] for row in entries if row["name"] in common_names]
        family["capabilities"] = dict(STATUS)
    return families


def inventory(game_dir, *, game_id, source_sha256=None):
    """Read the exact reviewed title and return reusable native-file identities."""
    _game_id(game_id)
    if source_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ValueError("Supplied upstream source SHA-256 must be a complete lowercase digest")
    root = _absolute(game_dir)
    _plain_path(root)
    xbe, archive = root / "default.xbe", root / "loadfile.afs"
    before = (_signature(xbe), _signature(archive))
    if before[0][0] > 8 * 1024**2:
        raise ToolUnavailable("DOA3 source executable exceeds its reviewed size bound")
    xbe_sha = _file_hash(xbe)
    if xbe_sha not in XBE_HASHES:
        raise ToolUnavailable("Native DOA3 assets require the exact reviewed USA executable")
    entries = _entries(archive)
    archive_sha = _file_hash(archive)
    if before != (_signature(xbe), _signature(archive)):
        raise ToolUnavailable("DOA3 native asset source changed during inventory")
    return {"schema": SCHEMA, "game_id": game_id, "title": "Dead or Alive 3 (USA)",
            "platform": "xbox", "title_id": "54430001",
            "source": {"xbe_name": xbe.name, "xbe_sha256": xbe_sha,
                       "archive_name": archive.name, "archive_sha256": archive_sha,
                       "source_sha256": source_sha256,
                       "source_sha256_verification": "caller_supplied" if source_sha256 else "not_supplied"},
            "members": entries, "fighters": _families(entries), "capabilities": dict(STATUS)}


def _selection(manifest, fighter, costume, entry_ids, all_assets):
    if type(all_assets) is not bool:
        raise ValueError("all_assets must be an explicit boolean")
    if sum((fighter is not None, costume is not None, entry_ids is not None, bool(all_assets))) != 1:
        raise ValueError("Choose exactly one native selection: fighter, costume, entry_ids or all_assets")
    entries, families = manifest["members"], manifest["fighters"]
    if entry_ids is not None:
        if not isinstance(entry_ids, (list, tuple)) or len(entry_ids) > MAX_EXPORT_MEMBERS \
                or any(type(i) is not int or not 0 <= i < len(entries) for i in entry_ids):
            raise ValueError("Native member selection requires existing integer AFS indices")
        indices, selected = set(entry_ids), {"scope": "members", "indices": sorted(set(entry_ids))}
    elif all_assets:
        indices = {row["index"] for row in entries if row["kind"] != "placeholder"}
        selected = {"scope": "all_native_assets"}
    else:
        hits = [row for row in families if row["nick"] == fighter] if fighter is not None else [row for row in families if costume in row["costumes"]]
        if len(hits) != 1:
            raise ValueError("Native fighter/costume selection has no unique archive family")
        family = hits[0]
        chosen = family["costumes"] if costume is None else {costume: family["costumes"][costume]}
        if not chosen or any(set(pair) != {"xpr", "cat"} for pair in chosen.values()):
            raise ToolUnavailable("Native costume selection needs complete XPR/CAT companions")
        indices = {family["bin"], *family["motion_indices"], *family["shared_indices"],
                   *(value for pair in chosen.values() for value in pair.values())}
        selected = {"scope": "fighter" if costume is None else "costume", "fighter": family["nick"],
                    "costumes": sorted(chosen)}
    rows = [entries[index] for index in sorted(indices)]
    if not rows or len(rows) > MAX_EXPORT_MEMBERS or sum(row["size"] for row in rows) > MAX_EXPORT_BYTES:
        raise ToolUnavailable("Native member selection exceeds the bounded bundle budget or is empty")
    if any(row["kind"] == "placeholder" for row in rows):
        raise ToolUnavailable("Placeholder AFS members are not reusable assets")
    return rows, selected


def _validate_bundle(folder, manifest):
    _plain_path(folder)
    try:
        metadata = folder / "manifest.json"
        _plain_path(metadata)
        if metadata.stat().st_size > 2 * 1024**2 or json.loads(metadata.read_text(encoding="utf8")) != manifest:
            raise ToolUnavailable("Existing native bundle metadata differs from its source identity")
        expected = {"manifest.json", *(row["path"] for row in manifest["members"])}
        actual = set()
        for path in folder.rglob("*"):
            _plain_path(path)
            if path.is_file():
                actual.add(path.relative_to(folder).as_posix())
        if actual != expected:
            raise ToolUnavailable("Existing native bundle has missing or unexpected files")
        for row in manifest["members"]:
            path = folder / row["path"]
            if path.stat().st_size != row["size"] or _file_hash(path) != row["sha256"]:
                raise ToolUnavailable("Existing native bundle member content changed")
    except (OSError, ValueError) as error:
        raise ToolUnavailable("Existing native bundle cannot be verified; it was left unchanged") from error


def _bundle_families(families, indices):
    result = []
    for family in families:
        costumes = {key: pair for key, pair in family["costumes"].items()
                    if any(index in indices for index in pair.values())}
        if not costumes:
            continue
        required = {family["bin"], *family["motion_indices"], *family["shared_indices"],
                    *(index for pair in costumes.values() for index in pair.values())}
        result.append({**family, "costumes": costumes,
                       "complete_costumes": sorted(key for key, pair in costumes.items()
                                                   if set(pair) == {"xpr", "cat"} and set(pair.values()) <= indices),
                       "included_indices": sorted(required & indices),
                       "missing_companion_indices": sorted(required - indices)})
    return result


def export_selected(game_dir, output_root, *, game_id, fighter=None, costume=None,
                    entry_ids=None, all_assets=False, source_sha256=None, progress=lambda *_: None):
    """Export only selected native bytes to a checked, atomic, reusable bundle."""
    root, destination = _absolute(game_dir), _absolute(output_root)
    _plain_path(destination)
    if destination == root or destination.is_relative_to(root):
        raise ValueError("Native asset output must stay outside the source game folder")
    progress(5, "Checking the reviewed DOA3 native asset source")
    source = inventory(root, game_id=game_id, source_sha256=source_sha256)
    rows, selection = _selection(source, fighter, costume, entry_ids, all_assets)
    members = [{key: value for key, value in row.items() if key != "offset"} |
               {"path": f"members/{row['index']:06d}_{row['name']}"} for row in rows]
    manifest = {key: source[key] for key in ("schema", "game_id", "title", "title_id", "platform", "source", "capabilities")}
    manifest.update({"selection": selection, "members": members,
                     "fighters": _bundle_families(source["fighters"], {row["index"] for row in rows}),
                     "counts": {"members": len(members), "bytes": sum(row["size"] for row in rows)}})
    identity = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    destination.mkdir(parents=True, exist_ok=True)
    _plain_path(destination)
    folder = destination / f"doa3-native-{identity[:24]}"
    if folder.exists():
        _validate_bundle(folder, manifest)
        return {**manifest, "bundle_dir": str(folder), "reused": True}
    stage = destination / f"doa3-stage-{uuid.uuid4().hex}"
    stage.mkdir()
    (stage / "members").mkdir()
    try:
        archive = root / "loadfile.afs"
        with archive.open("rb") as stream:
            for index, (row, member) in enumerate(zip(rows, members)):
                progress(20 + 65 * index / len(rows), f"Preserving native asset {row['name']}")
                stream.seek(row["offset"])
                left, digest = row["size"], hashlib.sha256()
                with (stage / member["path"]).open("xb") as output:
                    while left:
                        block = stream.read(min(left, 1024**2))
                        if not block:
                            raise ToolUnavailable("DOA3 native asset source became incomplete")
                        output.write(block)
                        digest.update(block)
                        left -= len(block)
                if digest.hexdigest() != row["sha256"]:
                    raise ToolUnavailable("DOA3 native asset changed during extraction")
        if _file_hash(archive) != source["source"]["archive_sha256"] or _file_hash(root / "default.xbe") != source["source"]["xbe_sha256"]:
            raise ToolUnavailable("DOA3 native asset source changed before bundle publication")
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf8")
        _validate_bundle(stage, manifest)
        stage.rename(folder)
        progress(100, "Native asset bundle ready; model decoding and reimport remain unsupported")
        return {**manifest, "bundle_dir": str(folder), "reused": False}
    finally:
        if stage.exists():
            # The UUID stage is created under our selected output directory;
            # refuse cleanup through any unexpected links or changed location.
            if stage.absolute().parent != destination or not stage.name.startswith("doa3-stage-"):
                raise ToolUnavailable("Native asset staging cleanup path changed")
            for path in (stage, *stage.rglob("*")):
                _plain_path(path)
            shutil.rmtree(stage)
