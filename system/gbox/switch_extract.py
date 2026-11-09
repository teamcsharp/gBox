"""A command line for the client-side Switch readers: NSP members, NCA sections, ExeFS and RomFS files.

Uses only `gbox.switch_nca`, `gbox.switch_romfs` and `gbox.switch_bktr` (CPU AES through `cryptography`) plus the
operator's `prod.keys` — the path that works where the shipped hactool does not (it reports `Invalid NCA header` for
this library's containers on both the i9 and the Spark).

    python -m gbox.switch_extract info      <container.nsp> [--keys prod.keys]
    python -m gbox.switch_extract exefs     <container.nsp> <nca-name> <out-dir> [--keys prod.keys]
    python -m gbox.switch_extract romfs-list <container.nsp> <nca-name> [--limit 20] [--keys prod.keys]
    python -m gbox.switch_extract romfs-get <container.nsp> <nca-name> <path> <out-file> [--keys prod.keys]
    python -m gbox.switch_extract bktr      <container.nsp> <nca-name> [--keys prod.keys]

`info` needs no keys (it reads the container and the ticket names); every other command needs `prod.keys`.
"""
import argparse
import struct
import sys
from pathlib import Path

from . import switch_bktr, switch_nca, switch_romfs


def members(path: str | Path) -> list[dict]:
    """The container's PFS0 members: [{name, offset, size}] with offsets relative to the container."""
    with Path(path).open("rb") as fh:
        magic, count, strings_size, _reserved = struct.unpack("<4sIII", fh.read(0x10))
        if magic != b"PFS0":
            raise ValueError(f"{Path(path).name}: not a PFS0 container")
        rows = [struct.unpack("<QQII", fh.read(0x18)) for _ in range(count)]
        table = fh.read(strings_size)
        data_at = 0x10 + count * 0x18 + strings_size
        out = []
        for offset, size, name_at, _pad in rows:
            end = table.find(b"\x00", name_at)
            out.append({"name": table[name_at:end if end >= 0 else None].decode("utf-8", "replace"),
                        "offset": data_at + offset, "size": size})
        return out


class Nca:
    """One NCA inside a container: its header, its title key and a section reader that decrypts on the fly."""

    def __init__(self, container: str | Path, name: str, keys: dict):
        self.container, self.keys = Path(container), keys
        self.member = next((m for m in members(container) if m["name"] == name), None)
        if not self.member:
            raise ValueError(f"{name} is not a member of {Path(container).name}")
        with self.container.open("rb") as fh:
            fh.seek(self.member["offset"])
            self.header = switch_nca.decrypt_header(fh.read(switch_nca.HEADER_SIZE), keys)
            ticket = next((m for m in members(container) if m["name"].endswith(".tik")), None)
            if not ticket:
                raise ValueError("no ticket in the container: a title key cannot be derived")
            fh.seek(ticket["offset"])
            self.ticket = fh.read(ticket["size"])
        self.key = switch_nca.title_key(self.ticket, keys, switch_nca.titlekek_index(self.header))

    def section(self, index: int) -> dict:
        for section in self.header["sections"]:
            if section["index"] == index:
                return section
        raise ValueError(f"no section {index} in this NCA")

    def read_section(self, index: int, offset: int, size: int) -> bytes:
        """`size` bytes at `offset` of section `index`, decrypted (CTR sections only)."""
        section = self.section(index)
        if section["crypt_type"] != switch_nca.CRYPT_CTR:
            raise ValueError(f"section {index} uses crypt type {section['crypt_type']}, not CTR")
        aligned = offset & ~0xF
        pad = offset - aligned
        need = ((size + pad + 15) // 16) * 16
        with self.container.open("rb") as fh:
            fh.seek(self.member["offset"] + section["offset"] + aligned)
            blob = fh.read(need)
        iv = switch_nca.section_iv(section["section_ctr"], section["offset"] + aligned)
        return switch_nca.ctr_decrypt(self.key, blob, iv)[pad:pad + size]

    def romfs(self) -> dict:
        """The RomFS at the first ROMFS section, walked: {header, files}.

        The RomFS header sits at the last IVFC level's logical offset (the level headers live in the section's FS
        header, at `header + 0x400 + index*0x200 + 8 + 0x10 + level*0x18`), not at the section start.
        """
        sections = [s for s in self.header["sections"] if s["fs_type"] == switch_nca.FS_ROMFS]
        if not sections:
            raise ValueError("no RomFS section in this NCA")
        section = sections[0]
        fs = 0x400 + section["index"] * 0x200 + 8
        levels = [struct.unpack_from("<Q", self.header["header"], fs + 0x10 + i * 0x18)[0] for i in range(6)]
        at = levels[-1]
        if at + switch_romfs.HEADER_SIZE > section["size"]:
            raise ValueError(f"the RomFS header offset {at:#x} is outside the section")
        header = switch_romfs.parse_header(self.read_section(section["index"], at, switch_romfs.HEADER_SIZE))
        self._romfs_at = at
        return switch_romfs.read(lambda off, size: self.read_section(section["index"], off, size), at)


def _keys(args) -> dict:
    if not args.keys:
        raise SystemExit("this command needs --keys (a prod.keys file)")
    return switch_nca.load_keys(args.keys)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gbox.switch_extract", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("info", "exefs", "romfs-list", "romfs-get", "bktr"):
        p = sub.add_parser(name)
        p.add_argument("container")
        if name != "info":
            p.add_argument("nca")
            p.add_argument("--keys", default="")
        if name == "exefs":
            p.add_argument("out_dir")
        if name == "romfs-list":
            p.add_argument("--limit", type=int, default=20)
        if name == "romfs-get":
            p.add_argument("path")
            p.add_argument("out_file")
    args = parser.parse_args(argv)

    if args.cmd == "info":
        for member in members(args.container):
            print(f"{member['name']} {member['size']}")
        return 0

    nca = Nca(args.container, args.nca, _keys(args))
    print(f"{args.nca}: title {nca.header['title_id']} size {nca.header['size']:#x} "
          f"content {nca.header['content_type']} keyblob {nca.header['keyblob']}")
    for section in nca.header["sections"]:
        print(f"  section {section['index']}: {section['offset']:#x}+{section['size']:#x} "
              f"fs {section['fs_type']} crypt {section['crypt_type']}")
    if args.cmd == "exefs":
        pfs0 = next((s for s in nca.header["sections"]
                     if s["fs_type"] == switch_nca.FS_PFS0 and s["partition_type"] == 1), None)
        if not pfs0:
            raise SystemExit("no PFS0 (ExeFS) section")
        blob = nca.read_section(pfs0["index"], pfs0["pfs0_offset"], pfs0["pfs0_size"])
        files = switch_nca.read_pfs0(blob)
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (out / name).write_bytes(data)
            print(f"  {name} {len(data)}")
    elif args.cmd == "romfs-list":
        out = nca.romfs()
        print(f"  {len(out['files'])} files")
        for entry in out["files"][:args.limit]:
            print(f"  {entry['size']:#x} {entry['path']}")
    elif args.cmd == "romfs-get":
        out = nca.romfs()
        entry = next((f for f in out["files"] if f["path"] == args.path), None)
        if not entry:
            raise SystemExit(f"{args.path} is not in this RomFS")
        section = next(s for s in nca.header["sections"] if s["fs_type"] == switch_nca.FS_ROMFS)
        data = nca.read_section(section["index"], getattr(nca, "_romfs_at") + out["header"]["data_offset"]
                                + entry["offset"], entry["size"])
        Path(args.out_file).write_bytes(data)
        print(f"  {args.path}: {len(data)} bytes -> {args.out_file}")
    elif args.cmd == "bktr":
        h = nca.header["header"]
        out = switch_bktr.superblock_offsets(h, next(s["index"] for s in nca.header["sections"]
                                                     if s["fs_type"] == switch_nca.FS_ROMFS))
        print(f"  relocation {out['relocation']['offset']:#x}+{out['relocation']['size']:#x} "
              f"count {out['relocation']['count']}")
        print(f"  subsection {out['subsection']['offset']:#x}+{out['subsection']['size']:#x} "
              f"count {out['subsection']['count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
