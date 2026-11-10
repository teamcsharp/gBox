#!/usr/bin/env bash
# clang 18.1.3 (spawn, spawn_at), GCC/binutils aarch64-linux-gnu (dispatcher/detonation/detonate_at).
# Supply a separate output directory; verified shipped bytes are never replaced.
set -eu
src=$(cd -- "$(dirname -- "$0")" && pwd)
out=${1:?Supply an output directory}
mkdir -p -- "$out"
out=$(cd -- "$out" && pwd)
aarch64-linux-gnu-as "$src/call.S" -o "$out/call.o"
aarch64-linux-gnu-ld -Ttext=0x18f2640 -e bootstrap --defsym=ORIGINAL_VT=0x2858318 --defsym=TEMP_VT=0x25a3100 --defsym=ORIGINAL_UPDATE=0xf8ce10 --defsym=ALLOC_FLAGS=0x2a51b78 --defsym=ALLOC_TABLE=0x296cc48 "$out/call.o" -o "$out/call.elf"
aarch64-linux-gnu-objcopy -O binary --only-section=.text "$out/call.elf" "$out/call.bin"
clang -target aarch64-linux-gnu -O2 -ffreestanding -fno-stack-protector -fno-pic -fno-asynchronous-unwind-tables -c "$src/spawn.c" -o "$out/spawn.o"
aarch64-linux-gnu-ld -Ttext=0x18f2880 --section-start=.rodata=0x18f2970 -e spawn --defsym=S_ITEM=0x28ea8e0 --defsym=FLASH_DTI=0x2951500 --defsym=S_STATS=0x28e9be0 --defsym=CREATE_ITEM=0x3bcf90 --defsym=SET_ROTATION=0x125ccf0 --defsym=REGISTER_PROJECTILE=0x3a9e70 "$out/spawn.o" -o "$out/spawn.elf"
aarch64-linux-gnu-objcopy -O binary --only-section=.text --only-section=.rodata "$out/spawn.elf" "$out/spawn.bin"
aarch64-linux-gnu-gcc -c -O2 -ffreestanding -fno-stack-protector -fno-pic -fno-asynchronous-unwind-tables -mgeneral-regs-only "$src/detonate.c" -o "$out/detonate.o"
aarch64-linux-gnu-ld -Ttext=0x18f29c0 -e detonate --defsym=FLASH_VT=0x284aeb8 --defsym=THROW_VT=0x288c9a0 --defsym=BOMB_VT=0x288c868 --defsym=MANAGER_VT=0x2858318 --defsym=REQUEST=0xf8c7c0 --defsym=UPDATE=0xf8ce10 "$out/detonate.o" -o "$out/detonate.elf"
aarch64-linux-gnu-objcopy -O binary --only-section=.text "$out/detonate.elf" "$out/detonate.bin"
# Grenade ring (2026-11-10): the hand / incendiary / flash classes (uWp1091 / uWp1093 / uWp1095) at a chosen point.
# Placed in the same zero padding after detonate (main+0x18f2aa8..0x18f3000, the end of the executable page).
clang -target aarch64-linux-gnu -O2 -ffreestanding -fno-stack-protector -fno-pic -fno-asynchronous-unwind-tables -fno-vectorize -fno-slp-vectorize -c "$src/spawn_at.c" -o "$out/spawn_at.o"
aarch64-linux-gnu-ld -Ttext=0x18f2ac0 -e spawn_at --defsym=S_ITEM=0x28ea8e0 --defsym=HAND_DTI=0x2951490 --defsym=FIRE_DTI=0x29514c8 --defsym=FLASH_DTI=0x2951500 --defsym=S_STATS=0x28e9be0 --defsym=CREATE_ITEM=0x3bcf90 --defsym=SET_ROTATION=0x125ccf0 --defsym=REGISTER_PROJECTILE=0x3a9e70 "$out/spawn_at.o" -o "$out/spawn_at.elf"
aarch64-linux-gnu-objcopy -O binary --only-section=.text "$out/spawn_at.elf" "$out/spawn_at.bin"
aarch64-linux-gnu-gcc -c -O2 -ffreestanding -fno-stack-protector -fno-pic -fno-asynchronous-unwind-tables -mgeneral-regs-only "$src/detonate_at.c" -o "$out/detonate_at.o"
aarch64-linux-gnu-ld -Ttext=0x18f2c00 -e detonate_at --defsym=HAND_VT=0x284b788 --defsym=FIRE_VT=0x284b328 --defsym=FLASH_VT=0x284aeb8 --defsym=THROW_VT=0x288c9a0 --defsym=BOMB_VT=0x288c868 --defsym=MANAGER_VT=0x2858318 --defsym=REQUEST=0xf8c7c0 --defsym=UPDATE=0xf8ce10 "$out/detonate_at.o" -o "$out/detonate_at.elf"
aarch64-linux-gnu-objcopy -O binary --only-section=.text "$out/detonate_at.elf" "$out/detonate_at.bin"
for name in call spawn detonate; do
  aarch64-linux-gnu-gcc -O2 -Wall "$src/test_$name.c" -o "$out/test_$name"
  "$out/test_$name" "$out/$name.bin"
done
for name in spawn_at detonate_at; do
  aarch64-linux-gnu-gcc -O2 -Wall "$src/test_$name.c" -o "$out/test_$name"
  "$out/test_$name" "$out/$name.bin" "$(stat -c %s "$out/$name.bin")"
done
python3 - "$src" "$out" <<'PY'
from pathlib import Path
import sys
namespace = {}
exec((Path(sys.argv[1]) / 'code.py').read_text(), namespace)
for name, data in namespace['IMAGES'].items():
    assert (Path(sys.argv[2]) / (name + '.bin')).read_bytes() == data, name
print('PASS: all generated instruction images reproduce exactly')
PY
