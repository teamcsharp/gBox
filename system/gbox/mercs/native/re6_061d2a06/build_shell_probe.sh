#!/usr/bin/env bash
# Isolated research output only. This does not install into a running process.
set -eu
src=$(cd -- "$(dirname -- "$0")" && pwd)
out=${1:?Supply an isolated output directory}
mkdir -p -- "$out"
out=$(cd -- "$out" && pwd)
clang -target aarch64-linux-gnu -Oz -ffreestanding -fno-stack-protector -fno-pic -fno-asynchronous-unwind-tables -mgeneral-regs-only -c "$src/shell_probe.c" -o "$out/probe.o"
cat > "$out/probe.ld" <<'LD'
SECTIONS {
  .spawn 0x18f2db0 : { *(.text.spawn_shell) }
  .arm 0x18f2f08 : { *(.text.arm_shell) }
  /DISCARD/ : { *(.comment) *(.note*) *(.llvm*) }
}
LD
aarch64-linux-gnu-ld -T "$out/probe.ld" -e spawn_shell --defsym=S_ITEM=0x28ea8e0 --defsym=SHELL2_DTI=0x2952098 --defsym=SHELL3_DTI=0x29520d0 --defsym=SHELL4_DTI=0x2952108 --defsym=SHELL2_VT=0x283ad18 --defsym=SHELL3_VT=0x283a880 --defsym=SHELL4_VT=0x283a3e8 --defsym=MANAGER_VT=0x2858318 --defsym=SHELL_EXPLODE_VT=0x288c660 --defsym=CREATE_ITEM=0x3bcf90 --defsym=DETACH=0xf3d5f0 "$out/probe.o" -o "$out/probe.elf"
for name in spawn arm; do
  aarch64-linux-gnu-objcopy -O binary --only-section=".$name" "$out/probe.elf" "$out/$name.bin"
done
python3 - "$src" "$out" <<'PY'
import runpy, sys
from pathlib import Path
n = runpy.run_path(str(Path(sys.argv[1]) / 'shell_probe.py'))
for name, image in [('spawn', n['SPAWN']), ('arm', n['ARM'])]:
    assert (Path(sys.argv[2]) / (name + '.bin')).read_bytes() == n['image_bytes'](image), name
assert n['SPAWN'][0] + n['SPAWN'][2] <= n['ARM'][0]
assert n['ARM'][0] + n['ARM'][2] == 0x18F3000
print('PASS: isolated shell research images reproduce exactly')
PY
