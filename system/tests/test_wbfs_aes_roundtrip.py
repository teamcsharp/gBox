"""Round-trip test for the WBFS partition AES decryption path in gbox.formats.wbfs.

Builds a synthetic WBFS fixture with a single encrypted partition whose FST contains
one file ('main.dol' with known bytes), then verifies:
  - partition_data() returns the exact plaintext data area
  - partition_fst() returns the exact FST entries
  - partition_file('main.dol') returns the exact file bytes
  - main_dol() is equivalent to partition_file('main.dol')
"""
import io
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Crypto.Cipher import AES

from gbox.formats.wbfs import (
    WBFS,
    WII_MAGIC,
    WII_COMMON_KEY,
    CLUSTER_SIZE,
    CLUSTER_HASH_SIZE,
    CLUSTER_DATA_OFF,
    CLUSTER_IV_OFF,
    CLUSTER_DATA_SIZE,
    PARTITION_TICKET_SIZE,
    PARTITION_TICKET_KEY_OFF,
    PARTITION_TICKET_TID_OFF,
    PARTITION_TICKET_CKEY_IDX,
)

# ---------------------------------------------------------------------------
# Synthetic fixture parameters
# ---------------------------------------------------------------------------

HD_SHIFT = 9
WBFS_SHIFT = 21
HD_SEC = 1 << HD_SHIFT          # 512
SEC_SIZE = 1 << WBFS_SHIFT      # 0x200000
N_HD_SEC = 1 << 20  # large enough that n_sec covers every allocated WBFS sector

# Partition layout (all offsets relative to partition start)
PART_OFF = 0x0F800000           # arbitrary, must be 4-aligned
TICKET = bytearray(PARTITION_TICKET_SIZE)
TITLE_KEY = bytes(range(16))    # arbitrary 16-byte key
TID = b"\x01\x02\x03\x04\x05\x06\x07\x08"

# Encrypt title key with common key (IV = TID + 8 zero bytes)
TICKET[PARTITION_TICKET_KEY_OFF:PARTITION_TICKET_KEY_OFF + 16] = AES.new(
    WII_COMMON_KEY, AES.MODE_CBC, TID + b"\x00" * 8
).encrypt(TITLE_KEY)
TICKET[PARTITION_TICKET_TID_OFF:PARTITION_TICKET_TID_OFF + 8] = TID
TICKET[PARTITION_TICKET_CKEY_IDX] = 0

# Partition header (after ticket): data_off/data_sz fields are at partition-relative +0x2B8/+0x2BC,
# stored >>2. The parser (wbfs._partition_geometry) reads the 0x2C-byte header at
# partition_offset + TICKET_SIZE and unpacks the data_off/data_sz fields at that same relative
# position, so the packed value must be (DATA_OFF >> 2) where DATA_OFF is the absolute
# partition-relative byte offset of the data area.
PART_HDR = bytearray(0x2C)
DATA_SZ = 3 * CLUSTER_SIZE      # 3 clusters
DATA_OFF = 0x10000               # byte offset of data area within partition (clear of ticket/header)
struct.pack_into(">I", PART_HDR, 0x2B8 - PARTITION_TICKET_SIZE, DATA_OFF >> 2)
struct.pack_into(">I", PART_HDR, 0x2BC - PARTITION_TICKET_SIZE, DATA_SZ >> 2)

# Disc/boot header: game id, magic, dol/fst offsets
DISC_HDR = bytearray(0x440)
DISC_HDR[0:6] = b"R3OJ01"
struct.pack_into(">I", DISC_HDR, 0x18, WII_MAGIC)
DISC_HDR[0x20:0x60] = b"Metroid: Other M" + b"\x00" * (0x60 - 0x20 - len("Metroid: Other M"))
# Logical (decrypted, hash-stripped) offsets: cluster c user data starts at c * CLUSTER_DATA_SIZE.
DOL_OFF = CLUSTER_DATA_SIZE               # main.dol: cluster 1 user start
FST_OFF = 2 * CLUSTER_DATA_SIZE           # FST: cluster 2 user start
FST_SZ = 0x100
# Wii: boot.bin offsets are stored >>2 (in the decrypted partition data, cluster 0).
struct.pack_into(">I", DISC_HDR, 0x420, DOL_OFF >> 2)
struct.pack_into(">I", DISC_HDR, 0x424, FST_OFF >> 2)
struct.pack_into(">I", DISC_HDR, 0x428, FST_SZ >> 2)

# main.dol content (known bytes, 64 bytes)
# a minimal valid DOL: 0x100 header, one text section (file offset 0x100, 0x40 bytes) -> total 0x140
DOL = bytearray(0x140)
struct.pack_into('>I', DOL, 0, 0x100)
struct.pack_into('>I', DOL, 0x90, 0x40)
DOL[0x100:] = bytes(range(0x40))
DOL = bytes(DOL)

# FST: 12-byte entries; root (next=2) + one file "main.dol"; name table at n*12 = 24
FST = bytearray(FST_SZ)
struct.pack_into(">B3sII", FST, 0, 0x00, b"\x00\x00\x00", 0, 2)                 # root: next index 2
struct.pack_into(">B3sII", FST, 12, 0x00, b"\x00\x00\x00", DOL_OFF >> 2, len(DOL))
FST[24:24 + 9] = b"main.dol\x00"

# ---------------------------------------------------------------------------
# Build encrypted partition data
# ---------------------------------------------------------------------------

def encrypt_cluster(user_plain: bytes) -> bytes:
    """Encrypt one cluster: hash block (IV=0) + user data (IV from hash block)."""
    assert len(user_plain) == CLUSTER_DATA_SIZE
    # Hash block plaintext: H0/H1/H2 SHA-1s (we don't verify them, so zeros are fine)
    hash_plain = bytearray(CLUSTER_HASH_SIZE)
    hash_enc = AES.new(TITLE_KEY, AES.MODE_CBC, b"\x00" * 16).encrypt(bytes(hash_plain))
    # IV for user data = the *encrypted* hash block bytes [0x3D0:0x3E0] (Wii spec)
    iv = hash_enc[CLUSTER_IV_OFF:CLUSTER_IV_OFF + 16]
    data_enc = AES.new(TITLE_KEY, AES.MODE_CBC, iv).encrypt(user_plain)
    return hash_enc + data_enc

# Build plaintext data area (3 clusters)
data_area = bytearray(DATA_SZ)
# Cluster 0: boot.bin (game id, dol/fst offsets)
data_area[CLUSTER_DATA_OFF:CLUSTER_DATA_OFF + 0x440] = DISC_HDR
# Cluster 1: main.dol
data_area[CLUSTER_SIZE + CLUSTER_DATA_OFF:CLUSTER_SIZE + CLUSTER_DATA_OFF + len(DOL)] = DOL  # logical offset CLUSTER_DATA_SIZE
# Cluster 2: FST
data_area[2 * CLUSTER_SIZE + CLUSTER_DATA_OFF:2 * CLUSTER_SIZE + CLUSTER_DATA_OFF + len(FST)] = FST

# Encrypt each cluster
enc_data = bytearray()
for c in range(3):
    user = bytes(data_area[c * CLUSTER_SIZE + CLUSTER_DATA_OFF:(c + 1) * CLUSTER_SIZE])
    enc_data += encrypt_cluster(user)

# ---------------------------------------------------------------------------
# Assemble the WBFS file
# ---------------------------------------------------------------------------

# WBFS header (offset 0)
wbfs_hdr = bytearray(HD_SEC)
wbfs_hdr[0:4] = b"WBFS"
struct.pack_into(">I", wbfs_hdr, 4, N_HD_SEC)
wbfs_hdr[8] = HD_SHIFT
wbfs_hdr[9] = WBFS_SHIFT
struct.pack_into(">I", wbfs_hdr, 0x0C, N_HD_SEC)   # wbfs_sector_count (unused by parser)
# Disc table: one entry at 0x0C
wbfs_hdr[0x0C] = 1

# Disc info at hd_sector 1: 0x100 disc header + wlba table
n_disc_sec = (143432 * 2 * 0x8000 + SEC_SIZE - 1) // SEC_SIZE
wlba = [0] * n_disc_sec
# We need to map virtual ISO sectors to WBFS sectors.
# Virtual ISO layout:
#   0x00000 - 0x40000 : disc header + partition table area (we put partition table at 0x40000)
#   0x40000 - 0x40008 : partition table (8 bytes: 1 partition, table at 0x40008)
#   0x40008 - 0x40010 : partition entry (offset>>2, type)
#   PART_OFF          : partition (ticket + header + encrypted data)
# We'll allocate WBFS sectors sequentially.
wbfs_sec = 2  # sector 0 = header, sector 1 = disc info

def alloc_sec():
    global wbfs_sec
    s = wbfs_sec
    wbfs_sec += 1
    return s

# Map virtual ISO sectors
iso_size = PART_OFF + DATA_OFF + DATA_SZ
n_iso_sec = (iso_size + SEC_SIZE - 1) // SEC_SIZE
for i in range(n_iso_sec):
    wlba[i] = alloc_sec()

# Build the file
buf = bytearray(wbfs_sec * SEC_SIZE)
# Header
buf[0:HD_SEC] = wbfs_hdr
# Disc info at hd_sector 1 (offset 1 * HD_SEC = 512 bytes)
info_off = HD_SEC
buf[info_off:info_off + 0x440] = DISC_HDR
for i, w in enumerate(wlba):
    struct.pack_into(">H", buf, info_off + 0x100 + i * 2, w)

# Disc header in virtual ISO sector 0 (wlba[0] = container sector 2): the dol/FST
# offsets at 0x420-0x428 are read from the virtual ISO, not the disc-info copy.
buf[wlba[0] * SEC_SIZE:wlba[0] * SEC_SIZE + 0x440] = DISC_HDR

# Partition table at 0x40000
pt_off = 0x40000
struct.pack_into(">II", buf, pt_off, 1, (pt_off + 8) >> 2)
struct.pack_into(">II", buf, pt_off + 8, PART_OFF >> 2, 0)

# Partition data
part_sec = wlba[PART_OFF // SEC_SIZE]
part_base = part_sec * SEC_SIZE
buf[part_base:part_base + PARTITION_TICKET_SIZE] = TICKET
buf[part_base + PARTITION_TICKET_SIZE:part_base + PARTITION_TICKET_SIZE + 0x2C] = PART_HDR
buf[part_base + DATA_OFF:part_base + DATA_OFF + DATA_SZ] = enc_data

# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

fh = io.BytesIO(bytes(buf))
wbfs = WBFS(buf, _fh=io.BytesIO(buf))

# partition_data: each cluster contributes its 0x7C00 user bytes
expected_pd = b"".join(
    bytes(data_area[c * CLUSTER_SIZE + CLUSTER_DATA_OFF:(c + 1) * CLUSTER_SIZE])
    for c in range(DATA_SZ // CLUSTER_SIZE)
)
pd = wbfs.partition_data(PART_OFF)
assert pd == expected_pd, f"partition_data mismatch: {pd[:64].hex()} != {expected_pd[:64].hex()}"

# partition_fst
fst = wbfs.partition_fst(PART_OFF)
assert len(fst) == 1, f"expected 1 FST entry, got {len(fst)}"
e = fst[0]
assert e["path"] == "main.dol", f"unexpected path {e['path']}"
assert e["offset"] == DOL_OFF, f"unexpected offset {e['offset']}"
assert e["size"] == len(DOL), f"unexpected size {e['size']}"

# partition_file
f = wbfs.partition_file(PART_OFF, "main.dol")
assert f == DOL, f"partition_file mismatch: {f.hex()} != {DOL.hex()}"

# main_dol
md = wbfs.main_dol(PART_OFF)
assert md == DOL, f"main_dol mismatch: {md.hex()} != {DOL.hex()}"

# cluster_data round-trip
cd = wbfs.cluster_data(PART_OFF, 1)
assert cd == bytes(data_area[CLUSTER_SIZE + CLUSTER_DATA_OFF:2 * CLUSTER_SIZE]), "cluster_data mismatch"

print("PASS: synthetic AES round-trip (partition_data, partition_fst, partition_file, main_dol, cluster_data)")
