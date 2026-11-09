"""IPS32 patch that rebinds the visible RE5 enemy class from uEm11 to uEm10.

Measured on the Switch main (module offset 0x4f724, Ghidra 0x0014f724):

    add w4, w20, #0x400     ; 0x3000d00 + 0x400 = uEm11 hash 0x3001100
    ->
    add w4, w20, #0x300     ; 0x3000d00 + 0x300 = uEm10 hash 0x3001000

Delivered as `exefs/main.ips`. A replaced `exefs/main` file is rejected (even byte-identical: the Switch "Launching..."
splash), while IPS patches are applied by the emulator's ExeFS layer.

Use together with `romfs/nativeNXx64/ImgNX/Archive/uEm11.arc` replaced by the uEm10 archive (or a modified uEm10 archive)
to make the camera-visible enemy load the uEm10 class.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
# Keep old probe imports working while using the revision and layout checks maintained by the reusable helper.
from gbox.re5_ips import OFFSET, ORIGINAL, REBIND, make_ips, apply_patch, assert_original, assert_supported_main
