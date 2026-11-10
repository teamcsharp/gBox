"""WBFS v1 reader: exposes the sparse WBFS container as a virtual, seekable Wii ISO (read-only).

Layout (big-endian): header at offset 0 = magic b"WBFS", u32 n_hd_sec, u8 hd_sec_shift, u8 wbfs_sec_shift,
2 pad bytes, disc_table[] (1 byte per disc, from 0x0C, nonzero = present). Disc 0 info lives at hd sector 1:
0x100-byte copy of the disc header, then u16 wlba_table[] mapping each wbfs sector of the ISO to a wbfs
sector in the container (0 = unallocated, reads as zeros). The whole file is never read into memory.

Wii partition data is AES-128-CBC encrypted per cluster (0x8000 bytes each). Each cluster has a 0x400
encrypted SHA-1 H0/H1/H2 header block, followed by 0x7C00 bytes of encrypted user data. The title key is
stored in the partition ticket, encrypted with the common key. cluster_data() and partition_fst() decrypt
the data and expose the FST file list (disc header dol/main.dol and FST offsets are unencrypted, from the
0x100-byte disc header copy at WBFS offset hd_sector)."""
from __future__ import annotations

import struct

WII_MAGIC = 0x5D1C9EA3

# Common key for all non-Korean Wii titles (extracted via Tweezer Hack, public since 2008)
WII_COMMON_KEY = bytes.fromhex("ebe42a225e8593e448d9c5457381aaf7")
# Korean common key
WII_KOREAN_KEY = bytes.fromhex("63b82bb4f4614e2e13f2fefbba4c9b7e")

# Partition layout constants (wiibrew.org/wiki/Wii_disc#Partition): offsets are relative to the
# partition start (ticket at +0, then 0x18 header fields, then TMD + certs, then data).
PARTITION_TICKET_SIZE = 0x2A4
PARTITION_TICKET_KEY_OFF = 0x1BF      # encrypted title key (16 bytes)
PARTITION_TICKET_TID_OFF = 0x1DC      # title ID (8 bytes, BE) — IV for title key decryption (zero-padded)
PARTITION_TICKET_CKEY_IDX = 0x1F1    # common key index (0=normal, 1=Korean, 2=Wii U Wii mode)
PARTITION_HEADER_H3_OFF = 0x2B4      # H3 table offset >> 2 (table size always 0x18000)
PARTITION_HEADER_DATA_OFF = 0x2B8    # data offset >> 2
PARTITION_HEADER_DATA_SZ = 0x2BC     # data size >> 2

# Cluster layout (relative to the start of the encrypted data area)
CLUSTER_SIZE = 0x8000
CLUSTER_HASH_SIZE = 0x400            # encrypted SHA-1 block (H0/H1/H2) at cluster start
CLUSTER_DATA_OFF = 0x400             # encrypted user data starts here
CLUSTER_IV_OFF = 0x3D0               # IV for user data = decrypted hash block[0x3D0:0x3E0]
CLUSTER_DATA_SIZE = 0x7C00           # user data size


class WBFS:
    def __init__(self, path, disc: int = 0, _fh=None):
        if _fh is not None:
            self.path = "<buffer>"
            self.fh = _fh
        else:
            self.path = str(path)
            self.fh = open(self.path, "rb")
        head = self.fh.read(0x200)
        if len(head) < 0x10 or head[:4] != b"WBFS":
            raise ValueError("not a WBFS image (magic 'WBFS' expected at offset 0)")
        self.n_hd_sec = struct.unpack_from(">I", head, 4)[0]
        self.hd_shift, self.sec_shift = head[8], head[9]
        if not (9 <= self.hd_shift <= 15) or not (15 <= self.sec_shift <= 30) or self.sec_shift < self.hd_shift:
            raise ValueError(f"implausible WBFS geometry hd_shift={self.hd_shift} sec_shift={self.sec_shift}")
        self.hd_sec = 1 << self.hd_shift
        self.sec_size = 1 << self.sec_shift
        self.n_sec = (self.n_hd_sec << self.hd_shift) >> self.sec_shift
        present = [i for i in range(min(self.hd_sec - 0x0C, 255)) if head[0x0C + i] and 0x0C + i < len(head)]
        if not present:
            raise ValueError("WBFS has no disc")
        if disc != 0:
            raise ValueError("only disc 0 of a WBFS image is supported")
        # a Wii disc spans at most 143432*2 sectors of 0x8000 bytes
        self.n_disc_sec = (143432 * 2 * 0x8000 + self.sec_size - 1) // self.sec_size
        self.fh.seek(self.hd_sec)
        info = self.fh.read(0x100 + self.n_disc_sec * 2)
        self.disc_header = info[:0x100]
        self.wlba = struct.unpack_from(f">{self.n_disc_sec}H", info, 0x100)
        if self.disc_header[0x18:0x1C] != struct.pack(">I", WII_MAGIC):
            raise ValueError("WBFS disc is not a Wii disc (0x5D1C9EA3 missing from the disc header copy)")
        self.game_id = self.disc_header[:6].decode("ascii", "replace")
        self.title = self.disc_header[0x20:0x60].split(b"\0")[0].decode("latin-1")
        used = [i for i, w in enumerate(self.wlba) if w]
        self.size = (used[-1] + 1) * self.sec_size if used else 0
        if any(w >= self.n_sec for w in self.wlba):
            raise ValueError("WBFS wlba entry beyond the container")

    def read(self, off: int, n: int) -> bytes:
        """Bytes [off, off+n) of the virtual ISO; unallocated sectors read as zeros."""
        if off < 0 or n < 0:
            raise ValueError("negative offset/length")
        out = bytearray()
        while n > 0:
            idx, inner = divmod(off, self.sec_size)
            take = min(n, self.sec_size - inner)
            w = self.wlba[idx] if idx < len(self.wlba) else 0
            if w:
                self.fh.seek(w * self.sec_size + inner)
                chunk = self.fh.read(take)
                chunk += b"\0" * (take - len(chunk))
            else:
                chunk = b"\0" * take
            out += chunk
            off += take
            n -= take
        return bytes(out)

    def partitions(self) -> list[dict]:
        """Wii partition table (groups at 0x40000): [{type, offset}] (type 0 data, 1 update, 2 channel)."""
        out = []
        groups = struct.unpack(">8I", self.read(0x40000, 32))
        for g in range(4):
            cnt, tab = groups[g * 2], groups[g * 2 + 1] << 2
            if not cnt or cnt > 32:
                continue
            for i in range(cnt):
                o, t = struct.unpack(">II", self.read(tab + i * 8, 8))
                out.append({"type": t, "offset": o << 2, "group": g})
        return out

    def close(self):
        self.fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def extract_iso(self, dest, chunk: int = 1 << 24) -> int:
        """Write the virtual ISO to dest (never the source dir). Returns bytes written."""
        done = 0
        with open(dest, "wb") as o:
            while done < self.size:
                b = self.read(done, min(chunk, self.size - done))
                o.write(b)
                done += len(b)
        return done

    # ------------------------------------------------------------------
    # Wii partition AES decryption (wiibrew.org/wiki/Wii_disc#Partition)
    # ------------------------------------------------------------------

    def _aes(self, key, iv, data):
        from Crypto.Cipher import AES
        return AES.new(key, AES.MODE_CBC, iv).decrypt(data)

    def _decrypt_title_key(self, ticket: bytes) -> bytes:
        """Decrypt the per-partition title key from a partition ticket.

        The title key (16 bytes at ticket offset 0x1BF) is encrypted with the common key
        (AES-128-CBC); the IV is the 8-byte title ID at ticket offset 0x1DC padded with
        8 zero bytes.
        """
        common_key = WII_KOREAN_KEY if ticket[PARTITION_TICKET_CKEY_IDX] == 1 else WII_COMMON_KEY
        enc_key = ticket[PARTITION_TICKET_KEY_OFF:PARTITION_TICKET_KEY_OFF + 16]
        tid = ticket[PARTITION_TICKET_TID_OFF:PARTITION_TICKET_TID_OFF + 8]
        return self._aes(common_key, tid + b"\x00" * 8, enc_key)

    def _partition_geometry(self, part_offset: int) -> tuple[int, int]:
        """(data_off, data_sz) in bytes, from the partition header fields at +0x2B8/+0x2BC
        (offsets are relative to the partition start and shifted by 2)."""
        hdr = self.read(part_offset + PARTITION_TICKET_SIZE, 0x2C)
        data_off, data_sz = struct.unpack_from(">II", hdr, PARTITION_HEADER_DATA_OFF - PARTITION_TICKET_SIZE)
        return data_off << 2, data_sz << 2

    def cluster_data(self, part_offset: int, cluster: int) -> bytes:
        """The decrypted 0x7C00 user data of one cluster of a partition.

        The 0x400 hash block is AES-CBC (title key, zero IV); its plaintext[0x3D0:0x3E0]
        is the IV for the 0x7C00 user data.
        """
        ticket = self.read(part_offset, PARTITION_TICKET_SIZE)
        title_key = self._decrypt_title_key(ticket)
        data_off, _ = self._partition_geometry(part_offset)
        raw = self.read(part_offset + data_off + cluster * CLUSTER_SIZE, CLUSTER_SIZE)
        hash_block = self._aes(title_key, b"\x00" * 16, raw[:CLUSTER_HASH_SIZE])
        iv = hash_block[CLUSTER_IV_OFF:CLUSTER_IV_OFF + 16]
        return self._aes(title_key, iv, raw[CLUSTER_DATA_OFF:CLUSTER_DATA_OFF + CLUSTER_DATA_SIZE])

    def partition_clusters(self, part_offset: int):
        """Generator yielding (cluster_index, decrypted_user_data) for every cluster of a partition."""
        _, data_sz = self._partition_geometry(part_offset)
        for c in range((data_sz + CLUSTER_SIZE - 1) // CLUSTER_SIZE):
            yield c, self.cluster_data(part_offset, c)

    def partition_data(self, part_offset: int, max_bytes: int | None = None) -> bytes:
        """The full decrypted data area of a partition, streamed (never the whole file in memory).

        max_bytes: truncate the result (bytes), for bounded inspection of the head of the data.
        """
        _, data_sz = self._partition_geometry(part_offset)
        out = bytearray()
        for _, user_data in self.partition_clusters(part_offset):
            out += user_data
            if max_bytes is not None and len(out) >= max_bytes:
                break
        return bytes(out[:min(data_sz, len(out))])

    def partition_fst(self, part_offset: int) -> list[dict]:
        """[(path, offset, size)] for every file in a partition's FST.

        The FST lives at the (unencrypted) disc-header FST offset (disc header fields at
        virtual-ISO 0x420/0x424/0x428), relative to the partition start; only the encrypted
        clusters it spans are decrypted. Offsets in the entries are relative to the
        data-area start (cluster c's user data sits at c*0x8000 + 0x400 within the
        partition); read them with partition_file().
        """
        from .gcfst import parse_fst

        fst_off, fst_size = struct.unpack(">II", self.read(0x424, 8))
        c0, c1 = (fst_off + CLUSTER_DATA_OFF) // CLUSTER_SIZE, (fst_off + fst_size - 1) // CLUSTER_SIZE
        fst = b"".join(self.cluster_data(part_offset, c) for c in range(c0, c1 + 1))
        intra = fst_off - c0 * CLUSTER_SIZE
        return [{"path": p, "offset": a, "size": b} for p, a, b, _e in
                parse_fst(fst[intra:intra + fst_size], fst_off)]

    def partition_file(self, part_offset: int, path: str) -> bytes:
        """The decrypted bytes of a single file in a partition, identified by FST path.

        Only the clusters the file spans are decrypted.
        """
        entry = next((e for e in self.partition_fst(part_offset) if e["path"] == path), None)
        if entry is None:
            raise KeyError(f"{path} not in partition FST")
        n = entry["size"]
        out = bytearray()
        pos = 0
        c = entry["offset"] // CLUSTER_SIZE
        intra = entry["offset"] % CLUSTER_SIZE
        while pos < n:
            d = self.cluster_data(part_offset, c)
            take = min(len(d) - intra, n - pos)
            out += d[intra:intra + take]
            pos += take
            c += 1
            intra = 0
        return bytes(out)

    def main_dol(self, part_offset: int) -> bytes:
        """The decrypted main.dol executable (FST path from the disc-header copy at 0x420)."""
        return self.partition_file(part_offset, "main.dol")
