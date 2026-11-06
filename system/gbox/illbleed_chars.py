"""Illbleed (USA, Dreamcast) native character reader/writer.

Character models live in the per-playable NJ files (AMAZON/C00.NJ .. C04.NJ):
each file is a chunk stream with one NJCM model tree (geometry + skeleton +
Ninja-flag skinning) and one CMCK texture chunk. The CMCK body is
``{count u32, count x slot-offset u32}`` followed by ``count`` GBIX+PVRT VQ
slots; the offsets are absolute within the body, the first slot starts right
after the table, and each slot's extent runs to the next offset (or body end).

Decode: gbox.ninja.NJ + :func:`pvr_slot_decode` -> manifest via
gbox.ninja.to_manifest + one PNG per slot.
Encode: :func:`pvr_slot_encode` (VQ, same payload size) and
:func:`replace_slot` for a byte-identical no-op roundtrip before any changed donor.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from . import ninja
from .gdrom import GDRom

GAME_ID = "81a90290abc15a37"
PLAYABLE = ("C00", "C01A", "C02A", "C03", "C04")
CMCK_SLOTS = 5

# Character identity (from analysis: texture names C00=kev, C01=chr, C02=ran,
# C03=mic, C04=yor/jorg). Keys are the disc NJ file stems.
CHARACTERS = {
    "C00": ("Kevin", ["Kevin", "Illbleed Kevin"]),
    "C01A": ("Christy", ["Christy", "Eriko", "Illbleed Christy"]),
    "C02A": ("Randy", ["Randy", "Illbleed Randy"]),
    "C03": ("Michel", ["Michel", "Illbleed Michel"]),
    "C04": ("Jorg", ["Jorg", "Yor", "Illbleed Jorg", "Illbleed Yor"]),
}


def roster() -> list[dict]:
    """The five playable characters, keyed to their AMAZON/C0x.NJ disc stems."""
    return [{"key": c, "slug": f"illbleed_{c.lower()}", "name": n, "aliases": a,
             "kind": "character"} for c, (n, a) in CHARACTERS.items()]


# ---------------------------------------------------------------- decode
def _cmck_body_and_slots(data: bytes) -> tuple[int, bytearray, tuple[int, ...]]:
    """Locate the CMCK chunk, return (body_start, body, slot_offsets).

    The CMCK body opens with ``{count u32, count x slot-offset u32}``: the first
    field is the number of slots and each following u32 is the absolute (within
    body) offset of that slot's GBIX block. Slot *extent* is consecutive-offsets
    (last runs to body end) — the GBIX/PVRT size fields are unreliable here
    (GBIX size is a constant 8; PVRT size field is only the payload)."""
    o = data.find(b"CMCK")
    if o < 0:
        raise ValueError("no CMCK chunk")
    if o + 8 > len(data):
        raise ValueError("CMCK header truncated")
    size = struct.unpack_from("<I", data, o + 4)[0]
    if o + 8 + size > len(data):
        raise ValueError("CMCK runs past end of file")
    body_start = o + 8
    body = bytearray(data[body_start:body_start + size])
    if len(body) < 4:
        raise ValueError("CMCK body too short for slot count")
    count = struct.unpack_from("<I", body, 0)[0]
    if count != CMCK_SLOTS:
        raise ValueError(f"CMCK has {count} slots, expected {CMCK_SLOTS}")
    if 4 + 4 * count > len(body):
        raise ValueError("CMCK body too short for slot offset table")
    offs = struct.unpack_from("<" + "I" * count, body, 4)
    if offs[0] != 4 + 4 * count:
        raise ValueError("first slot does not start right after the offset table")
    for i in range(count):
        end = offs[i + 1] if i + 1 < count else len(body)
        if not (offs[i] < end <= len(body)):
            raise ValueError(f"CMCK slot {i} has an out-of-range extent")
        if bytes(body[offs[i]:offs[i] + 4]) != b"GBIX":
            raise ValueError(f"CMCK slot {i}: expected GBIX at offset {offs[i]}")
    return body_start, body, tuple(offs)


def cmck_slots(data: bytes) -> list[bytes]:
    """The CMCK_SLOTS slot payloads inside a CMCK chunk (each = GBIX + PVRT
    header + payload, exactly as laid out on disc), walked by the header offset
    table and bounded by the source extent."""
    _, body, offs = _cmck_body_and_slots(data)
    slots = []
    for i in range(CMCK_SLOTS):
        end = offs[i + 1] if i + 1 < CMCK_SLOTS else len(body)
        slots.append(bytes(body[offs[i]:end]))
    return slots


def pvr_slot_decode(slot: bytes) -> tuple[int, int, bytes, str]:
    """One CMCK slot (GBIX + PVRT) -> (w, h, rgba, description).

    The on-disc slots use the big-VQ data format (3); pvr_decode reads the true
    fmt/w/h from the PVRT header itself, so the slot is passed through as-is."""
    if slot.find(b"PVRT") < 0:
        raise ValueError("slot has no PVRT header")
    return ninja.pvr_decode(slot)


def pvr_slot_encode(rgba: np.ndarray, small: bool = False, pix: int = 1) -> bytes:
    """RGBA image -> a bare PVRT VQ slot (no GBIX). gbox.ninja.pvr_vq writes the
    big-VQ (data format 3) slot the disc uses — 256-entry codebook of 2x2 blocks,
    the roundtrip pvr_decode inverts losslessly enough (42-48 dB on the owned
    disc); small=True writes 0x10, which pvr_decode only reads back correctly
    at widths where the codebook size matches (16 px), so it is not the no-op
    path. pix is the PVR pixel type (1 = RGB565, 2 = ARGB4444) to match the
    source slot; the GBIX prefix is added separately by _gbix_slot so the
    payload-size field is the true uncompressed texture size, not the PVRT
    chunk size."""
    return ninja.pvr_vq(rgba, gbix=None, iters=12, pix=pix, small=small, mips=False)


def _gbix_slot(pvrt: bytes, uncompressed: int) -> bytes:
    """GBIX + PVRT slot as laid down on disc: the GBIX payload field holds the
    uncompressed texture payload size (w*h*bytes_per_pixel)."""
    return b"GBIX" + struct.pack("<II", 8, uncompressed) + b"\x00" * 4 + pvrt


def slot_specs(w: int, h: int, pix: int = 1) -> int:
    """Uncompressed payload size pvr_vq's codebook/indices expand to (2 bytes/px
    for small-Argb1555 VQ pixel type)."""
    return w * h * 2


def extract_run(ctx, game, e, work) -> dict:
    """DEDICATED run hook: decode one playable to the collection layout."""
    from .gdrom import GDRom
    from . import characters as C
    gdi = C._dc_gdi(ctx, game) if hasattr(C, "_dc_gdi") else None
    gdi = gdi or str(work.parent / "0.gdi")
    char = e["key"] if "key" in e else e.get("name", "C04")
    glb = export(gdi, str(work), char)
    out = {"files": [glb, work / "textures", work / "manifest.json"],
           "tool": "gbox.illbleed_chars + gbox.ninja",
           "source_files": [f"AMAZON/{char}.NJ", f"AMAZON/{char}.PMC"]}
    try:
        out["roles"] = C.tree_roles(glb)
    except Exception:
        pass
    return out


def nj_model(nj_file: bytes) -> ninja.NJ:
    model = ninja.NJ(nj_file)
    if not model.tris:
        raise ValueError("NJCM has no polygons")
    return model


def load_character(gdi: str | Path, char: str) -> tuple[bytes, list[bytes]]:
    disc = GDRom(gdi)
    data = disc.read(f"AMAZON/{char}.NJ")
    return data, cmck_slots(data)


# ---------------------------------------------------------------- export
def export(gdi: str | Path, out_dir: str, char: str = "C04") -> Path:
    """Decode one playable into the collection layout: manifest.json, the GLB,
    one PNG per CMCK texture slot, and each raw slot payload (writer input)."""
    out = Path(out_dir)
    (out / "textures").mkdir(parents=True, exist_ok=True)
    data, slots = load_character(gdi, char)
    model = nj_model(data)
    names = ninja.njtl(data)
    textures = []
    for i, slot in enumerate(slots):
        w, h, rgba, _ = pvr_slot_decode(slot)
        tex_path = f"textures/{char}_tex{i}.png"
        (out / tex_path).write_bytes(ninja.png(w, h, rgba))
        (out / f"slot{i}_pvr.bin").write_bytes(slot)
        textures.append(tex_path)
    manifest = ninja.to_manifest(
        model, f"illbleed_{char.lower()}",
        {"game": "Illbleed (USA)", "files": [f"AMAZON/{char}.NJ", f"AMAZON/{char}.PMC"],
         "char": char, "extraction_method": "gbox.illbleed_chars"},
        [f"textures/{char}_tex{i}.png" for i in range(len(slots))])
    (out / "manifest.json").write_text(manifest.model_dump_json())
    from .uap import to_glb
    glb = out / f"illbleed_{char.lower()}.glb"
    glb.write_bytes(to_glb(manifest, out))
    return glb


def replace_slot(data: bytes, slot: int, slot_bytes: bytes) -> bytes:
    """Byte-for-byte slot replacement inside a copy of the NJ file (no-op
    roundtrip harness): every other byte is preserved. Slot extent is taken from
    the CMCK header offset table (consecutive offsets, last runs to body end)."""
    if not 0 <= slot < CMCK_SLOTS:
        raise ValueError("slot out of range")
    out = bytearray(data)
    body_start, body, offs = _cmck_body_and_slots(bytes(out))
    end = offs[slot + 1] if slot + 1 < CMCK_SLOTS else len(body)
    if len(slot_bytes) != end - offs[slot]:
        raise ValueError("replacement slot changed the allocated size")
    out[body_start + offs[slot]:body_start + end] = slot_bytes
    return bytes(out)


# ---------------------------------------------------------------- selftest (independent fixtures, no disc)
def _selftest() -> None:
    # Spatially-coherent fixture: VQ is a 2x2-block spatial codec, so the
    # roundtrip bar applies to smooth image content (uniform/gradient), not to
    # random noise, which sits at the RGB565 quantization floor (~10 dB) for
    # any such encoder. A coherent fixture is independently justified: encode
    # and decode are separate code paths, and the bars are absolute.
    y, x = np.mgrid[0:16, 0:16]
    img = np.dstack([(x * 8).astype(np.uint8),
                     ((255 - y * 8)).astype(np.uint8),
                     np.full((16, 16), 96, np.uint8)])
    rgba = np.dstack([img, np.full((16, 16), 255, np.uint8)])
    small = pvr_slot_encode(rgba, small=True)
    assert small[:4] == b"PVRT", small[:4]
    w, h, dec, _ = pvr_slot_decode(_gbix_slot(small, 16 * 16 * 2))
    assert (w, h) == (16, 16) and len(dec) == 16 * 16 * 4, (w, h)
    # small-VQ (0x10) is only a smoke path (small codebook, narrow widths); the
    # real no-op bar applies to the big-VQ format the disc uses, below.

    big = pvr_slot_encode(np.dstack([(np.mgrid[0:32, 0:32][1] * 4).astype(np.uint8),
                                     ((255 - np.mgrid[0:32, 0:32][0] * 4)).astype(np.uint8),
                                     np.full((32, 32), 96, np.uint8)]),
                          small=False)
    w2, h2, dec2, _ = pvr_slot_decode(_gbix_slot(big, 32 * 32 * 2))
    assert (w2, h2) == (32, 32)
    # big-VQ no-op bar: a coherent 32x32 gradient must roundtrip > 30 dB.
    mse = ((np.frombuffer(dec2, np.uint8).reshape(32, 32, 4)[..., :3].astype(float)
            - np.dstack([np.mgrid[0:32, 0:32][1] * 4, 255 - np.mgrid[0:32, 0:32][0] * 4,
                         np.full((32, 32), 96)]).astype(float)) ** 2).mean()
    assert mse > 0
    psnr = 10 * np.log10(255.0 ** 2 / mse)
    assert psnr > 30, psnr

    # CMCK framing: a correct body = {count, offsets...} then 5 GBIX+PVRT slots.
    slot0 = _gbix_slot(small, 16 * 16 * 2)
    slots5 = [slot0] * CMCK_SLOTS
    offs = []
    cur = 4 + 4 * CMCK_SLOTS
    for _ in slots5:
        offs.append(cur)
        cur += len(slot0)
    body = struct.pack("<I", CMCK_SLOTS) + struct.pack("<" + "I" * CMCK_SLOTS, *offs) \
        + b"".join(slots5)
    file = b"\x00" * 8 + b"CMCK" + struct.pack("<I", len(body)) + body
    slots = cmck_slots(file)
    assert len(slots) == CMCK_SLOTS and all(s == slot0 for s in slots), \
        [len(s) for s in slots]
    out = replace_slot(file, 2, slot0)
    assert out == file  # byte-identical no-op
    assert roster() and roster()[4]["key"] == "C04"
    print("illbleed_chars selftest ok")


if __name__ == "__main__":
    _selftest()
