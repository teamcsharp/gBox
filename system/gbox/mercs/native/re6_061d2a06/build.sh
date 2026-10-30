#!/usr/bin/env bash
# clang 18.1.3 (spawn), GCC/binutils aarch64-linux-gnu (dispatcher/detonation).
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
for name in call spawn detonate; do
  aarch64-linux-gnu-gcc -O2 -Wall "$src/test_$name.c" -o "$out/test_$name"
  "$out/test_$name" "$out/$name.bin"
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
