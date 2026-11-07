# RE4 VR (Quest): extracting bytes from the shipped paks

Measured 2026-11-06 on the Windows PC, against
`\\10.89.1.125\QuickSwap2\Emulation\Occulus\Resident Evil 4 VR (occulus).zip` (8,383,651,519 bytes, read in place).

**Status: byte extraction works.** The Oodle wall described in
[`re4-vr-deconstruction.md`](re4-vr-deconstruction.md) §"The one thing that stops extraction: Oodle" is gone: the reader
now accepts an Oodle decoder that the caller names explicitly, and four real entries have been pulled out of two
different paks and verified by length and MD5 (§5). This document supersedes that section; the rest of the
deconstruction note (layout, names, why it cannot be *played*) still stands.

Personal-use extraction from an owned copy. Nothing here grants or implies redistribution rights to Capcom/Armature
assets, and the decoder used below is another game's `oo2core` DLL under that game's own licence.

## 1. What changed in the reader (`system/gbox/ue_pak.py`)

The rule that matters is unchanged: **a decoder is never discovered outside the game folder**. What was added is one
explicit door for archives whose game is not installed here at all — an Android title links Oodle statically into
`libUE4.so` and ships no `oo2core_*` library, so "look in the game folder" can never succeed for it.

```python
class Oodle:
    PATTERN = re.compile(r"(?i)^oo2core_\d+_win64\.dll$")

    def __init__(self, dll, game_dir=None, allow_external=False):
        ...
```

| call | outcome |
|---|---|
| `Oodle(dll, game_dir)` with `dll` inside `game_dir` | loads (unchanged: the game's own DLL) |
| `Oodle(dll, game_dir)` with `dll` outside `game_dir` | `PakUnsupported`: "only an oo2core_*_win64.dll inside the game folder is used" |
| `Oodle(dll)` / `Oodle(dll, allow_external=False)` | `PakUnsupported`: a decoder outside the game folder must be named explicitly |
| `Oodle(dll, allow_external=True)`, name matches, is a file | loads; `Oodle.external` is `True` |
| `Oodle(dll, allow_external=True)`, wrong name / missing / not a DLL / no export | `PakUnsupported` (`OSError` from `ctypes` for a file that is not loadable) |

Everything else is deliberately untouched:

* `Oodle.find(game_dir)` still only globs inside `game_dir`, and `open_pak(..., game_dir=...)` still calls it. No
  new scan path exists anywhere.
* `OodleLZ_Decompress` is resolved with the same 14-argument signature and the same `c_ssize_t` return, and
  `decompress()` still refuses a result whose length is not exactly `raw_len` ("Oodle returned N bytes, expected M").
* New: the export is checked by name, so a wrong DLL fails with "exports no OodleLZ_Decompress" instead of an
  `AttributeError` from inside ctypes.
* New: `IS_WINDOWS` (module constant) replaces the inline `sys.platform` test so the platform gate is a single,
  testable fact.

The entry point grew one keyword:

```python
def open_pak(path, game_dir=None, oodle_dll=None):
```

* `oodle_dll=` names a decoder outright. It is loaded as an external library, and the summary reports
  `"oodle_dll": "<name>", "oodle_external": True`.
* Without it, behaviour is exactly as before: the game's DLL is looked for in `game_dir`, and without `game_dir` Oodle
  entries stay unreadable with `"oodle_error"` saying so.
* A named decoder that cannot be used raises `PakUnsupported` (a bad argument, not an unreadable archive) and closes
  the pak handle. A broken DLL found *inside* a game folder is still only reported in the summary, so listing a game's
  paks never fails because of it.
* `decompress_block`'s refusal message now ends with the way out: "name a decoder explicitly with
  `open_pak(..., oodle_dll=<oo2core_*_win64.dll>)`".

Existing callers (`gbox/ue_steam.py`, `gbox/decrypt_lab.py`) pass `(path, game_dir)` and are unaffected; the lab's
`POST /api/decrypt-lab/ue-pak` route does **not** pass a decoder, so it still refuses Oodle entries in a title like this.
Wiring `oodle_dll` into that route is a one-line change in `gbox/decrypt_lab.py`, which this work was not allowed to
touch.

## 2. Supplying a decoder

Both candidate libraries were checked with `ctypes` before anything was wired:

```python
import ctypes
lib = ctypes.WinDLL(r"D:\SteamLibrary\steamapps\common\ELDEN RING NIGHTREIGN\Game\oo2core_9_win64.dll")
fn = lib.OodleLZ_Decompress            # present; OodleLZ_Compress / OodleLZ_GetCompressedBufferSizeNeeded too
```

| DLL | size | `OodleLZ_Decompress` |
|---|---|---|
| `...\ELDEN RING NIGHTREIGN\Game\oo2core_9_win64.dll` | 643,584 | present (used for every result below) |
| `...\ARMORED CORE VI FIRES OF RUBICON\Game\oo2core_8_win64.dll` | 962,048 | present (not needed) |

The two shapes a caller uses:

```python
from gbox import ue_pak

# a pak on disk
pf, s = ue_pak.open_pak(r"...\pakchunk1-Android_ETC2.pak", oodle_dll=r"D:\...\oo2core_9_win64.dll")
data = pf.read("VR4/Content/Levels/BIO4/1st/r100/r100.umap")
s["oodle_dll"], s["oodle_external"]        # 'oo2core_9_win64.dll', True

# or the object directly
pf = ue_pak.PakFile(path, oodle=ue_pak.Oodle(r"D:\...\oo2core_9_win64.dll", allow_external=True))
```

There is no CLI for `ue_pak`; the lab route and `ue_steam` are the only front doors, and neither takes a decoder yet.

## 3. Archive layout that makes the route possible

Measured from the outer central directory and from the OBB's own zip64 directory:

| member | uncompressed | stored as | note |
|---|---|---|---|
| `com.Armature.VR4/` | 0 | — | directory entry |
| `com.Armature.VR4/main.203.com.Armature.VR4.obb` | 4,278,854,071 | deflate (4,268,836,483) | **80 members, all stored**, 18 paks |
| `com.Armature.VR4/patch.203.com.Armature.VR4.obb` | 4,233,911,336 | deflate | 2 paks: `pakchunk0` 4,206,242,657 + `pakchunk9optional` 27,668,163 |
| `com.Armature.VR4/VR4-Android-Shipping-arm64.apk` | 56,831,952 | deflate | the arm64 shell |
| `com.Armature.VR4.apk` | 56,831,952 | deflate | a second copy of the same APK |

Two facts decide the whole route:

1. **The OBBs are deflated inside the outer zip**, so the OBB cannot be entered at a chosen offset: reaching its
   central directory means inflating all 4.28 GB once, forwards. There is no random access into a deflate stream.
2. **The paks inside the OBB are stored**, so a byte range of an OBB member is a byte range of the pak. Once the
   directory is known, the raw bytes of any pak can be copied out of a second forward pass without materialising the
   multi-GB container.

The two paks used here (from the main OBB's stored members):

| pak | offset in OBB | size | entries |
|---|---|---|---|
| `VR4/Content/Paks/pakchunk0optional-Android_ETC2.pak` | 722,236,777 | 2,446,567,768 | 8,883 (`.uptnl` optional segments) |
| `VR4/Content/Paks/pakchunk1-Android_ETC2.pak` | 3,168,804,662 | 56,860,746 | 475 (`.umap`/`.uasset`/`.uexp`/`.ubulk`) |

Both are pak **v9** with a valid index SHA-1 and no encrypted entries — no AES key is involved for either pak.

Because chunk0optional sits *before* chunk1, a single forward pass to 3.23 GB captures everything needed: chunk1 in
full, chunk0optional's first 96 MB and its last 64 MB (its index lives at the end).

## 4. The route

Two passes over the OBB, no multi-GB local copy, ~8 GB of SMB traffic on a cold cache. Save the appendix script
anywhere (it keeps its work files in `%TEMP%\re4vr`):

```powershell
python re4vr_paks.py cd                            # pass 1: OBB zip64 directory -> %TEMP%\re4vr\cd.json
python re4vr_paks.py get                           # pass 2: capture windows, extract, print size + md5
python re4vr_paks.py get --pak1 "VR4/Content/..." --optional "VR4/Content/..."
```

Measured cost, cold SMB cache: one pass = 3.7 min at ~19.5 MB/s (`zipfile`'s own member reads manage ~14.5 MB/s;
reading raw 8 MB blocks and inflating them in-process is the difference). With the archive still in the client cache a
pass took 11 s. Disk: `%TEMP%\re4vr` holds `pakchunk1-Android_ETC2.pak` (56 MB) plus the two captured windows
(96 MB + 64 MB) — safe to delete, they are reversed from the archive.

The script is the appendix below. It has three parts worth naming:

* `inflate_member(f, member, targets, stop)` — one forward raw-inflate of the deflated OBB, copying only
  `[start, end)` windows into pre-allocated buffers and stopping once past the last wanted byte.
* `parse_central_directory(tail, tail_start)` — zip64 EOCD + central directory parsed out of the last 4 MB of that
  stream. It agrees with Python's `zipfile` on all 80 members (names, sizes, offsets) to the byte.
* `RangePak` — a `ue_pak.PakFile` whose `_f` is a seek/read object over the captured windows. The pak index, the
  inline `FPakEntry` headers, the block table, the `OodleLZ_Decompress` call and the length check are therefore the
  shipped code, not a special case: only the byte source differs.

## 5. Entries extracted

Four entries, two paks, each one decompressed by `oo2core_9_win64.dll`. In every case the number of bytes produced
equals the `FPakEntry` uncompressed size recorded in both the pak index and the inline header, which the reader
cross-checks before decompressing.

| pak | entry | stored | uncompressed | md5 |
|---|---|---|---|---|
| `pakchunk1` | `VR4/Content/Levels/BIO4/1st/r100/r100.umap` | 6,265 | 25,375 | `05aa870ff736cdf1556256b85df80e1a` |
| `pakchunk1` | `VR4/Content/Levels/BIO4/1st/r100/Lights/r100_Cabin_Exterior.umap` | 1,190 | 2,961 | `f1910a24ed1b6f5626276778fd5b9b26` |
| `pakchunk0optional` | `VR4/Content/Characters/BIO4/ANIMAL/em21_Dog/Textures/dog01.uptnl` | 538,275 | 655,360 | `e5f87e8e04205d54b486913f86eb098c` |
| `pakchunk0optional` | `Engine/Content/EditorMaterials/PreviewShadowIndicator.uptnl` | 647 | 262,144 | `56648027f984b4448e0a813a2a40d198` |

(`r100` is the village, `r100_Cabin_Exterior` a level's light script; `dog01` is the `em21_Dog` character texture set,
i.e. the same retail names the other editions use.)

Content is what the name says, not noise:

* `r100.umap` and `r100_Cabin_Exterior.umap` begin `c1 83 2a 9e f9 ff ff ff` — the UE4 package magic
  `0x9E2A83C1` and the legacy-file-version `-7` — and `gbox.ue_asset.parse_package` reads their export tables
  (`r100_Cabin_Lights.umap` → `BlueprintGeneratedClass r100_Cabin_Lights_C : LevelScriptActor`; the
  `_BuiltData.uasset` siblings → `LightMapTexture2D` ×4 + `MapBuildDataRegistry`).
* `dog01.uptnl` begins `43 3a 2b 4a …`, not a package magic: `.uptnl` is an *optional segment* payload that only
  means something alongside the base asset and its segment table, so it is verified as bytes, not as an asset.

Reproduce any of these without the big-pak dance by extracting `pakchunk1` once (§4) and then:

```python
pf, s = ue_pak.open_pak(r"%TEMP%\re4vr\pakchunk1-Android_ETC2.pak", oodle_dll=r"D:\...\oo2core_9_win64.dll")
assert s["oodle_external"] is True
print(pf.read("VR4/Content/Levels/BIO4/1st/r100/r100.umap")[:8].hex())      # c1832a9ef9ffffff
```

## 6. What is still out of reach

* **The base game content is in the patch OBB.** `pakchunk0` (4.2 GB, the pak that carries the base assets the
  `.uptnl` segments belong to) exists only inside `patch.203...obb`, not in the main OBB. It is reachable by exactly
  the same two-pass route, but it has not been run, so no base asset has been extracted. Until it is, an optional
  segment like `dog01.uptnl` is bytes without its owner.
* **Cooking-level asset conversion.** Packages open at the table level (header, names, imports, exports, class names —
  §5), but turning an export into geometry/texture/material data needs the title's exact engine version and the cooked
  layouts that go with it. These packages are unversioned, so `ue_asset` falls back to its 4.27 default
  (`ue4 == 522`); the real version is linked into `libUE4.so` and was not confirmed here. Property-level decoding is
  therefore unverified, and no converter (`.uasset` → UAP/glTF) has been run against this title.
* **Textures.** The `.uptnl` payloads are ETC2 texture data for Android. gBox has an ETC1 decoder for 3DS TEX files
  (`gbox/merc3d_tex.py`) but no UE4 `Texture2D` → ETC2 path, so nothing decodes these to an image yet.
* **Android runtime.** Unchanged from the deconstruction note: the content is an arm64 Android VR app
  (`libUE4.so`, `libOVRPlugin.so`, an OpenXR headset, no flat mode). The Spark has no Android userspace and no
  headset, so "view/replace assets" is the ceiling here; "play it in MercMode" is a different project.
* **The lab route.** `POST /api/decrypt-lab/ue-pak` still cannot pass a decoder (see §1), so an operator using the GUI
  gets the 409 until that one line is added.
* **No redistribution.** Nothing in this route changes the licensing position: personal-use extraction only.

## 7. Tests

`system/tests/test_ue_pak.py` gained five cases; the existing policy test still passes unchanged:

* `test_oodle_reads_through_an_explicitly_named_external_decoder` — a stub `ctypes.WinDLL` exporting
  `OodleLZ_Decompress`, and a tag "codec" (`b"STUB" + raw`) wired in as the pak's Oodle, so a full multi-block pak is
  compressed, listed and read through the real code path, length check included.
* `test_external_oodle_dll_still_needs_both_a_path_and_the_right_name` — no opt-in, a game folder it is not in, a
  wrong name, and a missing file are each refused.
* `test_oodle_is_never_discovered_next_to_the_archive` — an `oo2core_9_win64.dll` next to the pak stays unused and the
  read still raises; proves no scanning crept in.
* `test_oodle_byte_count_mismatch_is_refused`, `test_open_pak_refuses_an_unusable_explicit_decoder` — error paths.

```
cd system
$env:PYTHONPATH = "tests"        # ue_synth lives beside the tests
python -m pytest tests/test_ue_pak.py -q
# 68 passed, 4 skipped
```

The four skips are the pre-existing "compression arrived in pak v3" parameters.

## Appendix: `re4vr_paks.py`

```python
"""Read RE4 VR (Quest) .pak entries straight out of the 8.4 GB nested archive, on Windows.

    archive.zip -> com.Armature.VR4/main.<ver>.obb (deflated) -> VR4/Content/Paks/*.pak (stored) -> Oodle blocks

The OBB holds 80 entries and 18 paks; the paks are stored, so a byte range of the pak is a byte range of the OBB.
Only what is needed is inflated: the whole OBB for its zip64 directory, then one more pass that copies the wanted
windows (pakchunk1 in full, pakchunk0optional's head + tail). Nothing multi-GB is written anywhere.

Personal-use extraction from an owned copy; the Oodle decoder is a separately installed game's oo2core DLL, named
explicitly (gbox.ue_pak never discovers one outside a game folder).

    python re4vr_paks.py cd                      # pass 1: the OBB's central directory -> work/cd.json
    python re4vr_paks.py get                     # pass 2 + the four proven entries
    python re4vr_paks.py get --pak1 NAME --optional NAME
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import tempfile
import time
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")
from gbox import ue_pak                                           # noqa: E402

ZIP = Path(r"\\10.89.1.125\QuickSwap2\Emulation\Occulus\Resident Evil 4 VR (occulus).zip")
OBB = "com.Armature.VR4/main.203.com.Armature.VR4.obb"
PAK1 = "VR4/Content/Paks/pakchunk1-Android_ETC2.pak"
PAK0OPT = "VR4/Content/Paks/pakchunk0optional-Android_ETC2.pak"
DLL = Path(r"D:\SteamLibrary\steamapps\common\ELDEN RING NIGHTREIGN\Game\oo2core_9_win64.dll")

WORK = Path(tempfile.gettempdir()) / "re4vr"
CD_JSON = WORK / "cd.json"
HEAD_MB, TAIL_MB = 96, 64

EOCD, ZIP64_EOCD, ZIP64_LOC, CDH, LFH = 0x06054B50, 0x06064B50, 0x07064B50, 0x02014B50, 0x04034B50
CT = {0: "stored", 8: "deflate", 12: "bzip2", 14: "lzma", 99: "aes"}


# ------------------------------------------------------------------ outer zip / OBB stream

def member_layout(f, name: str):
    """(compressed size, uncompressed size, absolute offset of the member's first data byte)."""
    info = zipfile.ZipFile(f).getinfo(name)          # reads the outer central directory only
    f.seek(info.header_offset)
    hdr = f.read(30)
    if struct.unpack_from("<I", hdr, 0)[0] != LFH:
        raise SystemExit(f"{name}: no local file header at {info.header_offset}")
    name_len, extra_len = struct.unpack_from("<HH", hdr, 26)
    return info.compress_size, info.file_size, info.header_offset + 30 + name_len + extra_len


def inflate_member(f, name: str, targets=(), stop: int | None = None) -> int:
    """Inflate a deflated member once, copying [start, end) windows into each target's bytearray.

    Raw inflate in 8 MB reads: ~20 MB/s off the share, against ~14 MB/s through zipfile's small reads."""
    csize, _usize, start = member_layout(f, name)
    f.seek(start)
    d, left, pos, t0, mark = zlib.decompressobj(-15), csize, 0, time.time(), 0
    while left > 0:
        raw = f.read(min(8 << 20, left))
        if not raw:
            raise IOError(f"{name}: member ended after {csize - left} compressed bytes")
        left -= len(raw)
        out = d.decompress(raw)
        if out:
            for ts, te, buf in targets:
                lo, hi = max(pos, ts), min(pos + len(out), te)
                if lo < hi:
                    buf[lo - ts:lo - ts + (hi - lo)] = out[lo - pos:hi - pos]
            pos += len(out)
        if pos - mark >= (1 << 30):
            mark = pos
            print(f"  {pos / 1e6:.0f} MB, {pos / 1e6 / (time.time() - t0):.1f} MB/s", flush=True)
        if stop is not None and pos >= stop:
            break
    return pos


def parse_central_directory(tail: bytes, tail_start: int) -> list[dict]:
    """Zip64 central directory from a tail buffer that contains the end of the decompressed stream."""
    def u32(o): return struct.unpack_from("<I", tail, o)[0]
    def u64(o): return struct.unpack_from("<Q", tail, o)[0]

    eocd = tail.rfind(struct.pack("<I", EOCD))
    if eocd < 0:
        raise SystemExit("no end-of-central-directory record in the tail")
    cd_size, cd_off = u32(eocd + 12), u32(eocd + 16)
    total = struct.unpack_from("<H", tail, eocd + 10)[0]
    loc = eocd - 20
    if loc >= 0 and u32(loc) == ZIP64_LOC:
        at = u64(loc + 8) - tail_start
        if not 0 <= at < len(tail) or u32(at) != ZIP64_EOCD:
            raise SystemExit("zip64 end-of-central-directory record is outside the captured tail")
        total, cd_size, cd_off = u64(at + 32), u64(at + 40), u64(at + 48)
    base = cd_off - tail_start
    if base < 0 or base + cd_size > len(tail):
        raise SystemExit(f"central directory {cd_off}+{cd_size} is not in the captured tail")
    rows, p = [], base
    for _ in range(total):
        if u32(p) != CDH:
            raise SystemExit(f"bad central directory signature at {tail_start + p}")
        ctype, csize, usize = struct.unpack_from("<H", tail, p + 10)[0], u32(p + 20), u32(p + 24)
        nlen, elen, clen = struct.unpack_from("<HHH", tail, p + 28)
        hdr = u32(p + 42)
        name = tail[p + 46:p + 46 + nlen].decode("utf-8", "replace")
        extra = tail[p + 46 + nlen:p + 46 + nlen + elen]
        e = 0
        while e + 4 <= len(extra):                    # zip64 extended information
            hid, hlen = struct.unpack_from("<HH", extra, e)
            if hid == 0x0001:
                body, q = extra[e + 4:e + 4 + hlen], 0
                if usize == 0xFFFFFFFF and q + 8 <= len(body):
                    usize, q = struct.unpack_from("<Q", body, q)[0], q + 8
                if csize == 0xFFFFFFFF and q + 8 <= len(body):
                    csize, q = struct.unpack_from("<Q", body, q)[0], q + 8
                if hdr == 0xFFFFFFFF and q + 8 <= len(body):
                    hdr = struct.unpack_from("<Q", body, q)[0]
            e += 4 + hlen
        rows.append({"name": name, "size": usize, "csize": csize, "ctype": ctype, "hdr": hdr})
        p += 46 + nlen + elen + clen
    return rows


def build_cd(tail_mb: int = 4) -> dict:
    """Pass 1: inflate the OBB once to reach its directory (4.28 GB, ~4 min at 20 MB/s)."""
    WORK.mkdir(parents=True, exist_ok=True)
    with open(ZIP, "rb") as f:
        _c, usize, _s = member_layout(f, OBB)
        tail = bytearray(min(tail_mb << 20, usize))
        t0 = time.time()
        inflate_member(f, OBB, [(usize - len(tail), usize, tail)])
    rows = parse_central_directory(bytes(tail), usize - len(tail))
    for r in rows:
        r["ctype_name"] = CT.get(r["ctype"], str(r["ctype"]))
    out = {"zip": str(ZIP), "obb": OBB, "obb_size": usize, "secs": round(time.time() - t0, 1), "entries": rows}
    CD_JSON.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(rows)} entries in {out['secs']}s -> {CD_JSON}")
    return out


# ------------------------------------------------------------------ a pak inside the OBB

class _RangeReader:
    """File-like seek/read over captured windows; PakFile._read_at uses it unchanged."""

    def __init__(self, size: int, ranges):
        self.size, self._pos = size, 0
        self._ranges = sorted(((s, memoryview(b)) for s, b in ranges), key=lambda r: r[0])

    def seek(self, pos: int, whence: int = 0) -> int:
        self._pos = pos if whence == 0 else (self._pos + pos if whence == 1 else self.size + pos)
        return self._pos

    def tell(self) -> int:
        return self._pos

    def close(self) -> None:                          # PakFile.close() calls through; nothing to release
        pass

    def read(self, n: int = -1) -> bytes:
        n = self.size - self._pos if n is None or n < 0 else n
        out, pos, left = bytearray(), self._pos, n
        while left:
            for start, mv in self._ranges:
                if start <= pos < start + len(mv):
                    take = min(left, start + len(mv) - pos)
                    out += mv[pos - start:pos - start + take]
                    pos, left = pos + take, left - take
                    break
            else:
                raise ue_pak.PakError(f"offset {pos} is outside the captured windows ({n} bytes wanted)")
        self._pos += n
        return bytes(out)


class RangePak(ue_pak.PakFile):
    """A PakFile whose bytes come from captured ranges: index, inline headers, blocks and Oodle all as shipped."""

    def __init__(self, size: int, ranges, oodle=None):
        self.path = Path(f"<{OBB}>/{PAK0OPT}")
        self.oodle, self.file_size = oodle, size
        self._f = _RangeReader(size, ranges)
        self.info = ue_pak.read_footer(self._f, size)
        self.mount_point, self.names_available, self.index_hash_ok = "", True, None
        self.entries: dict[str, ue_pak.PakEntry] = {}
        self._load_index()


def data_start(buf) -> int:
    if struct.unpack_from("<I", buf, 0)[0] != LFH:
        raise SystemExit("not a zip local file header")
    nlen, elen = struct.unpack_from("<HH", buf, 26)
    return 30 + nlen + elen


def capture() -> tuple[bytearray, bytearray, Path]:
    """Pass 2: the windows we need out of chunk0optional and pakchunk1, cached between runs."""
    cd = {e["name"]: e for e in json.loads(CD_JSON.read_text(encoding="utf-8"))["entries"]}
    opt, c1 = cd[PAK0OPT], cd[PAK1]
    for e in (opt, c1):
        if e["ctype"] != 0:
            raise SystemExit(f"{e['name']} is not stored in the OBB: byte ranges would not map")
    head, tail = bytearray(HEAD_MB << 20), bytearray((TAIL_MB << 20) + 4096)
    headf, tailf, p1 = WORK / "optional_head.bin", WORK / "optional_tail.bin", WORK / Path(PAK1).name
    if (p1.is_file() and p1.stat().st_size == c1["size"] and headf.is_file() and headf.stat().st_size == len(head)
            and tailf.is_file() and tailf.stat().st_size == len(tail)):
        print(f"windows reused from {WORK}")
        head[:], tail[:] = headf.read_bytes(), tailf.read_bytes()
        return head, tail, p1
    pak1 = bytearray(c1["size"] + 4096)
    targets = [(opt["hdr"], opt["hdr"] + len(head), head),
               (opt["hdr"] + opt["size"] - (TAIL_MB << 20), opt["hdr"] + opt["size"] + 4096, tail),
               (c1["hdr"], c1["hdr"] + c1["size"] + 4096, pak1)]
    stop = c1["hdr"] + c1["size"] + 4096
    with open(ZIP, "rb") as f:
        print(f"pass 2: inflating {OBB} up to {stop / 1e9:.2f} GB", flush=True)
        inflate_member(f, OBB, targets, stop=stop)
    p1.write_bytes(bytes(pak1[data_start(pak1):][:c1["size"]]))
    headf.write_bytes(head)
    tailf.write_bytes(tail)
    print(f"pakchunk1 -> {p1} ({p1.stat().st_size} bytes)")
    return head, tail, p1


def take(pf, name: str, pak_label: str) -> dict:
    e = pf.entries[name]
    data = pf.read(e)
    if len(data) != e.usize:
        raise SystemExit(f"{name}: got {len(data)} bytes, index says {e.usize}")
    row = {"pak": pak_label, "entry": name, "compression": e.method, "stored": e.size, "usize": e.usize,
           "blocks": len(e.blocks), "md5": hashlib.md5(data).hexdigest()}
    print(f"  OK {pak_label:<40} {name}\n     {e.method} {e.size} -> {e.usize} bytes, md5 {row['md5']}")
    return row


def get(pak1_entries: list[str], opt_entries: list[str]) -> list[dict]:
    head, tail, p1 = capture()
    oodle = ue_pak.Oodle(DLL, allow_external=True)          # named outright: nothing is discovered
    pf1 = ue_pak.PakFile(p1, oodle=oodle)
    print(f"pakchunk1: v{pf1.version}, {len(pf1.entries)} entries, index hash ok={pf1.index_hash_ok}")
    ds0 = data_start(head)
    cd = {e["name"]: e for e in json.loads(CD_JSON.read_text(encoding="utf-8"))["entries"]}
    opt = cd[PAK0OPT]
    pak = RangePak(opt["size"], [(0, memoryview(head)[ds0:]), (opt["size"] - (TAIL_MB << 20) - ds0, tail)],
                   oodle=oodle)
    print(f"pakchunk0optional: v{pak.version}, {len(pak.entries)} entries, index hash ok={pak.index_hash_ok}")
    rows = [take(pf1, n, Path(PAK1).name) for n in pak1_entries]
    rows += [take(pak, n, Path(PAK0OPT).name) for n in opt_entries]
    pf1.close()
    (WORK / "entries.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return rows


DEFAULT_P1 = ["VR4/Content/Levels/BIO4/1st/r100/r100.umap",
              "VR4/Content/Levels/BIO4/1st/r100/Lights/r100_Cabin_Exterior.umap"]
DEFAULT_OPT = ["VR4/Content/Characters/BIO4/ANIMAL/em21_Dog/Textures/dog01.uptnl",
               "Engine/Content/EditorMaterials/PreviewShadowIndicator.uptnl"]

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("cd", "get"), nargs="?", default="get")
    ap.add_argument("--pak1", action="append", default=[], help="entry to read from pakchunk1 (repeatable)")
    ap.add_argument("--optional", action="append", default=[], help="entry to read from pakchunk0optional")
    a = ap.parse_args()
    print(f"decoder: {DLL}")
    if a.cmd == "cd" or not CD_JSON.is_file():
        build_cd()
    if a.cmd == "get":
        print(json.dumps(get(a.pak1 or DEFAULT_P1, a.optional or DEFAULT_OPT), indent=1))
```
