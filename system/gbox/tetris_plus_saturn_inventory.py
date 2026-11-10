"""Tetris Plus (USA, Saturn) owned-build inventory (request #2458, stage 1).

Reads an extracted raw MODE1/2352 track-1 image (``chdman extractcd``) or a
2048-byte ISO, walks ISO9660 and hashes members.  The disc is 2D (SH-2 overlays
``*.BIN`` + sprite/tile banks ``*.CHR``/``*.CRT``): there are no 3D character
models; the fingerprint's Ninja/NaomiLib/LMT guesses are not supported by the files.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

CHD_SHA256 = '63e9fb7ee6aa6e0fcb97a0633bba0944ceaa50945a446ac012612341715b20d4'
BIN_SHA256 = 'f0df8cbe720881ff68d4dc08e5d1e8d27f47b32b19043a936dc0d543935a7fba'  # chdman extractcd -ob (all tracks, 591523296 bytes)
SATURN_HEADER = b"SEGA SEGASATURN SEGA TP T-57    T-5704H   V1.00119960831"
EXECUTABLE = "0MAIN.BIN"  # IP.BIN first-read size 0x18 sectors; LBA 24, load addr per IP header
# path -> (lba, size, sha256) of member bytes, track 1, user-data offset 16 in 2352 sectors
MEMBERS = {
 "0MAIN.BIN": [
  24,
  121064,
  "baea8631695bc54d89cb367101ea6fbdfd6f41cc8067feb17b66054d37e12fc6"
 ],
 "EDIT.BIN": [
  2666,
  102808,
  "522efa170fae89e57b01fb41c585c97d15062cbde7d29ffae56e98bb724251a6"
 ],
 "EDIT_E.CHR": [
  2491,
  356811,
  "868fa6af669603e59603ad4dfd7aacf0c525152c9cb592ef9de7c164bf3cdb08"
 ],
 "HOW_N_E.CHR": [
  893,
  40919,
  "4df7e8f328941dd003ff96b92fe7fd57883c89057f5db885ba2c5c4a30404d9d"
 ],
 "HOW_P_E.CHR": [
  971,
  148920,
  "562a798dd94034f0180851fe7f074cd9c3f856ba90d216bffa7585a1f40ad23d"
 ],
 "HOW_TO_N.BIN": [
  841,
  104984,
  "764d71f61b934903e797e9d74292697d0befb2cd5f8a037a8d8350ffd5161c3e"
 ],
 "HOW_TO_P.BIN": [
  913,
  117828,
  "de67263718b6d286ff7a29394ec9574622b01df3e1cb71dd171f3b9841334626"
 ],
 "HOW_TO_V.BIN": [
  1044,
  134340,
  "4606814040d012b7392e5264880fc227c944c74d4b2b020bd0ea85319f755543"
 ],
 "HOW_V_E.CHR": [
  1110,
  234438,
  "40ddf4a70fd299b205ab8d14d07931b625b9398c2a896756fc130e7e7c92e646"
 ],
 "INIT_MAP.BIN": [
  97,
  34,
  "74c51b57307bf1abb41cd5eee5b545d83e1f829c4fe1146177d309b0e383c9bb"
 ],
 "INIT_MAP.CRT": [
  98,
  438272,
  "c93f80b45791c0b8c232c479add0fb53a79cd70261ac21bbb3d2f0a6c9465a13"
 ],
 "JLOGO.BIN": [
  554,
  15816,
  "25ac47f7693e3a83cd48c18b212ff47b0e7ab84779a26aa7a8f8d8dbcaef9acb"
 ],
 "JLOGO_E.CHR": [
  527,
  53448,
  "90265f36827a521acd96e651c46ec24e2a6ee43d2c9936384796b0d523f93828"
 ],
 "LOGO_MAP.BIN": [
  312,
  34,
  "74c51b57307bf1abb41cd5eee5b545d83e1f829c4fe1146177d309b0e383c9bb"
 ],
 "LOGO_MAP.CRT": [
  313,
  438272,
  "8e8f312eed2a52550fb66ed4dea7b3eb5b169838d727d1c48570e32bc373b3e5"
 ],
 "MODE.BIN": [
  1287,
  15408,
  "5eb446c859f08b3a194b666db812249d7c0584a5b3d7647d982cd2b535078eb0"
 ],
 "MODE_E.CHR": [
  1225,
  125559,
  "6932e502541a23a3bd2130b4de15fdd31c4030537edd37711683cc3099b8209a"
 ],
 "NORMAL.BIN": [
  1760,
  67504,
  "97bebc82627f908ce7493ce0a4ee784f78bc3eaaa37c13ca162b5f871f3fe182"
 ],
 "NORMAL_E.CHR": [
  1329,
  880883,
  "7e8ffa40cfbb11bda60b55f11c5397df11a495acd9e1150e16403777bdb9f18f"
 ],
 "PUZZLE.BIN": [
  2231,
  202672,
  "c6996021b96160d697a0ca1d004cf462d1bc6f0d1be4dc2448da3d7e586cce73"
 ],
 "PUZZLE_E.CHR": [
  1793,
  895279,
  "8413af4fd1383839f1cd011083b5f2e8524a70c42dd57d34cfcba4e849dcfc07"
 ],
 "RANKING.BIN": [
  1324,
  10008,
  "358da7255f9b4e4192580e40c408b622d042bac766ac63dc5cd7f626fa382646"
 ],
 "RANK_E.CHR": [
  1295,
  58592,
  "d545a33bfd2bda18946d4b9a831d4353a48d91a18223aaea99f770d4fdbe3b0f"
 ],
 "SDDRVS.TSK": [
  84,
  25556,
  "c8842cc957bf82693ddd72d996353c9cb92feb34fe5f2834c0651aebacb4bd04"
 ],
 "TDEMO.BIN": [
  604,
  18992,
  "c20e22b538b22f1d41eff96434f82f1cc3c62b57b1b10bdaa8b965a97ecc370e"
 ],
 "TDEMO_E.CHR": [
  562,
  84823,
  "c0ad741bff7898676f266e66225dab6756d9072cee7f54b920fe0cc6a808c392"
 ],
 "TET_ABS.TXT": [
  22,
  16,
  "791fc948b2cd7f83b3482c082705ac63bf3cd45054b33eccbe44873f28cc6519"
 ],
 "TET_BIB.TXT": [
  23,
  16,
  "791fc948b2cd7f83b3482c082705ac63bf3cd45054b33eccbe44873f28cc6519"
 ],
 "TET_CPY.TXT": [
  21,
  24,
  "710ba8b99fae9c5480190053314d29204ea1d52519baf36c2982f2ed67cd21b4"
 ],
 "TITLE.BIN": [
  774,
  135800,
  "4e774e52d29e56c0ac06d8ffb25cedbf8831d48a11501220e6f4d2032c825e9c"
 ],
 "TITLE_E.CHR": [
  614,
  327315,
  "abe702316678f0b9342a2015d4e2f6452247d496a3cfd15b450015864661dc95"
 ],
 "VSPUZ.BIN": [
  2443,
  96944,
  "77b055d915cdaa1416e0ef3f14a2de7c57638dd1846f098a4c004a9f17c3e95e"
 ],
 "VSPUZ_E.CHR": [
  2330,
  231038,
  "f544600f26086d906bfd76e19b60c5b416a7a987e848c647438aad4f97ecd4cf"
 ]
}


def _sector_layout(fh) -> tuple[int, int]:
    """Return (sector_size, user_offset) for a raw 2352 or cooked 2048 image."""
    fh.seek(16 * 2352 + 16)
    if fh.read(6) == b"\x01CD001":
        return 2352, 16
    fh.seek(16 * 2048)
    if fh.read(6) == b"\x01CD001":
        return 2048, 0
    raise ValueError("no ISO9660 primary volume descriptor at LBA 16")


def read_extent(fh, lba: int, size: int) -> bytes:
    ss, off = _sector_layout(fh)
    out = bytearray()
    for i in range((size + 2047) // 2048):
        fh.seek((lba + i) * ss + off)
        out += fh.read(2048)
    return bytes(out[:size])


def listing(path) -> list[tuple[str, int, int]]:
    with open(path, "rb") as fh:
        pvd = read_extent(fh, 16, 2048)
        root = pvd[156:190]
        files: list[tuple[str, int, int]] = []

        def walk(lba, ln, prefix):
            d = read_extent(fh, lba, ln)
            o = 0
            while o < len(d):
                n = d[o]
                if n == 0:
                    o = (o // 2048 + 1) * 2048
                    continue
                r = d[o:o + n]
                o += n
                nm = r[33:33 + r[32]]
                if nm in (b"\0", b"\1"):
                    continue
                nm = nm.decode("ascii").split(";")[0]
                el, sz = struct.unpack("<I", r[2:6])[0], struct.unpack("<I", r[10:14])[0]
                if r[25] & 2:
                    walk(el, sz, prefix + nm + "/")
                else:
                    files.append((prefix + nm, el, sz))

        walk(struct.unpack("<I", root[2:6])[0], struct.unpack("<I", root[10:14])[0], "")
        return files


def saturn_header(path) -> bytes:
    with open(path, "rb") as fh:
        return read_extent(fh, 0, 2048)[:0x100]


def inventory(path) -> dict:
    """Hash every member by streaming its extent; classify by extension."""
    with open(path, "rb") as fh:
        rows = []
        for nm, lba, sz in listing(path):
            rows.append({"path": nm, "lba": lba, "size": sz,
                         "sha256": hashlib.sha256(read_extent(fh, lba, sz)).hexdigest()})
    kinds = {"BIN": "sh2_overlay_or_data", "CHR": "sprite_tile_bank", "CRT": "tilemap_or_cell_table"}
    for r in rows:
        r["kind"] = kinds.get(r["path"].rsplit(".", 1)[-1], "other")
    return {"platform": "saturn", "executable": EXECUTABLE, "files": rows,
            "executable_sha256": next(r["sha256"] for r in rows if r["path"] == EXECUTABLE)}


# --- analysis-stage probe (hypothesis from header statistics over all 12 *.CHR members) ---
# IP.BIN/0MAIN.BIN: SH-2 big-endian, load/entry base 0x06010000 (0MAIN.BIN literal pool refs
# 0x06010030 / 0x060FFC00). Decoder not yet located (linear capstone SH2 scan is too noisy; needs Ghidra).
MAIN_BASE = 0x06010000
CHR_MODE_BITS = {0x80: "bit7", 0x40: "bit6", 0x20: "bit5", 0x04: "bit2"}


def chr_header(data: bytes) -> dict:
    """Parse the 10-byte *.CHR header: 01, mode, u16be a, u16be b, u8 width (+pad), u8 height.
    Width/height are inferred (values 160x224, 160x240, 16x16, 104x8 ... fit Saturn bitmap sizes);
    mode/a/b semantics are unproven."""
    if len(data) < 10 or data[0] != 1:
        raise ValueError("not a Tetris Plus CHR bank (magic 0x01 expected)")
    return {"mode": data[1],
            "mode_bits": [n for m, n in CHR_MODE_BITS.items() if data[1] & m],
            "a": struct.unpack(">H", data[2:4])[0], "b": struct.unpack(">H", data[4:6])[0],
            "width": data[6], "height": data[8], "pad_ok": data[7] == 0,
            "payload_offset": 9}
