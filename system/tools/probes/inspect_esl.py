"""What is inside a RE4 Switch `.esl` file? The game ships one family per character (`emleon00..07`).

If these name the model packs, the character->pack mapping is a decode rather than a bisection. This prints the size, the
first words, every printable string, and the integer ranges - enough to say whether a table is there and whether it holds
names or ids.
"""
import os
import re
import struct
import sys

ETC = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), "010099A00BC1E000", "bio4", "etc")
NAME = sys.argv[1] if len(sys.argv) > 1 else "emleon00.esl"


def main() -> int:
    path = os.path.join(ETC, NAME)
    data = open(path, "rb").read()
    print(f"{NAME}: {len(data)} bytes")
    print("first 8 words:", [hex(v) for v in struct.unpack_from(">8I", data, 0)])
    strings = [m.group().decode("latin-1") for m in re.finditer(rb"[ -~]{3,}", data)]
    print(f"printable strings: {len(strings)}")
    for text in strings[:24]:
        print("   ", text[:60])
    # integers that look like pack ids (0..0x40) and any that look like a table of counts
    small = [v for v in struct.unpack_from(f">{len(data) // 2}H", data, 0)][:24]
    print("first 24 halfwords:", [hex(v) for v in small])
    print("contains 'pl':", b"pl" in data.lower(), "| contains 'udas':", b"udas" in data.lower(),
          "| contains '.esl':", b".esl" in data.lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
