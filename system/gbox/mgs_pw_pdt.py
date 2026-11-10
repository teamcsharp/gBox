"""Metal Gear Solid: Peace Walker (PSP) .PDT container reader.

Owned-build findings (ULES01372 CSO, source sha256
26430f5ad29d989e005e75bc9b34b03e4830b4b25666978891029f58085b3a28):

Outer file layout (little-endian), XOR-obfuscated PDT v1 (BGM.PDT,
VOICE*.PDT, dlc/VEP*.PDT, dlc/WMP*.PDT):
  off 0  u8   xor key (whole payload after byte 15 is XORed with this byte)
  off 1  u8   type code lo  (0x88=VEP, 0x92=WMP, 0x11=BGM, 0xb4=VOICE*)
  off 2  u8   type code hi  (0x1b=DLC, 0x01=BGM, 0xb2=VOICE*)
  off 3  u8   0
  off 4  u32  0 (reserved)
  off 8  u32  0 (reserved)
  off 12 u32  seed/serial (varies per file, meaning unknown)
  off 16 ...  XOR-obfuscated inner container, offsets below are into this
             payload (file offset = 16 + payload offset).

Inner container (after XOR):
  off 0  u32  magic 0x007A7E9C
  off 4  u16  0
  off 6  u16  1 (version)
  off 8  u16  member count
  off 10 u16  2
  off 12 u32  32 + count*12 (table end offset; matches all probed files)
  off 16 ...  member table, stride 12 bytes per member:
       u32 size  (plaintext member size in bytes)
       u32 hash  (not crc32; per-member integrity id, algorithm unknown)
       u32 offset (offset from FILE start; the payload begins at file
                   offset 16, so payload offset = offset-16; members are
                   stored contiguously, 0x800/0x2000-aligned)

Member 0 of VEP*/WMP* PDTs is a nested-name blob ("...confession.pdt",
"Beyond the B..." title text); audio members start with
00 00 00 00 50 00 00 00 (Konami PSP sound header, not RIFF/AT3).

STAGEDAT.PDT is NOT single-byte-XOR: ciphertext does not decode with
key byte 0xFA (0xE9^0x88 != 0x9C^0x7E), so it uses a different cipher
(separate milestone; likely keyed stream / save-linked).
"""

MAGIC = 0x007A7E9C


class PdtError(Exception):
    pass


def deobfuscate(payload):
    """XOR the payload after the 16-byte outer header with header byte 0."""
    if len(payload) < 16:
        raise PdtError('PDT too short')
    key = payload[0]
    return key, bytes(b ^ key for b in payload[16:])


class PdtFile:
    """Parsed PDT v1 container (XOR variant)."""

    def __init__(self, raw):
        import struct
        self.struct = struct
        self.key, body = deobfuscate(raw)
        if len(body) < 16:
            raise PdtError('inner container too short')
        magic, z, version, count, two, table_end = struct.unpack('<IHHHHI', body[:16])
        if magic != MAGIC:
            raise PdtError('bad PDT inner magic %#x (STAGEDAT-style cipher?)' % magic)
        if version != 1 or two != 2 or z != 0:
            raise PdtError('unexpected PDT inner header fields')
        self.count = count
        self.table_end = table_end
        if table_end != 32 + count * 12:
            raise PdtError('PDT table end %#x != 32+count*12' % table_end)
        if len(body) < table_end:
            raise PdtError('PDT truncated member table')
        self.members = []
        prev_end = None
        for i in range(count):
            size, mhash, offset = struct.unpack('<III', body[16 + 12 * i:28 + 12 * i])
            end = offset + size
            if offset < 16 or end > len(body) + 16:
                raise PdtError('member %d exceeds file' % i)
            if prev_end is not None and offset < prev_end:
                raise PdtError('member %d overlaps previous' % i)
            prev_end = end
            self.members.append({'index': i, 'size': size, 'hash': mhash, 'offset': offset})
        self._body = body

    def extract(self, index):
        m = self.members[index]
        o = m['offset'] - 16
        return self._body[o:o + m['size']]


def open_from_ciso(ciso, read_members, path):
    """Open a PDT straight out of an opened CISO via psp_ciso_inventory."""
    for name, lba, size in read_members(ciso, None):
        if name.upper() == path.upper():
            return PdtFile(ciso.read(lba * 2048, size))
    raise PdtError('PDT %s not found in image' % path)
