
void FUN_000ed60c(int param_1,int param_2,int param_3)

{
  undefined1 uVar1;
  ushort uVar2;
  int *piVar3;
  undefined4 *puVar4;
  undefined4 *puVar5;
  int iVar6;
  uint uVar7;
  int iVar8;
  int iVar9;
  int iVar10;
  undefined1 *puVar11;
  uint *puVar12;
  undefined4 uVar13;
  undefined4 uVar14;
  undefined4 uVar15;
  undefined4 uVar16;
  
  puVar11 = (undefined1 *)(param_2 + param_3 * 0x50);
  *puVar11 = 1;
  *(undefined4 *)(puVar11 + 4) = 1;
  iVar6 = iRam017147ec;
  puVar12 = (uint *)(param_2 + param_3 * 0x420 + 0x140);
  param_1 = param_3 * 0xac + param_1;
  uVar7 = *(uint *)(iRam017147ec + -0x7f70);
  *(uint *)(puVar11 + 8) = (uint)*(byte *)(param_1 + 0x158c);
  *(int *)(puVar11 + 0x10) = (int)*(short *)(param_1 + 0x1590);
  *(int *)(puVar11 + 0x14) = (int)*(short *)(param_1 + 0x1592);
  puVar4 = (undefined4 *)(uVar7 & 0xfffffff0);
  uVar13 = puVar4[1];
  uVar14 = puVar4[2];
  uVar15 = puVar4[3];
  puVar5 = (undefined4 *)((uint)(puVar11 + 0x20) & 0xfffffff0);
  *puVar5 = *puVar4;
  puVar5[1] = uVar13;
  puVar5[2] = uVar14;
  puVar5[3] = uVar15;
  puVar4 = (undefined4 *)(uVar7 & 0xfffffff0);
  uVar13 = *puVar4;
  uVar14 = puVar4[1];
  uVar15 = puVar4[2];
  uVar16 = puVar4[3];
  *(undefined4 *)(puVar11 + 0x40) = 0;
  *(undefined4 *)(puVar11 + 0x44) = 0;
  puVar4 = (undefined4 *)((uint)(puVar11 + 0x30) & 0xfffffff0);
  *puVar4 = uVar13;
  puVar4[1] = uVar14;
  puVar4[2] = uVar15;
  puVar4[3] = uVar16;
  *(undefined4 *)(puVar11 + 0x48) = *(undefined4 *)(param_1 + 0x1594);
  *puVar12 = (uint)*(ushort *)(param_1 + 0x159c);
  uVar2 = *(ushort *)(param_1 + 0x15b4);
  puVar12[4] = 0xffffffff;
  puVar12[1] = (uint)uVar2;
  puVar12[2] = 0xffffffff;
  puVar12[3] = 0xffffffff;
  puVar12[5] = 0;
  if (*(char *)(param_1 + 0x158e) == '\0') {
    puVar12[6] = 1;
  }
  else if (*(char *)(param_1 + 0x158f) == '\0') {
    puVar12[6] = 2;
  }
  else {
    puVar12[6] = 0;
  }
  *(undefined1 *)(puVar12 + 7) = *(undefined1 *)(param_1 + 0x15cc);
  *(undefined1 *)((int)puVar12 + 0x1d) = *(undefined1 *)(param_1 + 0x15cd);
  *(undefined1 *)((int)puVar12 + 0x1e) = *(undefined1 *)(param_1 + 0x15ce);
  *(undefined1 *)((int)puVar12 + 0x1f) = *(undefined1 *)(param_1 + 0x15cf);
  *(undefined1 *)(puVar12 + 8) = *(undefined1 *)(param_1 + 0x15d0);
  *(undefined1 *)((int)puVar12 + 0x21) = *(undefined1 *)(param_1 + 0x15d1);
  *(undefined1 *)((int)puVar12 + 0x22) = *(undefined1 *)(param_1 + 0x15d2);
  *(undefined1 *)((int)puVar12 + 0x23) = *(undefined1 *)(param_1 + 0x15d3);
  uVar1 = *(undefined1 *)(param_1 + 0x15d4);
  puVar12[10] = 0;
  *(undefined1 *)((int)puVar12 + 0x25) = 1;
  *(undefined1 *)(puVar12 + 9) = uVar1;
  puVar12[0xb] = (uint)*(ushort *)(param_1 + 0x159e);
  uVar2 = *(ushort *)(param_1 + 0x15b6);
  puVar12[0xf] = 0xffffffff;
  puVar12[0xc] = (uint)uVar2;
  puVar12[0x10] = 1;
  puVar12[0xd] = 0xffffffff;
  puVar12[0xe] = 0xffffffff;
  if (*(char *)(param_1 + 0x158e) == '\x01') {
    puVar12[0x11] = 1;
  }
  else if (*(char *)(param_1 + 0x158f) == '\x01') {
    puVar12[0x11] = 2;
  }
  else {
    puVar12[0x11] = 0;
  }
  *(undefined1 *)(puVar12 + 0x12) = *(undefined1 *)(param_1 + 0x15d5);
  *(undefined1 *)((int)puVar12 + 0x49) = *(undefined1 *)(param_1 + 0x15d6);
  *(undefined1 *)((int)puVar12 + 0x4a) = *(undefined1 *)(param_1 + 0x15d7);
  *(undefined1 *)((int)puVar12 + 0x4b) = *(undefined1 *)(param_1 + 0x15d8);
  *(undefined1 *)(puVar12 + 0x13) = *(undefined1 *)(param_1 + 0x15d9);
  *(undefined1 *)((int)puVar12 + 0x4d) = *(undefined1 *)(param_1 + 0x15da);
  *(undefined1 *)((int)puVar12 + 0x4e) = *(undefined1 *)(param_1 + 0x15db);
  *(undefined1 *)((int)puVar12 + 0x4f) = *(undefined1 *)(param_1 + 0x15dc);
  uVar1 = *(undefined1 *)(param_1 + 0x15dd);
  puVar12[0x15] = 0;
  *(undefined1 *)((int)puVar12 + 0x51) = 1;
  *(undefined1 *)(puVar12 + 0x14) = uVar1;
  puVar12[0x16] = (uint)*(ushort *)(param_1 + 0x15a0);
  uVar2 = *(ushort *)(param_1 + 0x15b8);
  puVar12[0x1a] = 0xffffffff;
  puVar12[0x17] = (uint)uVar2;
  puVar12[0x1b] = 2;
  puVar12[0x18] = 0xffffffff;
  puVar12[0x19] = 0xffffffff;
  if (*(char *)(param_1 + 0x158e) == '\x02') {
    uVar7 = 1;
LAB_000ee028:
    puVar12[0x1c] = uVar7;
  }
  else {
    uVar7 = (uint)*(char *)(param_1 + 0x158f);
    if (*(char *)(param_1 + 0x158f) == '\x02') goto LAB_000ee028;
    puVar12[0x1c] = 0;
  }
  *(undefined1 *)(puVar12 + 0x1d) = *(undefined1 *)(param_1 + 0x15de);
  *(undefined1 *)((int)puVar12 + 0x75) = *(undefined1 *)(param_1 + 0x15df);
  *(undefined1 *)((int)puVar12 + 0x76) = *(undefined1 *)(param_1 + 0x15e0);
  *(undefined1 *)((int)puVar12 + 0x77) = *(undefined1 *)(param_1 + 0x15e1);
  *(undefined1 *)(puVar12 + 0x1e) = *(undefined1 *)(param_1 + 0x15e2);
  *(undefined1 *)((int)puVar12 + 0x79) = *(undefined1 *)(param_1 + 0x15e3);
  *(undefined1 *)((int)puVar12 + 0x7a) = *(undefined1 *)(param_1 + 0x15e4);
  *(undefined1 *)((int)puVar12 + 0x7b) = *(undefined1 *)(param_1 + 0x15e5);
  uVar1 = *(undefined1 *)(param_1 + 0x15e6);
  puVar12[0x20] = 0;
  *(undefined1 *)((int)puVar12 + 0x7d) = 1;
  *(undefined1 *)(puVar12 + 0x1f) = uVar1;
  puVar12[0x21] = (uint)*(ushort *)(param_1 + 0x15a2);
  uVar2 = *(ushort *)(param_1 + 0x15ba);
  puVar12[0x25] = 0xffffffff;
  puVar12[0x22] = (uint)uVar2;
  puVar12[0x26] = 3;
  puVar12[0x23] = 0xffffffff;
  puVar12[0x24] = 0xffffffff;
  if (*(char *)(param_1 + 0x158e) == '\x03') {
    puVar12[0x27] = 1;
  }
  else if (*(char *)(param_1 + 0x158f) == '\x03') {
    puVar12[0x27] = 2;
  }
  else {
    puVar12[0x27] = 0;
  }
  *(undefined1 *)(puVar12 + 0x28) = *(undefined1 *)(param_1 + 0x15e7);
  *(undefined1 *)((int)puVar12 + 0xa1) = *(undefined1 *)(param_1 + 0x15e8);
  *(undefined1 *)((int)puVar12 + 0xa2) = *(undefined1 *)(param_1 + 0x15e9);
  *(undefined1 *)((int)puVar12 + 0xa3) = *(undefined1 *)(param_1 + 0x15ea);
  *(undefined1 *)(puVar12 + 0x29) = *(undefined1 *)(param_1 + 0x15eb);
  *(undefined1 *)((int)puVar12 + 0xa5) = *(undefined1 *)(param_1 + 0x15ec);
  *(undefined1 *)((int)puVar12 + 0xa6) = *(undefined1 *)(param_1 + 0x15ed);
  *(undefined1 *)((int)puVar12 + 0xa7) = *(undefined1 *)(param_1 + 0x15ee);
  uVar1 = *(undefined1 *)(param_1 + 0x15ef);
  puVar12[0x2b] = 0;
  *(undefined1 *)((int)puVar12 + 0xa9) = 1;
  *(undefined1 *)(puVar12 + 0x2a) = uVar1;
  puVar12[0x2c] = (uint)*(ushort *)(param_1 + 0x15a4);
  uVar2 = *(ushort *)(param_1 + 0x15bc);
  puVar12[0x30] = 0xffffffff;
  puVar12[0x2d] = (uint)uVar2;
  puVar12[0x31] = 4;
  puVar12[0x2e] = 0xffffffff;
  puVar12[0x2f] = 0xffffffff;
  if (*(char *)(param_1 + 0x158e) == '\x04') {
    puVar12[0x32] = 1;
  }
  else if (*(char *)(param_1 + 0x158f) == '\x04') {
    puVar12[0x32] = 2;
  }
  else {
    puVar12[0x32] = 0;
  }
  *(undefined1 *)(puVar12 + 0x33) = *(undefined1 *)(param_1 + 0x15f0);
  *(undefined1 *)((int)puVar12 + 0xcd) = *(undefined1 *)(param_1 + 0x15f1);
  *(undefined1 *)((int)puVar12 + 0xce) = *(undefined1 *)(param_1 + 0x15f2);
  *(undefined1 *)((int)puVar12 + 0xcf) = *(undefined1 *)(param_1 + 0x15f3);
  *(undefined1 *)(puVar12 + 0x34) = *(undefined1 *)(param_1 + 0x15f4);
  *(undefined1 *)((int)puVar12 + 0xd1) = *(undefined1 *)(param_1 + 0x15f5);
  *(undefined1 *)((int)puVar12 + 0xd2) = *(undefined1 *)(param_1 + 0x15f6);
  *(undefined1 *)((int)puVar12 + 0xd3) = *(undefined1 *)(param_1 + 0x15f7);
  uVar1 = *(undefined1 *)(param_1 + 0x15f8);
  puVar12[0x36] = 0;
  *(undefined1 *)((int)puVar12 + 0xd5) = 1;
  *(undefined1 *)(puVar12 + 0x35) = uVar1;
  puVar12[0x37] = (uint)*(ushort *)(param_1 + 0x15a6);
  uVar2 = *(ushort *)(param_1 + 0x15be);
  puVar12[0x3b] = 0xffffffff;
  puVar12[0x38] = (uint)uVar2;
  puVar12[0x3c] = 5;
  puVar12[0x39] = 0xffffffff;
  puVar12[0x3a] = 0xffffffff;
  if (*(char *)(param_1 + 0x158e) == '\x05') {
    puVar12[0x3d] = 1;
  }
  else if (*(char *)(param_1 + 0x158f) == '\x05') {
    puVar12[0x3d] = 2;
  }
  else {
    puVar12[0x3d] = 0;
  }
  *(undefined1 *)(puVar12 + 0x3e) = *(undefined1 *)(param_1 + 0x15f9);
  *(undefined1 *)((int)puVar12 + 0xf9) = *(undefined1 *)(param_1 + 0x15fa);
  *(undefined1 *)((int)puVar12 + 0xfa) = *(undefined1 *)(param_1 + 0x15fb);
  *(undefined1 *)((int)puVar12 + 0xfb) = *(undefined1 *)(param_1 + 0x15fc);
  *(undefined1 *)(puVar12 + 0x3f) = *(undefined1 *)(param_1 + 0x15fd);
  *(undefined1 *)((int)puVar12 + 0xfd) = *(undefined1 *)(param_1 + 0x15fe);
  *(undefined1 *)((int)puVar12 + 0xfe) = *(undefined1 *)(param_1 + 0x15ff);
  *(undefined1 *)((int)puVar12 + 0xff) = *(undefined1 *)(param_1 + 0x1600);
  uVar1 = *(undefined1 *)(param_1 + 0x1601);
  puVar12[0x41] = 0;
  *(undefined1 *)((int)puVar12 + 0x101) = 1;
  *(undefined1 *)(puVar12 + 0x40) = uVar1;
  puVar12[0x42] = (uint)*(ushort *)(param_1 + 0x15a8);
  uVar2 = *(ushort *)(param_1 + 0x15c0);
  puVar12[0x46] = 0xffffffff;
  puVar12[0x43] = (uint)uVar2;
  puVar12[0x47] = 6;
  puVar12[0x44] = 0xffffffff;
  puVar12[0x45] = 0xffffffff;
  if (*(char *)(param_1 + 0x158e) == '\x06') {
    puVar12[0x48] = 1;
  }
  else if (*(char *)(param_1 + 0x158f) == '\x06') {
    puVar12[0x48] = 2;
  }
  else {
    puVar12[0x48] = 0;
  }
  *(undefined1 *)(puVar12 + 0x49) = *(undefined1 *)(param_1 + 0x1602);
  *(undefined1 *)((int)puVar12 + 0x125) = *(undefined1 *)(param_1 + 0x1603);
  *(undefined1 *)((int)puVar12 + 0x126) = *(undefined1 *)(param_1 + 0x1604);
  *(undefined1 *)((int)puVar12 + 0x127) = *(undefined1 *)(param_1 + 0x1605);
  *(undefined1 *)(puVar12 + 0x4a) = *(undefined1 *)(param_1 + 0x1606);
  *(undefined1 *)((int)puVar12 + 0x129) = *(undefined1 *)(param_1 + 0x1607);
  *(undefined1 *)((int)puVar12 + 0x12a) = *(undefined1 *)(param_1 + 0x1608);
  *(undefined1 *)((int)puVar12 + 299) = *(undefined1 *)(param_1 + 0x1609);
  uVar1 = *(undefined1 *)(param_1 + 0x160a);
  puVar12[0x4c] = 0;
  *(undefined1 *)((int)puVar12 + 0x12d) = 1;
  *(undefined1 *)(puVar12 + 0x4b) = uVar1;
  puVar12[0x4d] = (uint)*(ushort *)(param_1 + 0x15aa);
  uVar2 = *(ushort *)(param_1 + 0x15c2);
  puVar12[0x51] = 0xffffffff;
  puVar12[0x4e] = (uint)uVar2;
  puVar12[0x52] = 7;
  puVar12[0x4f] = 0xffffffff;
  puVar12[0x50] = 0xffffffff;
  if (*(char *)(param_1 + 0x158e) == '\a') {
    puVar12[0x53] = 1;
  }
  else if (*(char *)(param_1 + 0x158f) == '\a') {
    puVar12[0x53] = 2;
  }
  else {
    puVar12[0x53] = 0;
  }
  *(undefined1 *)(puVar12 + 0x54) = *(undefined1 *)(param_1 + 0x160b);
  *(undefined1 *)((int)puVar12 + 0x151) = *(undefined1 *)(param_1 + 0x160c);
  *(undefined1 *)((int)puVar12 + 0x152) = *(undefined1 *)(param_1 + 0x160d);
  *(undefined1 *)((int)puVar12 + 0x153) = *(undefined1 *)(param_1 + 0x160e);
  *(undefined1 *)(puVar12 + 0x55) = *(undefined1 *)(param_1 + 0x160f);
  *(undefined1 *)((int)puVar12 + 0x155) = *(undefined1 *)(param_1 + 0x1610);
  *(undefined1 *)((int)puVar12 + 0x156) = *(undefined1 *)(param_1 + 0x1611);
  *(undefined1 *)((int)puVar12 + 0x157) = *(undefined1 *)(param_1 + 0x1612);
  uVar1 = *(undefined1 *)(param_1 + 0x1613);
  puVar12[0x57] = 0;
  *(undefined1 *)((int)puVar12 + 0x159) = 1;
  *(undefined1 *)(puVar12 + 0x56) = uVar1;
  puVar12[0x58] = (uint)*(ushort *)(param_1 + 0x15ac);
  uVar2 = *(ushort *)(param_1 + 0x15c4);
  puVar12[0x5c] = 0xffffffff;
  puVar12[0x59] = (uint)uVar2;
  puVar12[0x5d] = 8;
  puVar12[0x5a] = 0xffffffff;
  puVar12[0x5b] = 0xffffffff;
  if (*(char *)(param_1 + 0x158e) == '\b') {
    puVar12[0x5e] = 1;
  }
  else if (*(char *)(param_1 + 0x158f) == '\b') {
    puVar12[0x5e] = 2;
  }
  else {
    puVar12[0x5e] = 0;
  }
  *(undefined1 *)(puVar12 + 0x5f) = *(undefined1 *)(param_1 + 0x1614);
  *(undefined1 *)((int)puVar12 + 0x17d) = *(undefined1 *)(param_1 + 0x1615);
  *(undefined1 *)((int)puVar12 + 0x17e) = *(undefined1 *)(param_1 + 0x1616);
  *(undefined1 *)((int)puVar12 + 0x17f) = *(undefined1 *)(param_1 + 0x1617);
  *(undefined1 *)(puVar12 + 0x60) = *(undefined1 *)(param_1 + 0x1618);
  *(undefined1 *)((int)puVar12 + 0x181) = *(undefined1 *)(param_1 + 0x1619);
  *(undefined1 *)((int)puVar12 + 0x182) = *(undefined1 *)(param_1 + 0x161a);
  *(undefined1 *)((int)puVar12 + 0x183) = *(undefined1 *)(param_1 + 0x161b);
  uVar1 = *(undefined1 *)(param_1 + 0x161c);
  puVar12[0x62] = 0;
  *(undefined1 *)((int)puVar12 + 0x185) = 1;
  *(undefined1 *)(puVar12 + 0x61) = uVar1;
  puVar12[99] = (uint)*(ushort *)(param_1 + 0x15ae);
  uVar2 = *(ushort *)(param_1 + 0x15c6);
  puVar12[0x67] = 0xffffffff;
  puVar12[100] = (uint)uVar2;
  puVar12[0x68] = 9;
  puVar12[0x65] = 0xffffffff;
  puVar12[0x66] = 0xffffffff;
  if (*(char *)(param_1 + 0x158e) == '\t') {
    puVar12[0x69] = 1;
  }
  else if (*(char *)(param_1 + 0x158f) == '\t') {
    puVar12[0x69] = 2;
  }
  else {
    puVar12[0x69] = 0;
  }
  *(undefined1 *)(puVar12 + 0x6a) = *(undefined1 *)(param_1 + 0x161d);
  *(undefined1 *)((int)puVar12 + 0x1a9) = *(undefined1 *)(param_1 + 0x161e);
  *(undefined1 *)((int)puVar12 + 0x1aa) = *(undefined1 *)(param_1 + 0x161f);
  *(undefined1 *)((int)puVar12 + 0x1ab) = *(undefined1 *)(param_1 + 0x1620);
  *(undefined1 *)(puVar12 + 0x6b) = *(undefined1 *)(param_1 + 0x1621);
  *(undefined1 *)((int)puVar12 + 0x1ad) = *(undefined1 *)(param_1 + 0x1622);
  *(undefined1 *)((int)puVar12 + 0x1ae) = *(undefined1 *)(param_1 + 0x1623);
  *(undefined1 *)((int)puVar12 + 0x1af) = *(undefined1 *)(param_1 + 0x1624);
  uVar1 = *(undefined1 *)(param_1 + 0x1625);
  puVar12[0x6d] = 0;
  *(undefined1 *)((int)puVar12 + 0x1b1) = 1;
  *(undefined1 *)(puVar12 + 0x6c) = uVar1;
  puVar12[0x6e] = (uint)*(ushort *)(param_1 + 0x15b0);
  uVar2 = *(ushort *)(param_1 + 0x15c8);
  puVar12[0x72] = 0xffffffff;
  puVar12[0x6f] = (uint)uVar2;
  puVar12[0x73] = 10;
  puVar12[0x70] = 0xffffffff;
  puVar12[0x71] = 0xffffffff;
  if (*(char *)(param_1 + 0x158e) == '\n') {
    puVar12[0x74] = 1;
  }
  else if (*(char *)(param_1 + 0x158f) == '\n') {
    puVar12[0x74] = 2;
  }
  else {
    puVar12[0x74] = 0;
  }
  *(undefined1 *)(puVar12 + 0x75) = *(undefined1 *)(param_1 + 0x1626);
  *(undefined1 *)((int)puVar12 + 0x1d5) = *(undefined1 *)(param_1 + 0x1627);
  *(undefined1 *)((int)puVar12 + 0x1d6) = *(undefined1 *)(param_1 + 0x1628);
  *(undefined1 *)((int)puVar12 + 0x1d7) = *(undefined1 *)(param_1 + 0x1629);
  *(undefined1 *)(puVar12 + 0x76) = *(undefined1 *)(param_1 + 0x162a);
  *(undefined1 *)((int)puVar12 + 0x1d9) = *(undefined1 *)(param_1 + 0x162b);
  *(undefined1 *)((int)puVar12 + 0x1da) = *(undefined1 *)(param_1 + 0x162c);
  *(undefined1 *)((int)puVar12 + 0x1db) = *(undefined1 *)(param_1 + 0x162d);
  uVar1 = *(undefined1 *)(param_1 + 0x162e);
  puVar12[0x78] = 0;
  *(undefined1 *)((int)puVar12 + 0x1dd) = 1;
  *(undefined1 *)(puVar12 + 0x77) = uVar1;
  puVar12[0x79] = (uint)*(ushort *)(param_1 + 0x15b2);
  uVar2 = *(ushort *)(param_1 + 0x15ca);
  puVar12[0x7d] = 0xffffffff;
  puVar12[0x7a] = (uint)uVar2;
  puVar12[0x7e] = 0xb;
  puVar12[0x7b] = 0xffffffff;
  puVar12[0x7c] = 0xffffffff;
  if (*(char *)(param_1 + 0x158e) == '\v') {
    puVar12[0x7f] = 1;
  }
  else if (*(char *)(param_1 + 0x158f) == '\v') {
    puVar12[0x7f] = 2;
  }
  else {
    puVar12[0x7f] = 0;
  }
  piVar3 = *(int **)(iVar6 + -0x7fb0);
  *(undefined1 *)(puVar12 + 0x80) = *(undefined1 *)(param_1 + 0x162f);
  *(undefined1 *)((int)puVar12 + 0x201) = *(undefined1 *)(param_1 + 0x1630);
  *(undefined1 *)((int)puVar12 + 0x202) = *(undefined1 *)(param_1 + 0x1631);
  *(undefined1 *)((int)puVar12 + 0x203) = *(undefined1 *)(param_1 + 0x1632);
  *(undefined1 *)(puVar12 + 0x81) = *(undefined1 *)(param_1 + 0x1633);
  *(undefined1 *)((int)puVar12 + 0x205) = *(undefined1 *)(param_1 + 0x1634);
  *(undefined1 *)((int)puVar12 + 0x206) = *(undefined1 *)(param_1 + 0x1635);
  *(undefined1 *)((int)puVar12 + 0x207) = *(undefined1 *)(param_1 + 0x1636);
  *(undefined1 *)(puVar12 + 0x82) = *(undefined1 *)(param_1 + 0x1637);
  puVar12[0x83] = 0;
  *(undefined1 *)((int)puVar12 + 0x209) = 1;
  *(undefined4 *)(param_2 + param_3 * 4 + 0x11c0) = 0xc;
  if (*(int *)(*piVar3 + *(int *)(*piVar3 + 0x24) * 0x5940 + 0x23cd4) == param_3) {
    return;
  }
  puVar4 = *(undefined4 **)(iVar6 + -0x7f6c);
  uVar13 = *puVar4;
  iVar8 = func_0x00201ba8(uVar13,3);
  iVar9 = func_0x00201ba8(uVar13,6);
  iVar10 = func_0x00201ba8(uVar13,7);
  if ((iVar8 == 0 && iVar9 == 0) && iVar10 == 0) {
    if (param_3 == 0) {
      if (*(char *)(param_1 + 0x158d) == '\x03') goto LAB_000ee018;
    }
    else if ((param_3 == 1) && (*(char *)(param_1 + 0x158d) == '\x04')) {
LAB_000ee018:
      *(undefined1 *)(param_1 + 0x158d) = 0;
    }
  }
  uVar13 = *puVar4;
  iVar8 = func_0x00201ba8(uVar13,4);
  iVar9 = func_0x00201ba8(uVar13,6);
  iVar10 = func_0x00201ba8(uVar13,7);
  if ((iVar8 == 0 && iVar9 == 0) && iVar10 == 0) {
    if (param_3 == 0) {
      if (*(char *)(param_1 + 0x158d) != '\x04') goto LAB_000edf64;
    }
    else if ((param_3 != 1) || (*(char *)(param_1 + 0x158d) != '\x03')) goto LAB_000edf64;
    *(undefined1 *)(param_1 + 0x158d) = 0;
  }
LAB_000edf64:
  piVar3 = *(int **)(iVar6 + -0x7ffc);
  func_0x009c08e4(*(undefined4 *)(*piVar3 + 0x182d4),param_3,*(undefined1 *)(param_1 + 0x158d));
  func_0x009c0904(*(undefined4 *)(*piVar3 + 0x182d4),param_3,*(undefined4 *)(param_1 + 0x1598));
  return;
}


