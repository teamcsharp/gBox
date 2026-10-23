
undefined4
FUN_00d1f650(int param_1,int param_2,int param_3,uint param_4,undefined4 param_5,undefined8 param_6)

{
  float fVar1;
  float *pfVar2;
  uint uVar3;
  undefined4 *puVar4;
  undefined4 *puVar5;
  uint uVar6;
  short sVar7;
  undefined2 uVar9;
  undefined4 uVar8;
  uint *puVar10;
  int iVar11;
  int iVar12;
  int iVar13;
  int iVar14;
  int iVar15;
  double dVar16;
  undefined4 uVar17;
  undefined4 uVar18;
  undefined1 auStack_a0 [16];
  undefined4 uStack_90;
  undefined4 uStack_8c;
  undefined4 uStack_88;
  undefined4 uStack_84;
  undefined4 uStack_80;
  undefined4 uStack_7c;
  undefined4 uStack_78;
  undefined4 uStack_74;
  
  iVar12 = iRam017154ac;
  iVar13 = *(int *)(param_2 + 0xac);
  iVar15 = (uint)*(ushort *)(param_2 + 0xbc) + param_3;
  *(undefined2 *)(iVar15 + 0x34) = 1;
  if ((*(ushort *)(iVar13 + 0x3a) == 0) ||
     (puVar10 = (uint *)((uint)*(ushort *)(iVar13 + 0x3a) + iVar13), puVar10 == (uint *)0x0)) {
    iVar14 = *(int *)(iVar12 + -0x7fbc);
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    *(float *)(iVar15 + 0x10) =
         *(float *)(iVar14 + (iVar11 * 4 & 0x3ffcU)) * *(float *)(iVar13 + 0x2c) +
         *(float *)(iVar13 + 0x28);
  }
  else {
    iVar14 = *(int *)(iVar12 + -0x7fbc);
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    *(undefined4 *)(iVar15 + 0x2c) = *(undefined4 *)(iVar14 + (iVar11 * 4 & 0x3ffcU));
    uVar3 = *puVar10 >> 5 & 7;
    if (uVar3 == 2) {
LAB_00d1fc84:
      uVar8 = *(undefined4 *)(param_1 + 0x104);
    }
    else if (uVar3 < 3) {
      if (uVar3 == 1) {
        uVar8 = *(undefined4 *)(param_2 + 0x24);
      }
      else {
LAB_00d1f734:
        uVar8 = *(undefined4 *)(param_3 + 0xc);
      }
    }
    else if (uVar3 == 3) {
      if (*(int *)(param_1 + 0x1a0) == 0) goto LAB_00d1fc84;
      uVar8 = *(undefined4 *)(*(int *)(param_1 + 0x1a0) + 0x104);
    }
    else {
      if (uVar3 != 4) goto LAB_00d1f734;
      uVar8 = *(undefined4 *)(**(int **)(iVar12 + -0x7fd4) + 100);
    }
    dVar16 = (double)func_0x00ba4c24(*(undefined1 *)puVar10,puVar10 + 1,*puVar10 >> 1 & 1,
                                     *puVar10 >> 2 & 7,uVar8,param_6,0);
    *(float *)(iVar15 + 0x10) = (float)dVar16;
    if ((*puVar10 & 1) == 0) {
      *(ushort *)(iVar15 + 0x34) = *(ushort *)(iVar15 + 0x34) | 0x40;
    }
  }
  iVar11 = **(int **)(param_1 + 0xec) + 1;
  **(int **)(param_1 + 0xec) = iVar11;
  *(float *)(iVar15 + 0x14) =
       *(float *)(iVar14 + (iVar11 * 4 & 0x3ffcU)) * *(float *)(iVar13 + 0x4c) +
       *(float *)(iVar13 + 0x48);
  iVar11 = **(int **)(param_1 + 0xec) + 1;
  **(int **)(param_1 + 0xec) = iVar11;
  fVar1 = *(float *)(iVar14 + (iVar11 * 4 & 0x3ffcU)) * *(float *)(iVar13 + 0x74) +
          *(float *)(iVar13 + 0x70);
  *(float *)(iVar15 + 0x38) = fVar1;
  *(float *)(iVar15 + 0x3c) = fVar1;
  puVar4 = (undefined4 *)(param_4 & 0xfffffff0);
  uVar8 = puVar4[1];
  uVar17 = puVar4[2];
  uVar18 = puVar4[3];
  puVar5 = (undefined4 *)(iVar15 + 0x40U & 0xfffffff0);
  *puVar5 = *puVar4;
  puVar5[1] = uVar8;
  puVar5[2] = uVar17;
  puVar5[3] = uVar18;
  if ((*(ushort *)(iVar13 + 0x38) == 0) ||
     (puVar10 = (uint *)((uint)*(ushort *)(iVar13 + 0x38) + iVar13), puVar10 == (uint *)0x0)) {
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    pfVar2 = *(float **)(iVar12 + -0x7fb8);
    *(float *)(iVar15 + 0x50) =
         *(float *)(iVar14 + (iVar11 * 4 & 0x3ffcU)) * *(float *)(iVar13 + 0x14) +
         *(float *)(iVar13 + 0x10);
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    *(float *)(iVar15 + 0x54) =
         *(float *)(iVar14 + (iVar11 * 4 & 0x3ffcU)) * *(float *)(iVar13 + 0x1c) +
         *(float *)(iVar13 + 0x18);
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    fVar1 = *pfVar2;
    *(float *)(iVar15 + 0x58) =
         *(float *)(iVar14 + (iVar11 * 4 & 0x3ffcU)) * *(float *)(iVar13 + 0x24) +
         *(float *)(iVar13 + 0x20);
    if ((*(float *)(iVar15 + 0x50) == fVar1) &&
       ((*(float *)(iVar15 + 0x54) == pfVar2[1] && (*(float *)(iVar15 + 0x58) == pfVar2[2])))) {
      iVar14 = *(int *)(iVar12 + -0x7fc0);
    }
    else {
LAB_00d1f984:
      iVar14 = *(int *)(iVar12 + -0x7fc0);
      *(ushort *)(iVar15 + 0x34) = *(ushort *)(iVar15 + 0x34) | 2;
    }
  }
  else if ((*puVar10 & 0x800000) == 0) {
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    *(undefined4 *)(iVar15 + 0x20) = *(undefined4 *)(iVar14 + (iVar11 * 4 & 0x3ffcU));
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    *(undefined4 *)(iVar15 + 0x24) = *(undefined4 *)(iVar14 + (iVar11 * 4 & 0x3ffcU));
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    *(undefined4 *)(iVar15 + 0x28) = *(undefined4 *)(iVar14 + (iVar11 * 4 & 0x3ffcU));
    uVar3 = *puVar10 >> 5 & 7;
    if (uVar3 == 2) {
LAB_00d1fb98:
      uVar8 = *(undefined4 *)(param_1 + 0x104);
    }
    else if (uVar3 < 3) {
      if (uVar3 == 1) {
        uVar8 = *(undefined4 *)(param_2 + 0x24);
      }
      else {
LAB_00d1fb78:
        uVar8 = *(undefined4 *)(param_3 + 0xc);
      }
    }
    else if (uVar3 == 3) {
      if (*(int *)(param_1 + 0x1a0) == 0) goto LAB_00d1fb98;
      uVar8 = *(undefined4 *)(*(int *)(param_1 + 0x1a0) + 0x104);
    }
    else {
      if (uVar3 != 4) goto LAB_00d1fb78;
      uVar8 = *(undefined4 *)(**(int **)(iVar12 + -0x7fd4) + 100);
    }
    func_0x00ba187c(&uStack_90,*(undefined1 *)puVar10,puVar10 + 1,*puVar10 >> 1 & 1,
                    *puVar10 >> 2 & 7,uVar8,auStack_a0,0);
    puVar4 = (undefined4 *)((uint)(iVar15 + 0x50) & 0xfffffff0);
    *puVar4 = uStack_90;
    puVar4[1] = uStack_8c;
    puVar4[2] = uStack_88;
    puVar4[3] = uStack_84;
    if ((*puVar10 & 1) == 0) {
      iVar14 = *(int *)(iVar12 + -0x7fc0);
      *(ushort *)(iVar15 + 0x34) = *(ushort *)(iVar15 + 0x34) | 0x12;
    }
    else {
      pfVar2 = *(float **)(iVar12 + -0x7fb8);
      if (((*(float *)(iVar15 + 0x50) != *pfVar2) || (*(float *)(iVar15 + 0x54) != pfVar2[1])) ||
         (*(float *)(iVar15 + 0x58) != pfVar2[2])) goto LAB_00d1f984;
      iVar14 = *(int *)(iVar12 + -0x7fc0);
    }
  }
  else {
    iVar14 = *(int *)(iVar12 + -0x7fc0);
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    *(undefined4 *)(iVar15 + 0x20) = *(undefined4 *)(iVar14 + (iVar11 * 4 & 0x3ffcU));
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    *(undefined4 *)(iVar15 + 0x24) = *(undefined4 *)(iVar14 + (iVar11 * 4 & 0x3ffcU));
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    *(undefined4 *)(iVar15 + 0x28) = *(undefined4 *)(iVar14 + (iVar11 * 4 & 0x3ffcU));
    uVar3 = *puVar10 >> 5 & 7;
    if (uVar3 == 2) {
LAB_00d1fc18:
      uVar8 = *(undefined4 *)(param_1 + 0x104);
    }
    else if (uVar3 < 3) {
      if (uVar3 == 1) {
        uVar8 = *(undefined4 *)(param_2 + 0x24);
      }
      else {
LAB_00d1f8d0:
        uVar8 = *(undefined4 *)(param_3 + 0xc);
      }
    }
    else if (uVar3 == 3) {
      if (*(int *)(param_1 + 0x1a0) == 0) goto LAB_00d1fc18;
      uVar8 = *(undefined4 *)(*(int *)(param_1 + 0x1a0) + 0x104);
    }
    else {
      if (uVar3 != 4) goto LAB_00d1f8d0;
      uVar8 = *(undefined4 *)(**(int **)(iVar12 + -0x7fd4) + 100);
    }
    func_0x00ba6018(&uStack_80,*(undefined1 *)puVar10,puVar10 + 1,*puVar10 >> 1 & 1,
                    *puVar10 >> 2 & 7,uVar8,iVar15 + 0x20,0);
    puVar4 = (undefined4 *)((uint)(iVar15 + 0x50) & 0xfffffff0);
    *puVar4 = uStack_80;
    puVar4[1] = uStack_7c;
    puVar4[2] = uStack_78;
    puVar4[3] = uStack_74;
    if ((*puVar10 & 1) == 0) {
      *(ushort *)(iVar15 + 0x34) = *(ushort *)(iVar15 + 0x34) | 0x32;
    }
    else {
      pfVar2 = *(float **)(iVar12 + -0x7fb8);
      if (((*(float *)(iVar15 + 0x50) != *pfVar2) || (*(float *)(iVar15 + 0x54) != pfVar2[1])) ||
         (*(float *)(iVar15 + 0x58) != pfVar2[2])) {
        *(ushort *)(iVar15 + 0x34) = *(ushort *)(iVar15 + 0x34) | 2;
      }
    }
  }
  if ((*(ushort *)(iVar13 + 0x42) == 0) ||
     (puVar10 = (uint *)((uint)*(ushort *)(iVar13 + 0x42) + iVar13), puVar10 == (uint *)0x0)) {
    iVar12 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar12;
    uVar3 = *(uint *)(iVar14 + (iVar12 * 4 & 0x3ffcU));
    if (*(ushort *)(iVar13 + 0x46) == 0) {
      sVar7 = *(short *)(iVar13 + 0x44);
    }
    else {
      uVar6 = *(ushort *)(iVar13 + 0x46) + 1;
      sVar7 = *(short *)(iVar13 + 0x44) + ((short)uVar3 - (short)(uVar3 / uVar6) * (short)uVar6);
    }
    *(short *)(iVar15 + 0x36) = sVar7;
    goto LAB_00d1fa50;
  }
  uVar3 = *puVar10 >> 5 & 7;
  if (uVar3 == 3) {
    if (*(int *)(param_1 + 0x1a0) == 0) {
LAB_00d1fb90:
      uVar8 = *(undefined4 *)(param_1 + 0x104);
    }
    else {
      uVar8 = *(undefined4 *)(*(int *)(param_1 + 0x1a0) + 0x104);
    }
  }
  else if (uVar3 == 4) {
    uVar8 = *(undefined4 *)(**(int **)(iVar12 + -0x7fd4) + 100);
  }
  else {
    if (uVar3 == 2) goto LAB_00d1fb90;
    uVar8 = *(undefined4 *)(param_2 + 0x24);
  }
  iVar13 = **(int **)(param_1 + 0xec) + 1;
  **(int **)(param_1 + 0xec) = iVar13;
  uVar9 = func_0x00ba5318(*(undefined1 *)puVar10,puVar10 + 1,*puVar10 >> 1 & 1,*puVar10 >> 2 & 7,
                          uVar8,*(undefined4 *)(iVar14 + (iVar13 * 4 & 0x3ffcU)),0);
  *(undefined2 *)(iVar15 + 0x36) = uVar9;
LAB_00d1fa50:
  uVar8 = func_0x00d1e374(param_1,param_2,iVar15,param_5,*(undefined1 *)(param_3 + 0xb),
                          *(ulonglong *)(param_2 + 0x18) >> 0x33 & 1);
  return uVar8;
}


