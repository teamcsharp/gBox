
void FUN_009c55d4(int param_1,int *param_2,int param_3)

{
  bool bVar1;
  int iVar2;
  uint uVar3;
  int *piVar4;
  int iVar5;
  undefined4 *puVar6;
  undefined4 *puVar7;
  int iVar8;
  int iVar9;
  int iVar10;
  int iVar11;
  uint uVar12;
  int *piVar13;
  int iVar14;
  int *piVar15;
  ulonglong uVar16;
  double dVar17;
  undefined4 uVar18;
  undefined4 uVar19;
  undefined4 uVar20;
  undefined4 uVar21;
  
  iVar10 = iRam01714ecc;
  if (*(int *)(param_1 + 0xe4) == 0) {
    return;
  }
  if (*(int *)(param_1 + 0xc4) != 1) {
    return;
  }
  iVar2 = *(int *)(param_1 + 0xc0);
  uVar3 = *(uint *)(*(int *)(param_1 + 0xe4) + 0xc);
  if (iVar2 == 0) {
    return;
  }
  if (uVar3 == 0) {
    return;
  }
  if (*(char *)(uVar3 + 0x48) == '\0') {
    *(undefined4 *)(uVar3 + 0x2c) = 0;
    *(undefined4 *)(uVar3 + 0x28) = 0;
  }
  iVar14 = 0;
  if (*(int **)(uVar3 + 0xbc) == (int *)0x0) {
LAB_009c5c80:
    *(int **)(uVar3 + iVar14 * 4 + 0xbc) = param_2;
  }
  else {
    if (param_2 == *(int **)(uVar3 + 0xbc)) {
      return;
    }
    iVar14 = 1;
    if (*(int **)(uVar3 + 0xc0) == (int *)0x0) goto LAB_009c5c80;
    if (param_2 == *(int **)(uVar3 + 0xc0)) {
      return;
    }
    if (*(int **)(uVar3 + 0xc4) == (int *)0x0) {
      iVar14 = 2;
      goto LAB_009c5c80;
    }
    if (param_2 == *(int **)(uVar3 + 0xc4)) {
      return;
    }
  }
  *(int *)(uVar3 + 0x28) = *(int *)(uVar3 + 0x28) + param_3;
  if ((*(char *)(uVar3 + 0x48) != '\0') && (*(int *)(iVar2 + 100) <= *(int *)(uVar3 + 0xa0))) {
    if (*(int *)(iVar2 + 100) != *(int *)(uVar3 + 0xa0)) {
      return;
    }
    if (param_3 <= *(int *)(uVar3 + 0x2c)) {
      return;
    }
  }
  *(undefined1 *)(uVar3 + 0x48) = 1;
  puVar6 = (undefined4 *)(iVar2 + 0x10U & 0xfffffff0);
  uVar18 = puVar6[1];
  uVar19 = puVar6[2];
  uVar20 = puVar6[3];
  puVar7 = (undefined4 *)(uVar3 & 0xfffffff0);
  *puVar7 = *puVar6;
  puVar7[1] = uVar18;
  puVar7[2] = uVar19;
  puVar7[3] = uVar20;
  puVar6 = (undefined4 *)(iVar2 + 0x20U & 0xfffffff0);
  uVar18 = *puVar6;
  uVar19 = puVar6[1];
  uVar20 = puVar6[2];
  uVar21 = puVar6[3];
  *(int *)(uVar3 + 0x2c) = param_3;
  puVar6 = (undefined4 *)(uVar3 + 0x10 & 0xfffffff0);
  *puVar6 = uVar18;
  puVar6[1] = uVar19;
  puVar6[2] = uVar20;
  puVar6[3] = uVar21;
  *(undefined4 *)(uVar3 + 0x30) = 0;
  *(undefined4 *)(uVar3 + 0x34) = *(undefined4 *)(iVar2 + 0x38);
  *(undefined4 *)(uVar3 + 0x38) = *(undefined4 *)(iVar2 + 0x3c);
  *(undefined4 *)(uVar3 + 0x3c) = *(undefined4 *)(iVar2 + 0x40);
  *(undefined4 *)(uVar3 + 0x40) = *(undefined4 *)(iVar2 + 0x44);
  *(undefined4 *)(uVar3 + 0x44) = *(undefined4 *)(iVar2 + 0x48);
  uVar12 = *(uint *)(*(int *)(param_1 + 0xe4) + 0x18);
  if (uVar12 == 0) {
LAB_009c57b4:
    iVar14 = -1;
  }
  else {
    piVar15 = *(int **)(*(int *)(param_1 + 0xe4) + 4);
    iVar14 = 0;
    if (*piVar15 != param_1) {
      uVar16 = (ulonglong)uVar12;
      iVar14 = 0;
      do {
        iVar14 = iVar14 + 1;
        uVar16 = uVar16 - 1;
        if (uVar16 == 0) goto LAB_009c57b4;
      } while (piVar15[iVar14] != param_1);
    }
  }
  *(char *)(uVar3 + 0x49) = (char)iVar14;
  *(int **)(uVar3 + 0x20) = param_2;
  if (param_2 == (int *)0x0) {
    uVar12 = 0xffffffff;
    *(undefined1 *)(uVar3 + 0x94) = *(undefined1 *)(iVar2 + 0x70);
    piVar15 = (int *)0x0;
    *(undefined4 *)(uVar3 + 0x98) = *(undefined4 *)(iVar2 + 0x60);
  }
  else {
    iVar8 = (*(code *)**(undefined4 **)(*param_2 + 0x14))(param_2);
    iVar14 = *(int *)(iVar10 + -0x7f10);
    iVar9 = *(int *)(iVar14 + 4);
    if (*(int *)(iVar8 + 4) == iVar9) {
LAB_009c5bbc:
      *(int *)(uVar3 + 0x24) = param_2[0x444];
    }
    else {
      iVar8 = *(int *)(iVar8 + 0x10);
      if (iVar8 != 0) {
        iVar11 = *(int *)(iVar8 + 4);
        while (iVar11 != iVar9) {
          iVar8 = *(int *)(iVar8 + 0x10);
          if (iVar8 == 0) goto LAB_009c5844;
          iVar11 = *(int *)(iVar8 + 4);
        }
        goto LAB_009c5bbc;
      }
    }
LAB_009c5844:
    *(undefined1 *)(uVar3 + 0x94) = *(undefined1 *)(iVar2 + 0x70);
    *(undefined4 *)(uVar3 + 0x98) = *(undefined4 *)(iVar2 + 0x60);
    iVar9 = (*(code *)**(undefined4 **)(*param_2 + 0x14))(param_2);
    iVar14 = *(int *)(iVar14 + 4);
    piVar15 = param_2;
    if (*(int *)(iVar9 + 4) == iVar14) {
LAB_009c5bd0:
      piVar13 = (int *)func_0x008ccbdc(param_2);
      if (piVar13 != (int *)0x0) {
        iVar9 = (*(code *)**(undefined4 **)(*piVar13 + 0x14))(piVar13);
        iVar14 = *(int *)(*(int *)(iVar10 + -0x7f0c) + 4);
        if (*(int *)(iVar9 + 4) != iVar14) {
          iVar9 = *(int *)(iVar9 + 0x10);
          if (iVar9 == 0) goto LAB_009c58cc;
          iVar8 = *(int *)(iVar9 + 4);
          while (iVar8 != iVar14) {
            iVar9 = *(int *)(iVar9 + 0x10);
            if (iVar9 == 0) {
              uVar12 = 0xffffffff;
              goto LAB_009c5920;
            }
            iVar8 = *(int *)(iVar9 + 4);
          }
        }
        uVar12 = (uint)*(byte *)(piVar13 + 0xbc5);
        goto LAB_009c5920;
      }
    }
    else {
      iVar9 = *(int *)(iVar9 + 0x10);
      if (iVar9 != 0) {
        iVar8 = *(int *)(iVar9 + 4);
        while (iVar8 != iVar14) {
          iVar9 = *(int *)(iVar9 + 0x10);
          if (iVar9 == 0) goto LAB_009c58cc;
          iVar8 = *(int *)(iVar9 + 4);
        }
        goto LAB_009c5bd0;
      }
    }
LAB_009c58cc:
    uVar12 = 0xffffffff;
  }
LAB_009c5920:
  piVar13 = *(int **)(*(int *)(param_1 + 0xe4) + 0x10);
  if (piVar13 == (int *)0x0) {
    iVar14 = *(int *)(iVar10 + -0x7f08);
  }
  else {
    iVar9 = (*(code *)**(undefined4 **)(*piVar13 + 0x14))(piVar13);
    iVar14 = *(int *)(iVar10 + -0x7f08);
    if (*(int *)(iVar9 + 4) != *(int *)(iVar14 + 4)) {
      iVar9 = *(int *)(iVar9 + 0x10);
      if (iVar9 == 0) goto LAB_009c59b0;
      iVar8 = *(int *)(iVar9 + 4);
      while (iVar8 != *(int *)(iVar14 + 4)) {
        iVar9 = *(int *)(iVar9 + 0x10);
        if (iVar9 == 0) goto LAB_009c59b0;
        iVar8 = *(int *)(iVar9 + 4);
      }
    }
    piVar13[0x52b] = uVar12;
  }
LAB_009c59b0:
  iVar9 = 0;
  if (*(int *)(param_1 + 0xc4) == 1) {
    iVar9 = *(int *)(param_1 + 0xc0);
  }
  dVar17 = (double)*(float *)(iVar9 + 0x60);
  iVar8 = (*(code *)**(undefined4 **)(*param_2 + 0x14))(piVar15);
  iVar10 = *(int *)(iVar10 + -0x7f04);
  iVar9 = *(int *)(iVar10 + 4);
  if (*(int *)(iVar8 + 4) != iVar9) {
    iVar8 = *(int *)(iVar8 + 0x10);
    if (iVar8 == 0) goto LAB_009c5a40;
    iVar11 = *(int *)(iVar8 + 4);
    while (iVar11 != iVar9) {
      iVar8 = *(int *)(iVar8 + 0x10);
      if (iVar8 == 0) goto LAB_009c5a40;
      iVar11 = *(int *)(iVar8 + 4);
    }
  }
  iVar9 = 0;
  piVar13 = param_2;
  do {
    piVar4 = (int *)piVar13[0x447];
    if (piVar4 == (int *)0x0) break;
    iVar11 = (*(code *)**(undefined4 **)(*piVar4 + 0x14))(piVar4);
    iVar8 = *(int *)(iVar10 + 4);
    if (*(int *)(iVar11 + 4) != iVar8) {
      iVar11 = *(int *)(iVar11 + 0x10);
      if (iVar11 == 0) break;
      iVar5 = *(int *)(iVar11 + 4);
      while (iVar5 != iVar8) {
        iVar11 = *(int *)(iVar11 + 0x10);
        if (iVar11 == 0) goto LAB_009c5b6c;
        iVar5 = *(int *)(iVar11 + 4);
      }
    }
    bVar1 = iVar9 != 0xff;
    iVar9 = iVar9 + 1;
    piVar13 = piVar4;
  } while (bVar1);
LAB_009c5b6c:
  uVar12 = func_0x008869c4(dVar17,piVar13);
  if (1 < uVar12) {
    *(uint *)(uVar3 + 0x3c) = *(uint *)(uVar3 + 0x3c) & 0xffffff3f;
  }
LAB_009c5a40:
  *(undefined4 *)(uVar3 + 0x9c) = *(undefined4 *)(iVar2 + 0x4c);
  *(undefined4 *)(uVar3 + 0xa0) = *(undefined4 *)(iVar2 + 100);
  iVar10 = (*(code *)**(undefined4 **)(*param_2 + 0x14))(piVar15);
  if (*(int *)(iVar10 + 4) != *(int *)(iVar14 + 4)) {
    iVar10 = *(int *)(iVar10 + 0x10);
    if (iVar10 == 0) {
LAB_009c5ac4:
      *(undefined4 *)(uVar3 + 0xa4) = 0;
      return;
    }
    iVar2 = *(int *)(iVar10 + 4);
    while (iVar2 != *(int *)(iVar14 + 4)) {
      iVar10 = *(int *)(iVar10 + 0x10);
      if (iVar10 == 0) goto LAB_009c5ac4;
      iVar2 = *(int *)(iVar10 + 4);
    }
  }
  *(int *)(uVar3 + 0xa4) = param_2[0x698];
  return;
}


