"""What does an RE5 skin map look like inside the archive? Tag and first bytes decide whether a colour or a real image can be injected."""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import mt_arc, skin_swap

ROOT = os.path.join(os.path.expanduser("~"), "gBox_alt/switch/romfs/010018100CD46000",
                    "nativeNXx64/ImgNX/Archive")


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "uPl07RebeccaNormal.arc"
    data = open(os.path.join(ROOT, name), "rb").read()
    arc = mt_arc.parse(data)
    groups = skin_swap.material_groups(arc)
    body = skin_swap.body_group(groups)
    print(f"{name}: {len(arc.entries)} entries, body group {body!r}")
    for kind, entry in sorted((groups.get(body) or {}).items()):
        head = entry.data[:24].hex()
        print(f"  {kind:2s} {entry.name[-44:]:44s} size={entry.size:>8} tag={entry.tag:#010x} head={head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
