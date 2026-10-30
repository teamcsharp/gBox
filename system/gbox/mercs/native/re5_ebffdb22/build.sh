#!/usr/bin/env bash
# Exact RE5 EBFFDB22 images; compile into a separate output directory.
set -eu
src=$(cd -- "$(dirname -- "$0")" && pwd)
out=${1:?Supply an output directory}
mkdir -p -- "$out"
out=$(cd -- "$out" && pwd)
aarch64-linux-gnu-as "$src/call.S" -o "$out/call.o"
aarch64-linux-gnu-ld -Ttext=0x118e600 -e bootstrap --defsym=TEMP_VT=0x1a91900 --defsym=ORIGINAL_UPDATE=0x799210 --defsym=ALLOC_FLAGS=0x1e739a8 --defsym=ALLOC_TABLE=0x1d8ac98 "$out/call.o" -o "$out/call.elf"
aarch64-linux-gnu-objcopy -O binary --only-section=.text "$out/call.elf" "$out/call.bin"
clang -target aarch64-linux-gnu -O2 -ffreestanding -fno-stack-protector -fno-pic -fno-asynchronous-unwind-tables -c "$src/spawn.c" -o "$out/spawn.o"
aarch64-linux-gnu-ld -Ttext=0x118e820 --section-start=.rodata=0x118e9c0 -e spawn --defsym=S_ITEM=0x1cf1408 --defsym=FLASH_DTI=0x1d71538 --defsym=CREATE_ITEM=0x1c21c0 --defsym=SET_ROTATION=0xd22880 "$out/spawn.o" -o "$out/spawn.elf"
aarch64-linux-gnu-objcopy -O binary --only-section=.text --only-section=.rodata "$out/spawn.elf" "$out/spawn.bin"
aarch64-linux-gnu-gcc -c -O2 -ffreestanding -fno-stack-protector -fno-pic -fno-asynchronous-unwind-tables -mgeneral-regs-only "$src/explode.c" -o "$out/explode.o"
aarch64-linux-gnu-ld -Ttext=0x118e9d0 -e explode --defsym=FLASH_VT=0x1c5ef58 --defsym=CONFIGURE=0x60d6d0 --defsym=FLASH_UPDATE=0x820e50 "$out/explode.o" -o "$out/explode.elf"
aarch64-linux-gnu-objcopy -O binary --only-section=.text "$out/explode.elf" "$out/explode.bin"
aarch64-linux-gnu-gcc -c -Oz -ffreestanding -fno-stack-protector -fno-pic -fno-asynchronous-unwind-tables -fno-unwind-tables -mgeneral-regs-only "$src/weapons.c" -o "$out/weapons.o"
aarch64-linux-gnu-ld -Ttext=0x118eac8 -e stage --defsym=INVENTORY_VT=0x1c78280 --defsym=ITEM_VT=0x1c782c0 --defsym=S_ITEM=0x1cf1408 --defsym=INIT_INVENTORY=0x91faf0 --defsym=ADD_ITEM=0x1c2ef0 --defsym=CONTAINS=0x1c3d10 --defsym=EQUIP=0x7ab380 "$out/weapons.o" -o "$out/weapons.elf"
aarch64-linux-gnu-objcopy -O binary --only-section=.text "$out/weapons.elf" "$out/weapons.bin"
dispatch=$(aarch64-linux-gnu-nm "$out/call.elf" | awk '$3 == "dispatcher" {print "0x" $1}')
for name in call spawn explode; do
 aarch64-linux-gnu-gcc -O2 -Wall -DDISPATCH_OFFSET="$dispatch" "$src/test_$name.c" -o "$out/test_$name"
 "$out/test_$name" "$out/$name.bin"
done
stage=$(aarch64-linux-gnu-nm "$out/weapons.elf" | awk '$3 == "stage" {print "0x" $1}')
discard=$(aarch64-linux-gnu-nm "$out/weapons.elf" | awk '$3 == "discard" {print "0x" $1}')
commit=$(aarch64-linux-gnu-nm "$out/weapons.elf" | awk '$3 == "commit" {print "0x" $1}')
aarch64-linux-gnu-gcc -O2 -Wall "$src/test_weapons.c" -o "$out/test_weapons"
"$out/test_weapons" "$out/weapons.bin" "$stage" "$discard" "$commit"
python3 - "$src" "$out" <<'PY'
from pathlib import Path
import sys
namespace = {}
exec((Path(sys.argv[1]) / 'code.py').read_text(), namespace)
for name, data in namespace['IMAGES'].items():
 assert (Path(sys.argv[2]) / (name + '.bin')).read_bytes() == data, name
print('PASS: all generated instruction images reproduce exactly')
PY
