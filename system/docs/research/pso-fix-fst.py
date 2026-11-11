"""Correct the GameCube FST reader, measured from this disc.

Probing the header of PSO Episode I & II Plus (GPOE8P) gave: the FST offset is the u32 at **0x424** (0x52400 here), the root entry's **size** field
holds the entry count (3556), and the string table therefore starts at fst + 3556*12. With those three facts the names resolve correctly:

  1: abeniji_fe_obj001_niji.bml    off 211401796  size 4064
  3: AdDrawLineTask.prs            off 211409892  size 3765
  4: AdEnding.rel                  off 211413660  size 8128

Earlier attempts read the FST offset from the wrong field and derived the count from the root's offset field (zero), which produced garbage names.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\gc_extract2.py")
text = path.read_text(encoding="utf-8")

start = text.find("def load(")
end = text.find("def extract(")
if start < 0 or end < 0:
    raise SystemExit("load/extract not found")

body = '''def load(iso=ISO):
    """Return (entry_table, string_table) for the image, using the offsets measured on this disc."""
    with iso.open("rb") as handle:
        header = handle.read(0x460)
        fst_offset = struct.unpack(">I", header[0x424:0x428])[0]
        handle.seek(fst_offset)
        head = handle.read(12)
        count = struct.unpack(">III", head)[2] or 1          # the root directory's size field is the entry count
        handle.seek(fst_offset)
        blob = handle.read(count * 12 + 0x80000)
    table = blob[:count * 12]
    strings = blob[count * 12:]
    return table, strings


def entries(iso=ISO):
    """Every file as (path, offset, size) - directories are walked with an explicit stack."""
    table, strings = load(iso)
    count = len(table) // 12
    out = []
    stack = []                                                    # (end_index, name)
    for index in range(1, count):
        type_name, offset, size = struct.unpack(">III", table[index * 12:index * 12 + 12])
        while stack and stack[-1][0] <= index:
            stack.pop()
        name = cstr(strings, type_name & 0x00FFFFFF)
        path = "/".join([entry[1] for entry in stack] + [name])
        if type_name & 0x01000000:
            out.append((path + "/", None, None))
            stack.append((offset, name))
        else:
            out.append((path, offset, size))
    return out


'''
text = text[:start] + body + text[end:]
path.write_text(text, encoding="utf-8")
print("FST reader corrected: offset 0x424, count from the root's size field")
