"""Bounded native-asset access for the user's SaveMGO installation.

Only NPMG00020/USRDIR game resources are eligible. Saves, RPCN credentials,
emulator configuration and executables are never collected. MDN/TXN exports are
native game assets, not decoded GLB/PNG or verified cross-game replacements.

Archive layout and encryption research: Jayveer/Solideye (MIT),
https://github.com/Jayveer/Solideye . This is an independent Python reader.
The format constants below are game-format constants, not account credentials.

The reference README declares the MIT license without a copyright notice.
No third-party source text is embedded here; no holder or year is guessed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import uuid
import wave

TITLE_ID = "NPMG00020"
MAX_FILES = 10_000
MAX_MEMBERS = 8192
MAX_ARCHIVE_BYTES = 64 * 1024**2
MAX_MEMBER_BYTES = 128 * 1024**2
MAX_SCAN_BYTES = 1024**3
MAX_EXPORT_BYTES = 512 * 1024**2
MAX_EXPORT_FILES = 2048
MAX_FULL_EXPORT_BYTES = 12 * 1024**3
MAX_NATIVE_FILE_BYTES = 4 * 1024**3
MAX_MANIFEST_BYTES = 16 * 1024**2
STREAM_CHUNK_BYTES = 1024**2
_BASE = (0xD1F59885C26DF674, 0xD64455CECA2DAC72, 0x6805A2BE051DF165, 0x0E8935EB9D526CE7,
         0x3F9C5DFE24FF32C3, 0x265B0547CF8941B3, 0x46B5469A63CCE4F9, 0x4E8E5BE641DF0454)
_WRAPPED = (0x55C90C7288570853, 0xED8C980ACA5FA7D1, 0x049ADAFD8BBACF84, 0x24DC27E04DFBF06A,
            0x28CA270D1136B6B2, 0x9325211259B10A4E, 0x530B3A635C942DB5, 0xEED10EF7641BD497)
_EXTENSIONS = {".dbm", ".bgm", ".ssp", ".spc", ".dat", ".slot", ".qar", ".dar", ".dlz", ".dld",
               ".geom", ".ptl", ".vfp", ".dci", ".cnf", ".nni", ".gcx", ".gsp"}
_KINDS = {".mdn": "models", ".mtar": "animations", ".txn": "textures", ".img": "images",
          ".dlz": "texture_containers", ".dld": "texture_indexes", ".slot": "character_containers",
          ".dar": "archives", ".qar": "texture_containers", ".geom": "environments",
          ".bgm": "music", ".dbm": "music", ".ssp": "soundpacks", ".spc": "speech"}
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def _plain(path: Path, *, must_exist: bool = True) -> Path:
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        try:
            stat = part.lstat()
        except FileNotFoundError:
            if must_exist and part == path:
                raise ValueError(f"Missing resource: {path.name}") from None
            continue
        if part.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
            raise ValueError("Symlinks and Windows reparse points are not asset sources or destinations")
    return path


def data_root(path: Path) -> Path:
    """Accept an exact content root or the verified prepared RPCS3 home."""
    path = _plain(Path(path))
    if path.name != "USRDIR" or path.parent.name != TITLE_ID:
        path = _plain(path / "dev_hdd0" / "game" / TITLE_ID / "USRDIR")
    if not path.is_dir():
        raise ValueError("SaveMGO NPMG00020 content directory is unavailable")
    return path


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024 or any(c in value for c in '\\:*?<>|"') or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid relative asset path")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(part in (".", "..") or part.endswith((" ", ".")) or part.split(".")[0].casefold() in _RESERVED for part in path.parts):
        raise ValueError("Unsafe relative asset path")
    return value


def _eligible(relative: str) -> bool:
    p = PurePosixPath(relative)
    if p.suffix.lower() not in _EXTENSIONS:
        return False
    parts = p.parts
    if parts[0] in {"dbm", "sdpack", "speech"}:
        return True
    resources = {"stage", "slotdat", "bgm", "shader", "sdpack", "sdpack_e", "speech", "speech_e"}
    if len(parts) >= 3 and parts[0] == "o" and parts[1] in resources:
        return True
    if len(parts) >= 5 and parts[:3] == ("o", "dl", "p") and parts[3] in resources:
        return True
    if len(parts) == 4 and parts[:3] == ("o", "dl", "p") and parts[3] in {"lippatch.dat", "lippatch_e.dat", "vox_ex1.dat", "vox_ex3.dat"}:
        return True
    return len(parts) == 2 and parts[0] == "o" and parts[1].endswith(("_n.dat", "_ne.dat"))


def _source(root: Path, relative: str) -> Path:
    relative = _relative(relative)
    if not _eligible(relative):
        raise ValueError("This path is not an eligible game asset; saves, configuration and executables are excluded")
    path = _plain(root.joinpath(*PurePosixPath(relative).parts))
    if not path.is_file() or not path.is_relative_to(root):
        raise ValueError("Asset is outside the verified content directory")
    return path


def _identity(path: Path) -> tuple:
    s = path.stat()
    return s.st_size, s.st_mtime_ns, s.st_ino, s.st_dev


def _read(path: Path, limit: int) -> bytes:
    before = _identity(path)
    if before[0] > limit:
        raise ValueError("Asset exceeds the bounded read limit")
    with path.open("rb") as handle:
        value = handle.read(limit + 1)
    if len(value) > limit or len(value) != before[0] or _identity(path) != before:
        raise ValueError("Asset changed during reading")
    return value


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _cancelled(cancel) -> None:
    if cancel and cancel():
        raise InterruptedError("Asset export cancelled")


def _stream(source: Path, *, expected: tuple | None = None, output: Path | None = None,
            cancel=None, on_chunk=None) -> tuple[str, int, tuple]:
    """Hash or copy with bounded memory and unchanged source identity."""
    _plain(source)
    before = _identity(source)
    if expected is not None and before != expected:
        raise ValueError("Asset changed after export planning")
    digest, count = hashlib.sha256(), 0
    _cancelled(cancel)
    with source.open("rb") as reader:
        opened = os.fstat(reader.fileno())
        if (opened.st_size, opened.st_mtime_ns, opened.st_ino, opened.st_dev) != before:
            raise ValueError("Asset changed while opening")
        writer = output.open("xb") if output else None
        try:
            while True:
                _cancelled(cancel)
                chunk = reader.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                count += len(chunk)
                if count > before[0]:
                    raise ValueError("Asset grew during reading")
                digest.update(chunk)
                if writer:
                    writer.write(chunk)
                if on_chunk:
                    on_chunk(len(chunk))
        finally:
            if writer:
                writer.close()
        finished = os.fstat(reader.fileno())
    _plain(source)
    if count != before[0] or _identity(source) != before or (finished.st_size, finished.st_mtime_ns, finished.st_ino, finished.st_dev) != before:
        raise ValueError("Asset changed during reading")
    return digest.hexdigest(), count, before


def _candidates(root: Path, *, max_files: int = MAX_FILES):
    count = 0
    def failed(error):
        raise error
    for current, directories, filenames in os.walk(root, followlinks=False, onerror=failed):
        directories.sort()
        for name in directories:
            _plain(Path(current) / name)
        for name in sorted(filenames):
            count += 1
            if count > max_files:
                raise ValueError("Content tree exceeds its file limit")
            yield _plain(Path(current) / name)


def _destination(root: Path, destination: Path) -> Path:
    parent = _plain(Path(destination), must_exist=False)
    if parent.is_relative_to(root):
        raise ValueError("Asset output must be outside the immutable game content directory")
    return parent


def _fingerprint(value: str) -> str:
    if value and not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Source fingerprint must be a SHA256 value")
    return value


def _kind(name: str) -> dict:
    extension = PurePosixPath(name).suffix.lower()
    return {"kind": _KINDS.get(extension, "native_assets"), "format": extension.lstrip(".") or "native", "state": "native_only",
            "readiness": {"native_export": True, "decoded": False, "cross_game_ready": False, "reimportable": False}}


def _audio_header(head: bytes) -> dict | None:
    if head[:4] == b"DLBM":
        offset, container = 0x820, "DLBM/KCEJ"
    elif head[:4] == b"\0\0\0\x10":
        offset, container = 0x20, "KCEJ"
    elif head[:4] == b"MTA2":
        offset, container = 0, "MTA2"
    else:
        return None
    if len(head) < offset + 0x80 or head[offset:offset + 4] != b"MTA2" or head[offset + 0x40:offset + 0x44] != b"HEAD":
        return None
    channels = struct.unpack_from(">H", head, offset + 0x56)[0]
    rate = struct.unpack_from(">f", head, offset + 0x7C)[0] or 48000
    start, end = struct.unpack_from(">II", head, offset + 0x58)
    if not 1 <= channels <= 64 or not math.isfinite(rate) or not 8000 <= rate <= 192000 or not 0 < end < 2**31 or start > end:
        return None
    return {"codec": "MTA2", "container": container, "channels": channels, "sample_rate": int(rate),
            "samples": end, "loop_start": start, "loop_end": end, "duration_s": round(end / rate, 3),
            "decoder": "vgmstream", "decoded": False}


def _stage(relative: str) -> str:
    parts = PurePosixPath(relative).parts
    try:
        i = parts.index("stage")
    except ValueError:
        raise ValueError("Encrypted DAR/QAR requires its original logical stage path") from None
    if len(parts) != i + 3 or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", parts[i + 1]):
        raise ValueError("Invalid logical stage directory")
    return "stage/" + parts[i + 1]


def _stage_key(stage: str) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, modes
        try:
            from cryptography.hazmat.decrepit.ciphers.algorithms import Blowfish
        except ImportError:
            from cryptography.hazmat.primitives.ciphers.algorithms import Blowfish
    except ImportError:
        raise RuntimeError("MGO archive decryption requires the existing cryptography package") from None
    decrypt = Cipher(Blowfish(struct.pack("<8Q", *_BASE)[8:]), modes.ECB()).decryptor()
    words = struct.unpack("<8Q", decrypt.update(struct.pack("<8Q", *_WRAPPED)) + decrypt.finalize())
    unwrapped = struct.pack("<8Q", *(word ^ (_BASE[0] if i == 0 else _WRAPPED[i - 1]) for i, word in enumerate(words)))
    folder = hashlib.md5(stage.encode("ascii")).digest()
    return bytes(value ^ folder[i % 16] for i, value in enumerate(unwrapped))


def _decrypt(blob: bytes, stage: str) -> bytes:
    if len(blob) < 32:
        raise ValueError("Truncated encrypted archive")
    key = _stage_key(stage)
    if not hmac.compare_digest(hmac.new(key, blob[:-16], hashlib.md5).digest(), blob[-16:]):
        raise ValueError("Archive checksum does not match its original logical stage")
    words = struct.unpack("<8Q", key)
    decoded = bytearray(blob)
    previous = words[0]
    for index in range((len(blob) - 16) // 8):
        value = struct.unpack_from("<Q", blob, index * 8)[0]
        struct.pack_into("<Q", decoded, index * 8, value ^ previous ^ words[index % 7 + 1])
        previous = value
    return bytes(decoded[:-24])


def _name(data: bytes, start: int, end: int) -> tuple[str, int]:
    nul = data.find(b"\0", start, min(end, start + 257))
    if nul <= start:
        raise ValueError("Invalid archive member name")
    try:
        name = data[start:nul].decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("Invalid archive member name") from None
    return _relative(name), nul + 1


def _index(data: bytes, extension: str) -> list[dict]:
    if len(data) < 4:
        raise ValueError("Truncated archive index")
    rows, seen = [], set()
    if extension == ".dar":
        count = struct.unpack_from(">I", data)[0]
        if not 0 < count <= MAX_MEMBERS:
            raise ValueError("Invalid DAR member count")
        position = 4
        for index in range(count):
            name, position = _name(data, position, len(data))
            position = (position + 3) & ~3
            if position + 4 > len(data):
                raise ValueError("Truncated DAR member size")
            size = struct.unpack_from(">I", data, position)[0]
            position = (position + 4 + 15) & ~15
            if size > MAX_MEMBER_BYTES or position + size > len(data):
                raise ValueError("DAR member exceeds archive bounds")
            rows.append({"index": index, "name": name, "offset": position, "size": size})
            position += size + 1
    elif extension == ".qar":
        offset = struct.unpack_from(">I", data, len(data) - 4)[0]
        if not 4 <= offset <= len(data) - 8:
            raise ValueError("Invalid QAR index offset")
        count = struct.unpack_from(">H", data, offset)[0]
        if not 0 < count <= MAX_MEMBERS or offset + 4 + count * 8 > len(data) - 4:
            raise ValueError("Invalid QAR member count")
        position, payload = offset + 4 + count * 8, 0
        for index in range(count):
            name, position = _name(data, position, len(data) - 4)
            size = struct.unpack_from(">I", data, offset + 8 + index * 8)[0]
            if size > MAX_MEMBER_BYTES or payload + size > offset:
                raise ValueError("QAR member exceeds payload bounds")
            rows.append({"index": index, "name": name, "offset": payload, "size": size})
            payload = (payload + size + 127) & ~127
    else:
        raise ValueError("Only DAR/QAR native archive indexing is implemented")
    for row in rows:
        if row["name"].casefold() in seen:
            raise ValueError("Duplicate archive member path")
        seen.add(row["name"].casefold())
        row.update(_kind(row["name"]))
    return rows


def _archive(root: Path, relative: str) -> tuple[dict, bytes]:
    path = _source(root, relative)
    if path.suffix.lower() not in {".dar", ".qar"}:
        raise ValueError("This asset is not a DAR/QAR archive")
    blob = _read(path, MAX_ARCHIVE_BYTES)
    stage = _stage(relative)
    decoded = _decrypt(blob, stage)
    rows = _index(decoded, path.suffix.lower())
    return {"path": relative, "sha256": _digest(blob), "size": len(blob), "logical_stage": stage,
            "checksum_verified": True, "members": rows}, decoded


def archive_index(path: Path, relative_path: str) -> dict:
    """Return verified native member metadata; no decrypted payload is returned."""
    return _archive(data_root(path), relative_path)[0]


def inventory(path: Path, *, source_fingerprint: str = "", include_members: bool = False, progress=None) -> dict:
    root = data_root(path)
    fingerprint = _fingerprint(source_fingerprint)
    entries, indexed, issues, scanned = [], 0, [], 0
    for candidate in _candidates(root):
        relative = candidate.relative_to(root).as_posix()
        if not _eligible(relative):
            continue
        if len(entries) >= MAX_FILES:
            raise ValueError("Content inventory exceeds its file limit")
        source = _source(root, relative)
        size = source.stat().st_size
        item = {"id": relative, "path": relative, "name": source.name, "size": size, **_kind(relative)}
        if source.suffix.lower() in {".bgm", ".dbm"}:
            with source.open("rb") as stream:
                audio = _audio_header(stream.read(0x2000))
            if audio:
                item["audio"] = audio
        if include_members and source.suffix.lower() in {".dar", ".qar"}:
            if scanned + size > MAX_SCAN_BYTES:
                raise ValueError("Archive inventory exceeds its total read budget")
            scanned += size
            try:
                index, _ = _archive(root, relative)
                item.update(sha256=index["sha256"], checksum_verified=True, members=index["members"])
                indexed += 1
            except (ValueError, RuntimeError) as error:
                issues.append({"path": relative, "reason": str(error)})
        entries.append(item)
        if progress and len(entries) % 25 == 0:
            progress({"files": len(entries), "indexed_archives": indexed})
    return {"schema": 1, "title_id": TITLE_ID, "source_fingerprint": fingerprint,
            "fingerprint_verification": "caller_supplied" if fingerprint else "not_provided",
            "assets": entries, "summary": {"files": len(entries), "bytes": sum(e["size"] for e in entries),
            "indexed_archives": indexed, "archive_members": sum(len(e.get("members", [])) for e in entries)},
            "issues": issues, "readiness": {"native_export": True, "encrypted_dar_qar": True,
            "decoded_models": False, "decoded_textures": False, "decoded_environments": False,
            "combined_cast_writer": False, "music_decoder": find_vgmstream() is not None}}


def _bundle_valid(directory: Path, manifest: dict, *, cancel=None, progress=None) -> bool:
    try:
        _plain(directory)
        if json.loads(_read(_plain(directory / "manifest.json"), MAX_MANIFEST_BYTES)) != manifest:
            return False
        wanted = {"manifest.json", *(row["output"] for row in manifest["files"])}
        actual = set()
        for item in _candidates(directory, max_files=MAX_FILES + 1):
            _cancelled(cancel)
            if item.is_file():
                actual.add(item.relative_to(directory).as_posix())
        if actual != wanted:
            return False
        verified, total = 0, sum(row["size"] for row in manifest["files"])
        for index, row in enumerate(manifest["files"]):
            def heartbeat(size):
                nonlocal verified
                verified += size
                if progress:
                    progress({"phase": "verify", "files": index, "total_files": len(manifest["files"]),
                              "bytes": verified, "total_bytes": total, "path": row["source_path"]})
            if _stream(_plain(directory.joinpath(*PurePosixPath(row["output"]).parts)), cancel=cancel,
                       on_chunk=heartbeat)[:2] != (row["sha256"], row["size"]):
                return False
        return True
    except InterruptedError:
        raise
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return False


def _remove_stage(stage: Path, parent: Path) -> None:
    # Only this invocation's checked UUID staging directory can be deleted.
    _plain(stage)
    if stage.parent != parent or not re.fullmatch(r"\.savemgo-[0-9a-f]{32}", stage.name) or stage.resolve().parent != parent.resolve():
        raise ValueError("Refusing to remove an unowned staging directory")
    shutil.rmtree(stage)


def export(path: Path, destination: Path, *, paths: list[str] | None = None, members: list[dict] | None = None,
           source_fingerprint: str = "", progress=None, cancel=None) -> dict:
    """Export selected native files/members to an immutable, verified private bundle."""
    root = data_root(path)
    if paths == ["*"]:
        if members:
            raise ValueError("Full native export and individual member selection are separate operations")
        return export_all(root, destination, source_fingerprint=source_fingerprint, progress=progress, cancel=cancel)
    parent = _destination(root, destination)
    fingerprint = _fingerprint(source_fingerprint)
    originals = sorted(set(_relative(value) for value in paths or []))
    selections = sorted({(_relative(row["archive"]), _relative(row["name"])) for row in members or []})
    if not originals and not selections:
        raise ValueError("Select native assets or archive members to export")
    if len(originals) + len(selections) > MAX_EXPORT_FILES:
        raise ValueError("Too many selected assets")
    planned, total, archive_bytes = [], 0, 0
    for relative in originals:
        _cancelled(cancel)
        source = _source(root, relative)
        if total + source.stat().st_size > MAX_EXPORT_BYTES:
            raise ValueError("Selected assets exceed the export byte limit")
        blob = _read(source, MAX_MEMBER_BYTES)
        total += len(blob)
        planned.append(({"output": "native/" + relative, "source_path": relative, "size": len(blob),
                         "sha256": _digest(blob), **_kind(relative)}, blob))
    current_archive = None
    for relative, name in selections:
        _cancelled(cancel)
        if relative != current_archive:
            source = _source(root, relative)
            archive_bytes += source.stat().st_size
            if archive_bytes > MAX_SCAN_BYTES:
                raise ValueError("Selected archives exceed the total read budget")
            archive, decoded = _archive(root, relative)
            current_archive = relative
        row = next((row for row in archive["members"] if row["name"] == name), None)
        if row is None:
            raise ValueError("Selected member does not exist in the authenticated archive")
        if total + row["size"] > MAX_EXPORT_BYTES:
            raise ValueError("Selected assets exceed the export byte limit")
        blob = decoded[row["offset"]:row["offset"] + row["size"]]
        total += len(blob)
        planned.append(({"output": "members/" + relative + "/" + name, "source_path": relative,
                         "archive_sha256": archive["sha256"], "logical_stage": archive["logical_stage"],
                         "archive_checksum_verified": True, "member": name, "member_index": row["index"],
                         "size": len(blob), "sha256": _digest(blob), **_kind(name)}, blob))
    if total > MAX_EXPORT_BYTES:
        raise ValueError("Selected assets exceed the export byte limit")
    manifest = {"schema": 1, "title_id": TITLE_ID, "source_fingerprint": fingerprint,
                "fingerprint_verification": "caller_supplied" if fingerprint else "not_provided",
                "native_only": True, "decoded_models": False, "decoded_textures": False,
                "files": sorted((row for row, _ in planned), key=lambda row: row["output"])}
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    bundle_id = _digest(canonical)
    parent.mkdir(parents=True, exist_ok=True)
    _plain(parent)
    final = _plain(parent / bundle_id, must_exist=False)
    if final.exists():
        if not _bundle_valid(final, manifest, cancel=cancel, progress=progress):
            raise ValueError("Existing asset bundle is incomplete or has changed")
        return {"state": "exported", "bundle_id": bundle_id, "directory": str(final),
                "manifest": str(final / "manifest.json"), "files": manifest["files"], "bytes": total, "reused": True}
    if shutil.disk_usage(parent).free < total + 64 * 1024**2:
        raise ValueError("Not enough free disk space for the native asset bundle and reserve")
    stage = parent / (".savemgo-" + uuid.uuid4().hex)
    stage.mkdir()
    try:
        for index, (row, blob) in enumerate(planned):
            _cancelled(cancel)
            output = stage.joinpath(*PurePosixPath(row["output"]).parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(blob)
            if progress:
                progress({"phase": "copy", "files": index + 1, "total_files": len(planned), "path": row["source_path"]})
        (stage / "manifest.json").write_bytes(canonical)
        if not _bundle_valid(stage, manifest, cancel=cancel, progress=progress):
            raise ValueError("Exported asset bundle failed verification")
        if final.resolve().parent != parent.resolve():
            raise ValueError("Asset bundle destination escaped its output directory")
        try:
            stage.rename(final)
        except OSError:
            if not final.exists() or not _bundle_valid(final, manifest, cancel=cancel, progress=progress):
                raise
            _remove_stage(stage, parent)
    finally:
        if stage.exists():
            _remove_stage(stage, parent)
    return {"state": "exported", "bundle_id": bundle_id, "directory": str(final),
            "manifest": str(final / "manifest.json"), "files": manifest["files"], "bytes": total, "reused": False}


def export_all(path: Path, destination: Path, *, source_fingerprint: str = "", progress=None,
               cancel=None, max_bytes: int = MAX_FULL_EXPORT_BYTES) -> dict:
    """Stream every eligible native resource; archives remain original encrypted files.

    A metadata/hash pass fixes a source snapshot before any output is created.
    The second pass copies and rechecks that snapshot. No model/texture conversion
    or archive-member extraction is implied by a successful native bundle.
    """
    root = data_root(path)
    parent = _destination(root, destination)
    fingerprint = _fingerprint(source_fingerprint)
    if not isinstance(max_bytes, int) or not 0 < max_bytes <= MAX_FULL_EXPORT_BYTES:
        raise ValueError("Full native export budget must be positive and at most 12 GiB")
    planned, total, seen = [], 0, set()
    for candidate in _candidates(root):
        _cancelled(cancel)
        relative = candidate.relative_to(root).as_posix()
        if not _eligible(relative):
            continue
        source = _source(root, relative)
        size = source.stat().st_size
        if size > MAX_NATIVE_FILE_BYTES or total + size > max_bytes:
            raise ValueError("Native assets exceed the full-export file or total disk budget")
        if relative.casefold() in seen:
            raise ValueError("Duplicate native output path")
        seen.add(relative.casefold())
        total += size
        planned.append((relative, source, _identity(source)))
    if not planned:
        raise ValueError("No eligible native game assets were found")
    rows, identities, hashed = [], {}, 0
    for index, (relative, source, identity) in enumerate(planned):
        def hashing(size):
            nonlocal hashed
            hashed += size
            if progress:
                progress({"phase": "hash", "files": index, "total_files": len(planned),
                          "bytes": hashed, "total_bytes": total, "path": relative})
        sha, size, identity = _stream(source, expected=identity, cancel=cancel, on_chunk=hashing)
        rows.append({"output": "native/" + relative, "source_path": relative, "size": size,
                     "sha256": sha, **_kind(relative)})
        identities[relative] = identity
    rows.sort(key=lambda row: row["output"])
    manifest = {"schema": 1, "title_id": TITLE_ID, "source_fingerprint": fingerprint,
                "fingerprint_verification": "caller_supplied" if fingerprint else "not_provided",
                "native_only": True, "decoded_models": False, "decoded_textures": False, "files": rows}
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    if len(canonical) > MAX_MANIFEST_BYTES:
        raise ValueError("Native manifest exceeds its size budget")
    bundle_id = _digest(canonical)
    parent.mkdir(parents=True, exist_ok=True)
    _plain(parent)
    final = _plain(parent / bundle_id, must_exist=False)
    result = {"state": "exported", "bundle_id": bundle_id, "directory": str(final),
              "manifest": str(final / "manifest.json"), "files": rows, "bytes": total,
              "native_only": True, "archives_unpacked": False}
    if final.exists():
        if not _bundle_valid(final, manifest, cancel=cancel, progress=progress):
            raise ValueError("Existing asset bundle is incomplete or has changed")
        return {**result, "reused": True}
    if shutil.disk_usage(parent).free < total + 64 * 1024**2:
        raise ValueError("Not enough free disk space for the native asset bundle and reserve")
    _cancelled(cancel)
    stage = parent / (".savemgo-" + uuid.uuid4().hex)
    stage.mkdir()
    copied = 0
    try:
        for index, row in enumerate(rows):
            relative = row["source_path"]
            output = stage.joinpath(*PurePosixPath(row["output"]).parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            def copying(size):
                nonlocal copied
                copied += size
                if progress:
                    progress({"phase": "copy", "files": index, "total_files": len(rows),
                              "bytes": copied, "total_bytes": total, "path": relative})
            sha, size, _ = _stream(_source(root, relative), expected=identities[relative],
                                    output=output, cancel=cancel, on_chunk=copying)
            if (sha, size) != (row["sha256"], row["size"]):
                raise ValueError("Copied asset does not match its planned source")
        _cancelled(cancel)
        (stage / "manifest.json").write_bytes(canonical)
        if not _bundle_valid(stage, manifest, cancel=cancel, progress=progress):
            raise ValueError("Exported asset bundle failed verification")
        try:
            stage.rename(final)
        except OSError:
            if not final.exists() or not _bundle_valid(final, manifest, cancel=cancel, progress=progress):
                raise
            _remove_stage(stage, parent)
    finally:
        if stage.exists():
            _remove_stage(stage, parent)
    if progress:
        progress({"phase": "complete", "files": len(rows), "total_files": len(rows), "bytes": total, "total_bytes": total})
    return {**result, "reused": False}


def find_vgmstream(configured: Path | None = None) -> Path | None:
    """Find an existing decoder only; never download or provision executables."""
    value = str(configured) if configured else shutil.which("vgmstream-cli") or shutil.which("vgmstream-cli.exe")
    if not value:
        return None
    path = _plain(Path(value))
    return path if path.is_file() else None


def decode_music(path: Path, relative_path: str, destination: Path, *, decoder: Path | None = None) -> dict:
    """Decode a known MTA2 music resource with an already provisioned vgmstream."""
    root = data_root(path)
    parent = _destination(root, destination)
    source = _source(root, relative_path)
    if source.suffix.lower() not in {".bgm", ".dbm"}:
        raise ValueError("Music decoding accepts only MGO BGM/DBM resources")
    blob = _read(source, MAX_MEMBER_BYTES)
    metadata = _audio_header(blob[:0x2000])
    if metadata is None:
        raise ValueError("Music resource has no validated MTA2 header")
    if metadata["samples"] * metadata["channels"] * 2 + 128 > MAX_EXPORT_BYTES:
        raise ValueError("Decoded music exceeds the output byte budget")
    executable = find_vgmstream(decoder)
    if executable is None:
        return {"state": "decoder_unavailable", "native_export": True, "decoded": False,
                "reason": "An existing vgmstream-cli provision is required; no executable was downloaded", "audio": metadata}
    parent.mkdir(parents=True, exist_ok=True)
    output = parent / (".savemgo-" + uuid.uuid4().hex)
    output.mkdir()
    wav = output / "music.wav"
    try:
        subprocess.run([str(executable), "-i", "-o", str(wav), str(source)], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if _digest(_read(source, MAX_MEMBER_BYTES)) != _digest(blob):
            raise ValueError("Music source changed during conversion")
        value = _read(_plain(wav), MAX_EXPORT_BYTES)
        with wave.open(str(wav), "rb") as stream:
            if stream.getnchannels() != metadata["channels"] or stream.getframerate() != metadata["sample_rate"] or stream.getnframes() != metadata["samples"] or stream.getsampwidth() != 2:
                raise ValueError("Decoded WAV metadata does not match its source")
        sha = _digest(value)
        final = _plain(parent / (sha + ".wav"), must_exist=False)
        if final.exists():
            if _digest(_read(final, MAX_EXPORT_BYTES)) != sha:
                raise ValueError("Existing decoded music has changed")
        else:
            wav.rename(final)
        return {"state": "decoded", "decoded": True, "path": str(final), "sha256": sha, "size": len(value),
                "source_path": relative_path, "source_sha256": _digest(blob), "audio": metadata}
    finally:
        if output.exists():
            _remove_stage(output, parent)
