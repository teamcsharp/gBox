
uint FUN_00d19608(int param_1,int param_2,int param_3,undefined8 *param_4,uint param_5,
                 undefined8 param_6,uint param_7)

{
  float fVar1;
  float *pfVar2;
  undefined4 *puVar3;
  uint uVar4;
  short sVar5;
  undefined2 uVar7;
  uint uVar6;
  uint *puVar8;
  undefined4 uVar9;
  int iVar10;
  int iVar11;
  int iVar12;
  int iVar13;
  int iVar14;
  double dVar15;
  undefined1 auStack_f0 [16];
  undefined4 uStack_e0;
  undefined4 uStack_dc;
  undefined4 uStack_d8;
  undefined4 uStack_d4;
  undefined4 uStack_d0;
  undefined4 uStack_cc;
  undefined4 uStack_c8;
  undefined4 uStack_c4;
  undefined1 auStack_c0 [16];
  undefined4 uStack_b0;
  undefined4 uStack_ac;
  undefined4 uStack_a8;
  undefined4 uStack_a4;
  undefined1 auStack_a0 [16];
  
  iVar11 = iRam017154ac;
  iVar12 = *(int *)(param_2 + 0xac);
  iVar14 = (uint)*(ushort *)(param_2 + 0xbc) + param_3;
  *(undefined2 *)(iVar14 + 0x34) = 1;
  if ((*(ushort *)(iVar12 + 0x3a) == 0) ||
     (puVar8 = (uint *)((uint)*(ushort *)(iVar12 + 0x3a) + iVar12), puVar8 == (uint *)0x0)) {
    iVar13 = *(int *)(iVar11 + -0x7fbc);
    iVar10 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar10;
    *(float *)(iVar14 + 0x10) =
         *(float *)(iVar13 + (iVar10 * 4 & 0x3ffcU)) * *(float *)(iVar12 + 0x2c) +
         *(float *)(iVar12 + 0x28);
  }
  else {
    iVar13 = *(int *)(iVar11 + -0x7fbc);
    iVar10 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar10;
    *(undefined4 *)(iVar14 + 0x2c) = *(undefined4 *)(iVar13 + (iVar10 * 4 & 0x3ffcU));
    uVar6 = *puVar8 >> 5 & 7;
    if (uVar6 == 2) {
LAB_00d19d44:
      uVar9 = *(undefined4 *)(param_1 + 0x104);
    }
    else if (uVar6 < 3) {
      if (uVar6 == 1) {
        uVar9 = *(undefined4 *)(param_2 + 0x24);
      }
      else {
LAB_00d19708:
        uVar9 = *(undefined4 *)(param_3 + 0xc);
      }
    }
    else if (uVar6 == 3) {
      if (*(int *)(param_1 + 0x1a0) == 0) goto LAB_00d19d44;
      uVar9 = *(undefined4 *)(*(int *)(param_1 + 0x1a0) + 0x104);
    }
    else {
      if (uVar6 != 4) goto LAB_00d19708;
      uVar9 = *(undefined4 *)(**(int **)(iVar11 + -0x7fd4) + 100);
    }
    dVar15 = (double)func_0x00ba4c24(*(undefined1 *)puVar8,puVar8 + 1,*puVar8 >> 1 & 1,
                                     *puVar8 >> 2 & 7,uVar9,param_6,0);
    *(float *)(iVar14 + 0x10) = (float)dVar15;
    if ((*puVar8 & 1) == 0) {
      *(ushort *)(iVar14 + 0x34) = *(ushort *)(iVar14 + 0x34) | 0x40;
    }
  }
  iVar10 = **(int **)(param_1 + 0xec) + 1;
  **(int **)(param_1 + 0xec) = iVar10;
  *(float *)(iVar14 + 0x14) =
       *(float *)(iVar13 + (iVar10 * 4 & 0x3ffcU)) * *(float *)(iVar12 + 0x4c) +
       *(float *)(iVar12 + 0x48);
  iVar10 = **(int **)(param_1 + 0xec) + 1;
  **(int **)(param_1 + 0xec) = iVar10;
  fVar1 = *(float *)(iVar13 + (iVar10 * 4 & 0x3ffcU)) * *(float *)(iVar12 + 0x74) +
          *(float *)(iVar12 + 0x70);
  *(float *)(iVar14 + 0x38) = fVar1;
  *(float *)(iVar14 + 0x3c) = fVar1;
  *(undefined8 *)(iVar14 + 0x40) = *param_4;
  *(undefined8 *)(iVar14 + 0x48) = param_4[1];
  *(undefined8 *)(iVar14 + 0x50) = param_4[2];
  *(undefined8 *)(iVar14 + 0x58) = param_4[3];
  if ((*(ushort *)(iVar12 + 0x38) == 0) ||
     (puVar8 = (uint *)((uint)*(ushort *)(iVar12 + 0x38) + iVar12), puVar8 == (uint *)0x0)) {
    iVar10 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar10;
    pfVar2 = *(float **)(iVar11 + -0x7fb8);
    *(float *)(iVar14 + 0x60) =
         *(float *)(iVar13 + (iVar10 * 4 & 0x3ffcU)) * *(float *)(iVar12 + 0x14) +
         *(float *)(iVar12 + 0x10);
    iVar10 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar10;
    *(float *)(iVar14 + 100) =
         *(float *)(iVar13 + (iVar10 * 4 & 0x3ffcU)) * *(float *)(iVar12 + 0x1c) +
         *(float *)(iVar12 + 0x18);
    iVar10 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar10;
    fVar1 = *pfVar2;
    *(float *)(iVar14 + 0x68) =
         *(float *)(iVar13 + (iVar10 * 4 & 0x3ffcU)) * *(float *)(iVar12 + 0x24) +
         *(float *)(iVar12 + 0x20);
    if ((*(float *)(iVar14 + 0x60) == fVar1) &&
       ((*(float *)(iVar14 + 100) == pfVar2[1] && (*(float *)(iVar14 + 0x68) == pfVar2[2])))) {
      iVar13 = *(int *)(iVar11 + -0x7fc0);
    }
    else {
LAB_00d19974:
      iVar13 = *(int *)(iVar11 + -0x7fc0);
      *(ushort *)(iVar14 + 0x34) = *(ushort *)(iVar14 + 0x34) | 2;
    }
  }
  else if ((*puVar8 & 0x800000) == 0) {
    iVar10 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar10;
    *(undefined4 *)(iVar14 + 0x20) = *(undefined4 *)(iVar13 + (iVar10 * 4 & 0x3ffcU));
    iVar10 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar10;
    *(undefined4 *)(iVar14 + 0x24) = *(undefined4 *)(iVar13 + (iVar10 * 4 & 0x3ffcU));
    iVar10 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar10;
    *(undefined4 *)(iVar14 + 0x28) = *(undefined4 *)(iVar13 + (iVar10 * 4 & 0x3ffcU));
    uVar6 = *puVar8 >> 5 & 7;
    if (uVar6 == 2) {
LAB_00d19c58:
      uVar9 = *(undefined4 *)(param_1 + 0x104);
    }
    else if (uVar6 < 3) {
      if (uVar6 == 1) {
        uVar9 = *(undefined4 *)(param_2 + 0x24);
      }
      else {
LAB_00d19c38:
        uVar9 = *(undefined4 *)(param_3 + 0xc);
      }
    }
    else if (uVar6 == 3) {
      if (*(int *)(param_1 + 0x1a0) == 0) goto LAB_00d19c58;
      uVar9 = *(undefined4 *)(*(int *)(param_1 + 0x1a0) + 0x104);
    }
    else {
      if (uVar6 != 4) goto LAB_00d19c38;
      uVar9 = *(undefined4 *)(**(int **)(iVar11 + -0x7fd4) + 100);
    }
    func_0x00ba187c(&uStack_d0,*(undefined1 *)puVar8,puVar8 + 1,*puVar8 >> 1 & 1,*puVar8 >> 2 & 7,
                    uVar9,auStack_f0,0);
    puVar3 = (undefined4 *)((uint)(iVar14 + 0x60) & 0xfffffff0);
    *puVar3 = uStack_d0;
    puVar3[1] = uStack_cc;
    puVar3[2] = uStack_c8;
    puVar3[3] = uStack_c4;
    if ((*puVar8 & 1) == 0) {
      iVar13 = *(int *)(iVar11 + -0x7fc0);
      *(ushort *)(iVar14 + 0x34) = *(ushort *)(iVar14 + 0x34) | 0x12;
    }
    else {
      pfVar2 = *(float **)(iVar11 + -0x7fb8);
      if (((*(float *)(iVar14 + 0x60) != *pfVar2) || (*(float *)(iVar14 + 100) != pfVar2[1])) ||
         (*(float *)(iVar14 + 0x68) != pfVar2[2])) goto LAB_00d19974;
      iVar13 = *(int *)(iVar11 + -0x7fc0);
    }
  }
  else {
    iVar13 = *(int *)(iVar11 + -0x7fc0);
    iVar10 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar10;
    *(undefined4 *)(iVar14 + 0x20) = *(undefined4 *)(iVar13 + (iVar10 * 4 & 0x3ffcU));
    iVar10 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar10;
    *(undefined4 *)(iVar14 + 0x24) = *(undefined4 *)(iVar13 + (iVar10 * 4 & 0x3ffcU));
    iVar10 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar10;
    *(undefined4 *)(iVar14 + 0x28) = *(undefined4 *)(iVar13 + (iVar10 * 4 & 0x3ffcU));
    uVar6 = *puVar8 >> 5 & 7;
    if (uVar6 == 2) {
LAB_00d19cd8:
      uVar9 = *(undefined4 *)(param_1 + 0x104);
    }
    else if (uVar6 < 3) {
      if (uVar6 == 1) {
        uVar9 = *(undefined4 *)(param_2 + 0x24);
      }
      else {
LAB_00d198c0:
        uVar9 = *(undefined4 *)(param_3 + 0xc);
      }
    }
    else if (uVar6 == 3) {
      if (*(int *)(param_1 + 0x1a0) == 0) goto LAB_00d19cd8;
      uVar9 = *(undefined4 *)(*(int *)(param_1 + 0x1a0) + 0x104);
    }
    else {
      if (uVar6 != 4) goto LAB_00d198c0;
      uVar9 = *(undefined4 *)(**(int **)(iVar11 + -0x7fd4) + 100);
    }
    func_0x00ba6018(&uStack_e0,*(undefined1 *)puVar8,puVar8 + 1,*puVar8 >> 1 & 1,*puVar8 >> 2 & 7,
                    uVar9,iVar14 + 0x20,0);
    puVar3 = (undefined4 *)((uint)(iVar14 + 0x60) & 0xfffffff0);
    *puVar3 = uStack_e0;
    puVar3[1] = uStack_dc;
    puVar3[2] = uStack_d8;
    puVar3[3] = uStack_d4;
    if ((*puVar8 & 1) == 0) {
      *(ushort *)(iVar14 + 0x34) = *(ushort *)(iVar14 + 0x34) | 0x32;
    }
    else {
      pfVar2 = *(float **)(iVar11 + -0x7fb8);
      if (((*(float *)(iVar14 + 0x60) != *pfVar2) || (*(float *)(iVar14 + 100) != pfVar2[1])) ||
         (*(float *)(iVar14 + 0x68) != pfVar2[2])) {
        *(ushort *)(iVar14 + 0x34) = *(ushort *)(iVar14 + 0x34) | 2;
      }
    }
  }
  if ((*(ushort *)(iVar12 + 0x42) == 0) ||
     (puVar8 = (uint *)((uint)*(ushort *)(iVar12 + 0x42) + iVar12), puVar8 == (uint *)0x0)) {
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    uVar6 = *(uint *)(iVar13 + (iVar11 * 4 & 0x3ffcU));
    if (*(ushort *)(iVar12 + 0x46) == 0) {
      sVar5 = *(short *)(iVar12 + 0x44);
    }
    else {
      uVar4 = *(ushort *)(iVar12 + 0x46) + 1;
      sVar5 = *(short *)(iVar12 + 0x44) + ((short)uVar6 - (short)(uVar6 / uVar4) * (short)uVar4);
    }
    *(short *)(iVar14 + 0x36) = sVar5;
    goto joined_r0x00d19a6c;
  }
  uVar6 = *puVar8 >> 5 & 7;
  if (uVar6 == 3) {
    if (*(int *)(param_1 + 0x1a0) == 0) {
LAB_00d19c50:
      uVar9 = *(undefined4 *)(param_1 + 0x104);
    }
    else {
      uVar9 = *(undefined4 *)(*(int *)(param_1 + 0x1a0) + 0x104);
    }
  }
  else if (uVar6 == 4) {
    uVar9 = *(undefined4 *)(**(int **)(iVar11 + -0x7fd4) + 100);
  }
  else {
    if (uVar6 == 2) goto LAB_00d19c50;
    uVar9 = *(undefined4 *)(param_2 + 0x24);
  }
  iVar12 = **(int **)(param_1 + 0xec) + 1;
  **(int **)(param_1 + 0xec) = iVar12;
  uVar7 = func_0x00ba5318(*(undefined1 *)puVar8,puVar8 + 1,*puVar8 >> 1 & 1,*puVar8 >> 2 & 7,uVar9,
                          *(undefined4 *)(iVar13 + (iVar12 * 4 & 0x3ffcU)),0);
  *(undefined2 *)(iVar14 + 0x36) = uVar7;
joined_r0x00d19a6c:
  if ((param_7 & 0x10000) == 0) {
    uVar6 = func_0x00d18b0c(param_1,param_2,iVar14,param_5,*(undefined1 *)(param_3 + 0xb));
  }
  else {
    iVar12 = iVar14 + (uint)*(byte *)(param_3 + 0xb) * 4 + 0x30;
    dVar15 = (double)*(float *)(iVar12 + 8);
    *(float *)(iVar12 + 8) = (float)(dVar15 + (double)*(float *)(iVar14 + 0x10));
    func_0x00d18b0c(param_1,param_2,iVar14,auStack_a0,*(undefined1 *)(param_3 + 0xb));
    *(float *)(iVar14 + (uint)*(byte *)(param_3 + 0xb) * 4 + 0x38) = (float)dVar15;
    uVar6 = func_0x00d18b0c(param_1,param_2,iVar14,param_5,*(undefined1 *)(param_3 + 0xb));
    vectorSubtractFloatingPoint(auStack_a0,*(undefined1 (*) [16])(param_5 & 0xfffffff0));
    func_0x0114f578(&uStack_b0,auStack_c0);
    uVar6 = uVar6 | 0x180;
    puVar3 = (undefined4 *)((uint)param_6 & 0xfffffff0);
    *puVar3 = uStack_b0;
    puVar3[1] = uStack_ac;
    puVar3[2] = uStack_a8;
    puVar3[3] = uStack_a4;
  }
  return uVar6;
}


