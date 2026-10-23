
bool FUN_009c372c(int param_1)

{
  undefined4 uVar1;
  uint uVar2;
  undefined4 *puVar3;
  int iVar4;
  uint uVar5;
  undefined4 *puVar6;
  undefined4 uVar7;
  undefined4 uVar8;
  undefined4 uVar9;
  undefined4 uVar10;
  
  iVar4 = iRam01714ecc;
  if (*(int *)(param_1 + 0xc) == 0) {
    puVar6 = *(undefined4 **)(iRam01714ecc + -0x7fdc);
  }
  else {
    puVar6 = *(undefined4 **)(iRam01714ecc + -0x7fdc);
    (*(code *)**(undefined4 **)(*(int *)*puVar6 + 0x1c))((int *)*puVar6,*(int *)(param_1 + 0xc));
    *(undefined4 *)(param_1 + 0xc) = 0;
  }
  uVar5 = (*(code *)**(undefined4 **)(*(int *)*puVar6 + 0x18))((int *)*puVar6,0xe0,0x20);
  *(uint *)(param_1 + 0xc) = uVar5;
  if (uVar5 != 0) {
    uVar2 = *(uint *)(iVar4 + -0x7fd4);
    uVar1 = *(undefined4 *)(iVar4 + -0x7ff4);
    puVar6 = (undefined4 *)(*(uint *)(iVar4 + -0x7fd8) & 0xfffffff0);
    uVar7 = puVar6[1];
    uVar8 = puVar6[2];
    uVar9 = puVar6[3];
    puVar3 = (undefined4 *)(uVar5 & 0xfffffff0);
    *puVar3 = *puVar6;
    puVar3[1] = uVar7;
    puVar3[2] = uVar8;
    puVar3[3] = uVar9;
    puVar6 = (undefined4 *)(uVar2 & 0xfffffff0);
    uVar7 = *puVar6;
    uVar8 = puVar6[1];
    uVar9 = puVar6[2];
    uVar10 = puVar6[3];
    *(undefined4 *)(uVar5 + 0x38) = uVar1;
    *(undefined4 *)(uVar5 + 0x28) = 0;
    puVar6 = (undefined4 *)(uVar5 + 0x10 & 0xfffffff0);
    *puVar6 = uVar7;
    puVar6[1] = uVar8;
    puVar6[2] = uVar9;
    puVar6[3] = uVar10;
    *(undefined4 *)(uVar5 + 0x2c) = 0;
    *(undefined4 *)(uVar5 + 0x30) = 0;
    *(undefined4 *)(uVar5 + 0x34) = 0;
    *(undefined4 *)(uVar5 + 0x3c) = 0;
    *(undefined4 *)(uVar5 + 0x40) = 0;
    *(undefined4 *)(uVar5 + 0x44) = 0;
    *(undefined1 *)(uVar5 + 0x48) = 0;
    *(undefined1 *)(uVar5 + 0x94) = 0;
    *(undefined1 *)(uVar5 + 0x49) = 0;
    func_0x009cb50c(uVar5 + 0x4c);
    *(undefined4 *)(uVar5 + 0xdc) = 0;
    *(undefined4 *)(uVar5 + 0x98) = 0;
    *(undefined1 *)(uVar5 + 0x94) = 0;
    *(undefined4 *)(uVar5 + 0x20) = 0;
    *(undefined4 *)(uVar5 + 0xa0) = 0;
    *(undefined4 *)(uVar5 + 0xa4) = 0;
    *(undefined1 *)(uVar5 + 0xa8) = 0;
    *(undefined4 *)(uVar5 + 0xbc) = 0;
    *(undefined4 *)(uVar5 + 0xc0) = 0;
    *(undefined4 *)(uVar5 + 0xc4) = 0;
    *(undefined4 *)(uVar5 + 200) = 0;
    *(undefined4 *)(uVar5 + 0xd4) = 0;
    *(undefined4 *)(uVar5 + 0xcc) = 0;
    *(undefined4 *)(uVar5 + 0xd8) = 0;
    *(undefined4 *)(uVar5 + 0xd0) = 0;
    *(undefined4 *)(uVar5 + 0xac) = 0xffffffff;
    *(undefined4 *)(uVar5 + 0x9c) = 0xffffffff;
    *(undefined4 *)(uVar5 + 0x24) = 0xffffffff;
  }
  return uVar5 != 0;
}


