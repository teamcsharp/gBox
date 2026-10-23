
void FUN_0015fa34(int param_1,int param_2)

{
  bool bVar1;
  int iVar2;
  int *piVar3;
  uint uVar4;
  int iVar5;
  undefined4 *puVar6;
  undefined4 *puVar7;
  int iVar8;
  int iVar9;
  int iVar10;
  int unaff_r23;
  int unaff_r25;
  int unaff_r30;
  undefined4 uVar11;
  undefined4 uVar12;
  undefined4 uVar13;
  
  iVar2 = *(int *)(unaff_r30 + -0x8000);
  param_1 = param_1 * 4;
  iVar8 = *(int *)(iVar2 + 0x33c);
  if (*(int *)(iVar8 + param_1 + 0x50 + 8) == 0) {
    return;
  }
  iVar10 = *(int *)(iVar8 + param_1 + 0x48);
  if (iVar10 == 0) {
    return;
  }
  if (*(int *)(iVar8 + param_1 + 0x50) == 0) {
    return;
  }
  if (*(int *)(iVar8 + param_1 + 0x68) == 0) {
    return;
  }
  if (*(int *)(iVar8 + param_1 + 0x70) == 0) {
    return;
  }
  if (*(int *)(iVar8 + param_1 + 0x70 + 8) == 0) {
    return;
  }
  if (*(int *)(iVar8 + param_1 + 0xf0) == 0) {
    return;
  }
  if (*(char *)(param_2 + 4) == '\0') {
    *(uint *)(iVar10 + 4) = *(uint *)(iVar10 + 4) & 0xfffdffff;
  }
  else {
    *(uint *)(iVar10 + 4) =
         *(uint *)(iVar10 + 4) & 0xffc0ffff | *(uint *)(iVar10 + 4) & 0x3f0000 | 0x20000;
  }
  iVar8 = *(int *)(*(int *)(iVar2 + 0x33c) + param_1 + 0x50);
  if (*(char *)(param_2 + 5) == '\0') {
    *(uint *)(iVar8 + 4) = *(uint *)(iVar8 + 4) & 0xfffdffff;
  }
  else {
    *(uint *)(iVar8 + 4) =
         *(uint *)(iVar8 + 4) & 0xffc0ffff | *(uint *)(iVar8 + 4) & 0x3f0000 | 0x20000;
  }
  iVar8 = *(int *)(*(int *)(iVar2 + 0x33c) + param_1 + 0x68);
  if (*(char *)(param_2 + 6) == '\0') {
    *(uint *)(iVar8 + 4) = *(uint *)(iVar8 + 4) & 0xfffdffff;
  }
  else {
    *(uint *)(iVar8 + 4) =
         *(uint *)(iVar8 + 4) & 0xffc0ffff | *(uint *)(iVar8 + 4) & 0x3f0000 | 0x20000;
  }
  iVar8 = *(int *)(*(int *)(iVar2 + 0x33c) + param_1 + 0x70);
  if (*(char *)(param_2 + 7) == '\0') {
    *(uint *)(iVar8 + 4) = *(uint *)(iVar8 + 4) & 0xfffdffff;
  }
  else {
    *(uint *)(iVar8 + 4) =
         *(uint *)(iVar8 + 4) & 0xffc0ffff | *(uint *)(iVar8 + 4) & 0x3f0000 | 0x20000;
  }
  iVar8 = *(int *)(*(int *)(iVar2 + 0x33c) + param_1 + 0x78);
  if (*(char *)(param_2 + 8) == '\0') {
    *(uint *)(iVar8 + 4) = *(uint *)(iVar8 + 4) & 0xfffdffff;
  }
  else {
    *(uint *)(iVar8 + 4) =
         *(uint *)(iVar8 + 4) & 0xffc0ffff | *(uint *)(iVar8 + 4) & 0x3f0000 | 0x20000;
  }
  piVar3 = *(int **)(unaff_r30 + -0x7ee8);
  iVar8 = unaff_r25 * 0x5e0 + 0x100 + *piVar3;
  if (iVar8 != 0) {
    *(undefined4 *)(iVar8 + 0x1f8) = *(undefined4 *)(param_2 + 0x44);
  }
  iVar10 = *(int *)(*(int *)(iVar2 + 0x33c) + param_1 + 0x50);
  iVar8 = *(int *)(*(int *)(iVar2 + 0x33c) + param_1 + 0x48);
  if ((iVar8 != 0) && (iVar10 != 0)) {
    *(undefined4 *)(iVar8 + 0x98) = *(undefined4 *)(unaff_r23 + 0x48);
    *(undefined4 *)(iVar8 + 0x9c) = *(undefined4 *)(unaff_r23 + 0x4c);
    *(undefined4 *)(iVar8 + 0xa0) = *(undefined4 *)(unaff_r23 + 0x50);
    *(undefined4 *)(iVar8 + 0xa4) = *(undefined4 *)(unaff_r23 + 0x54);
    *(undefined4 *)(iVar8 + 0xa8) = *(undefined4 *)(unaff_r23 + 0x58);
    uVar11 = *(undefined4 *)(unaff_r23 + 0x60);
    uVar12 = *(undefined4 *)(unaff_r23 + 100);
    uVar13 = *(undefined4 *)(unaff_r23 + 0x68);
    *(undefined4 *)(iVar8 + 0xb0) = *(undefined4 *)(unaff_r23 + 0x5c);
    *(undefined4 *)(iVar8 + 0xb4) = uVar11;
    *(undefined4 *)(iVar8 + 0xb8) = uVar12;
    *(undefined4 *)(iVar8 + 0xbc) = uVar13;
    uVar11 = *(undefined4 *)(unaff_r23 + 0x70);
    uVar12 = *(undefined4 *)(unaff_r23 + 0x74);
    uVar13 = *(undefined4 *)(unaff_r23 + 0x78);
    *(undefined4 *)(iVar8 + 0xc0) = *(undefined4 *)(unaff_r23 + 0x6c);
    *(undefined4 *)(iVar8 + 0xc4) = uVar11;
    *(undefined4 *)(iVar8 + 200) = uVar12;
    *(undefined4 *)(iVar8 + 0xcc) = uVar13;
    uVar11 = *(undefined4 *)(unaff_r23 + 0x80);
    uVar12 = *(undefined4 *)(unaff_r23 + 0x84);
    uVar13 = *(undefined4 *)(unaff_r23 + 0x88);
    *(undefined4 *)(iVar8 + 0xd0) = *(undefined4 *)(unaff_r23 + 0x7c);
    *(undefined4 *)(iVar8 + 0xd4) = uVar11;
    *(undefined4 *)(iVar8 + 0xd8) = uVar12;
    *(undefined4 *)(iVar8 + 0xdc) = uVar13;
    uVar11 = *(undefined4 *)(unaff_r23 + 0x90);
    uVar12 = *(undefined4 *)(unaff_r23 + 0x94);
    uVar13 = *(undefined4 *)(unaff_r23 + 0x98);
    *(undefined4 *)(iVar8 + 0xe0) = *(undefined4 *)(unaff_r23 + 0x8c);
    *(undefined4 *)(iVar8 + 0xe4) = uVar11;
    *(undefined4 *)(iVar8 + 0xe8) = uVar12;
    *(undefined4 *)(iVar8 + 0xec) = uVar13;
    *(undefined4 *)(iVar8 + 0xf0) = *(undefined4 *)(unaff_r23 + 0x9c);
    *(undefined4 *)(iVar8 + 0xf4) = *(undefined4 *)(unaff_r23 + 0xa0);
    *(undefined4 *)(iVar10 + 0x40) = *(undefined4 *)(unaff_r23 + 0xa4);
    *(undefined4 *)(iVar10 + 0x44) = *(undefined4 *)(unaff_r23 + 0xa8);
    puVar6 = (undefined4 *)(unaff_r23 + 0xb0U & 0xfffffff0);
    uVar11 = puVar6[1];
    uVar12 = puVar6[2];
    uVar13 = puVar6[3];
    puVar7 = (undefined4 *)(iVar10 + 0x50U & 0xfffffff0);
    *puVar7 = *puVar6;
    puVar7[1] = uVar11;
    puVar7[2] = uVar12;
    puVar7[3] = uVar13;
  }
  iVar10 = *(int *)(iVar2 + 0x33c);
  iVar8 = *(int *)(iVar10 + param_1 + 0x68);
  if (iVar8 != 0) {
    uVar11 = **(undefined4 **)(unaff_r30 + -0x7ef8);
    uVar12 = *(undefined4 *)(unaff_r23 + 0xec);
    uVar13 = *(undefined4 *)(unaff_r23 + 0xe4);
    *(undefined4 *)(iVar8 + 0x38) = *(undefined4 *)(unaff_r23 + 0xe8);
    *(undefined4 *)(iVar8 + 0x3c) = uVar12;
    *(undefined4 *)(iVar8 + 0x34) = uVar13;
    *(undefined4 *)(iVar8 + 0x40) = uVar11;
    func_0x00d9a058(iVar8,*(undefined4 *)(unaff_r23 + 0xe0));
    puVar6 = (undefined4 *)(unaff_r23 + 0xd0U & 0xfffffff0);
    uVar11 = puVar6[1];
    uVar12 = puVar6[2];
    uVar13 = puVar6[3];
    puVar7 = (undefined4 *)(iVar8 + 0x20U & 0xfffffff0);
    *puVar7 = *puVar6;
    puVar7[1] = uVar11;
    puVar7[2] = uVar12;
    puVar7[3] = uVar13;
    *(undefined4 *)(iVar8 + 0x48) = *(undefined4 *)(unaff_r23 + 0xf0);
    *(undefined4 *)(iVar8 + 0x4c) = *(undefined4 *)(unaff_r23 + 0xf4);
    *(undefined4 *)(iVar8 + 0x50) = *(undefined4 *)(unaff_r23 + 0xf8);
    *(undefined4 *)(iVar8 + 0x54) = *(undefined4 *)(unaff_r23 + 0xfc);
    iVar10 = *(int *)(iVar2 + 0x33c);
  }
  iVar9 = param_1 + 0x70;
  func_0x0015b6cc(unaff_r23 + 0x100,*(undefined4 *)(iVar10 + iVar9));
  func_0x0015d01c(unaff_r23 + 0x300,*(undefined4 *)(*(int *)(iVar2 + 0x33c) + iVar9 + 8));
  iVar10 = unaff_r25 * 0x5e0 + 0x100 + *piVar3;
  func_0x00bdfb3c((double)*(float *)(unaff_r23 + 0x334),(double)*(float *)(unaff_r23 + 0x338),iVar10
                  ,&stack0x00000080);
  *(undefined4 *)(iVar10 + 0x1b8) = *(undefined4 *)(unaff_r23 + 0x33c);
  uVar11 = *(undefined4 *)(unaff_r23 + 0x344);
  iVar8 = unaff_r25 * 0x10;
  *(undefined4 *)(iVar10 + 0x1bc) = *(undefined4 *)(unaff_r23 + 0x340);
  *(undefined4 *)(iVar10 + 0x1c0) = uVar11;
  puVar6 = (undefined4 *)(unaff_r23 + 0x350U & 0xfffffff0);
  uVar11 = puVar6[1];
  uVar12 = puVar6[2];
  uVar13 = puVar6[3];
  puVar7 = (undefined4 *)(iVar10 + 0x1d0U & 0xfffffff0);
  *puVar7 = *puVar6;
  puVar7[1] = uVar11;
  puVar7[2] = uVar12;
  puVar7[3] = uVar13;
  *(undefined4 *)(iVar10 + 0x1c4) = *(undefined4 *)(unaff_r23 + 0x348);
  puVar6 = (undefined4 *)(unaff_r23 + 0x10U & 0xfffffff0);
  uVar11 = puVar6[1];
  uVar12 = puVar6[2];
  uVar13 = puVar6[3];
  puVar7 = (undefined4 *)(*(int *)(iVar2 + 0x33c) + iVar8 + 0x90 & 0xfffffff0);
  *puVar7 = *puVar6;
  puVar7[1] = uVar11;
  puVar7[2] = uVar12;
  puVar7[3] = uVar13;
  puVar6 = (undefined4 *)(unaff_r23 + 0x20U & 0xfffffff0);
  uVar11 = puVar6[1];
  uVar12 = puVar6[2];
  uVar13 = puVar6[3];
  puVar7 = (undefined4 *)(*(int *)(iVar2 + 0x33c) + iVar8 + 0xb0 & 0xfffffff0);
  *puVar7 = *puVar6;
  puVar7[1] = uVar11;
  puVar7[2] = uVar12;
  puVar7[3] = uVar13;
  puVar6 = (undefined4 *)(unaff_r23 + 0x30U & 0xfffffff0);
  uVar11 = puVar6[1];
  uVar12 = puVar6[2];
  uVar13 = puVar6[3];
  puVar7 = (undefined4 *)(*(int *)(iVar2 + 0x33c) + iVar8 + 0xd0 & 0xfffffff0);
  *puVar7 = *puVar6;
  puVar7[1] = uVar11;
  puVar7[2] = uVar12;
  puVar7[3] = uVar13;
  iVar8 = *(int *)(iVar2 + 0x33c);
  iVar10 = *(int *)(iVar8 + 0xebc);
  if (iVar10 == 5) {
    iVar5 = *(int *)(**(int **)(unaff_r30 + -0x7fa4) +
                     *(int *)(**(int **)(unaff_r30 + -0x7fa4) + 0x24) * 0x7eb8 + 0x90);
    if (iVar5 == 2) goto LAB_00160078;
    if (iVar5 == 3) goto LAB_0015fee8;
    iVar10 = 0;
    bVar1 = false;
  }
  else {
    bVar1 = 1 < iVar10;
    iVar5 = iVar10;
  }
  if (iVar5 == 1) {
    param_1 = param_1 + 0x70;
    iVar8 = *(int *)(iVar8 + param_1 + 8);
    uVar4 = *(uint *)(iVar8 + 4);
    *(uint *)(iVar8 + 4) = uVar4 & 0xffc0ffff | uVar4 & 0x3f0000 | 0x20000;
    *(undefined1 *)(*(int *)(*(int *)(iVar2 + 0x33c) + param_1) + 0x214) = 1;
    *(undefined1 *)(*(int *)(*(int *)(iVar2 + 0x33c) + param_1) + 0x244) = 0;
    return;
  }
  if (!bVar1) {
    if (iVar10 != 0) {
      return;
    }
    iVar8 = *(int *)(iVar8 + iVar9 + 8);
    *(uint *)(iVar8 + 4) = *(uint *)(iVar8 + 4) & 0xfffdffff;
    *(undefined1 *)(*(int *)(*(int *)(iVar2 + 0x33c) + iVar9) + 0x214) = 0;
    *(undefined1 *)(*(int *)(*(int *)(iVar2 + 0x33c) + iVar9) + 0x244) = 0;
    return;
  }
  if (iVar10 != 2) {
    if (iVar10 != 3) {
      return;
    }
LAB_0015fee8:
    param_1 = param_1 + 0x70;
    iVar8 = *(int *)(iVar8 + param_1 + 8);
    uVar4 = *(uint *)(iVar8 + 4);
    *(uint *)(iVar8 + 4) = uVar4 & 0xffc0ffff | uVar4 & 0x3f0000 | 0x20000;
    *(undefined1 *)(*(int *)(*(int *)(iVar2 + 0x33c) + param_1) + 0x214) = 0;
    *(undefined1 *)(*(int *)(*(int *)(iVar2 + 0x33c) + param_1) + 0x244) = 0;
    return;
  }
LAB_00160078:
  param_1 = param_1 + 0x70;
  iVar8 = *(int *)(iVar8 + param_1 + 8);
  uVar4 = *(uint *)(iVar8 + 4);
  *(uint *)(iVar8 + 4) = uVar4 & 0xffc0ffff | uVar4 & 0x3f0000 | 0x20000;
  *(undefined1 *)(*(int *)(*(int *)(iVar2 + 0x33c) + param_1) + 0x214) = 0;
  *(undefined1 *)(*(int *)(*(int *)(iVar2 + 0x33c) + param_1) + 0x244) = 1;
  return;
}


