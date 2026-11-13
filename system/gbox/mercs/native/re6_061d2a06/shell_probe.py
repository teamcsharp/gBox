"""Isolated RE6 shell research images; deliberately absent from live capabilities.

Reproduce with build_shell_probe.sh (clang 18.1.3). All addresses are main-relative.
The arm return value means requested, never detonated. See the research note.
"""
from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class Shell:
    item: int
    dti: int
    vtable: int
    attribute0: int


SHELLS = {
    "shell1302": Shell(0x133, 0x2952098, 0x283AD18, 0x1142),
    "shell1303": Shell(0x134, 0x29520D0, 0x283A880, 0x08000022),
    "shell1304": Shell(0x135, 0x2952108, 0x283A3E8, 0x20022),
}
MANAGER_VT = 0x2858318
SHELL_EXPLODE_VT = 0x288C660
SPAWN_BYTES = bytes.fromhex(
    "fd7bbda90883009008610291f65701a9f44f02a9f30303aa5f0008ebf50300aafd030091"
    "8001005408830090084103915f0008eb6001005408830090082104915f0008ebc1060054"
    "567a0090d6a20f9106000014567a0090d662349103000014567a0090d6022291a80a53b9"
    "1f01016b61050054a8d2e6791f0500710b050054c87f009008812391e10302aa000140f9"
    "c2018052e3031faae4031f2a5128ab971f0000f1f40300aa600a00f9e8079f1a681a00b9"
    "600300b4880240f91f0116ebe1020054e00314aae1031faa02008012dc29d997891640b9"
    "0a008512e8031faa958209f929010a0a891600b91f3100f120020054696a68b88a02088b"
    "496100b9499138b9696a68b85f7138b9081100915f8138b949d138b9f5ffff17f4031faa"
    "e00314aaf44f42a9f65741a9fd7bc3a8c0035fd608148752290080529f6e00b9896a2838"
    "480080529f9e38b99fde38b9681a00b9f3ffff17"
)
ARM_BYTES = bytes.fromhex(
    "487a009008a10f919f0008eb487a009008613491841048fa487a009008012291841048fa"
    "61060054080040f91f0104eb01060054088049f91f0101eba1050054080853b91f01026b"
    "41050054280853b91f01036be104005428d0e6791f0500718b04005408d449f9297b00d0"
    "29610c911f0109ebe103005408d849f91f0100eb8103005408c053b91f51007123030054"
    "08e849f9e80200b4084d40f9a80200b4090140f9ca7c00d04a8119913f010aeb01020054"
    "080940f91f0100eba1010054080c40b9085d00121f050871210100540883855208686838"
    "c8000037085479b908011e32085439b920008052c0035fd6e0031faac0035fd6"
)
SPAWN = (0x18F2DB0, "spawn_shell_probe", 344,
         "faef57d8d6125c0911251a057ef776bf0b9126b41d5c45269465a85e796172f8")
ARM = (0x18F2F08, "arm_shell_probe", 248,
       "61f7f1a733d1c455d8b4b5e715de7bf74b16e6e8fe8d7e81440c7e4da96f952f")
IMAGES = {SPAWN[1]: SPAWN_BYTES, ARM[1]: ARM_BYTES}


def image_bytes(image):
    _, name, size, digest = image
    data = IMAGES[name]
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"shell research image checksum mismatch: {name}")
    return data
