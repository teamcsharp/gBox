
uint FUN_00d1c040(int param_1,int param_2,int param_3,undefined8 *param_4,uint param_5,
                 undefined8 param_6,uint param_7)

{
  float fVar1;
  float fVar2;
  float *pfVar3;
  undefined4 *puVar4;
  uint uVar5;
  short sVar6;
  undefined2 uVar8;
  uint uVar7;
  uint *puVar9;
  undefined4 uVar10;
  int iVar11;
  int iVar12;
  int iVar13;
  int iVar14;
  int iVar15;
  double dVar16;
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
  
  iVar12 = iRam017154ac;
  iVar13 = *(int *)(param_2 + 0xac);
  iVar15 = (uint)*(ushort *)(param_2 + 0xbc) + param_3;
  *(undefined2 *)(iVar15 + 0x34) = 1;
  if ((*(ushort *)(iVar13 + 0x3a) == 0) ||
     (puVar9 = (uint *)((uint)*(ushort *)(iVar13 + 0x3a) + iVar13), puVar9 == (uint *)0x0)) {
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
    uVar7 = *puVar9 >> 5 & 7;
    if (uVar7 == 2) {
LAB_00d1c7a4:
      uVar10 = *(undefined4 *)(param_1 + 0x104);
    }
    else if (uVar7 < 3) {
      if (uVar7 == 1) {
        uVar10 = *(undefined4 *)(param_2 + 0x24);
      }
      else {
LAB_00d1c140:
        uVar10 = *(undefined4 *)(param_3 + 0xc);
      }
    }
    else if (uVar7 == 3) {
      if (*(int *)(param_1 + 0x1a0) == 0) goto LAB_00d1c7a4;
      uVar10 = *(undefined4 *)(*(int *)(param_1 + 0x1a0) + 0x104);
    }
    else {
      if (uVar7 != 4) goto LAB_00d1c140;
      uVar10 = *(undefined4 *)(**(int **)(iVar12 + -0x7fd4) + 100);
    }
    dVar16 = (double)func_0x00ba4c24(*(undefined1 *)puVar9,puVar9 + 1,*puVar9 >> 1 & 1,
                                     *puVar9 >> 2 & 7,uVar10,param_6,0);
    *(float *)(iVar15 + 0x10) = (float)dVar16;
    if ((*puVar9 & 1) == 0) {
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
  fVar1 = *(float *)(iVar13 + 0x70);
  fVar2 = *(float *)(iVar13 + 0x74);
  *(undefined4 *)(iVar15 + 0x70) = 0;
  fVar1 = *(float *)(iVar14 + (iVar11 * 4 & 0x3ffcU)) * fVar2 + fVar1;
  *(undefined4 *)(iVar15 + 0x74) = 0;
  *(float *)(iVar15 + 0x38) = fVar1;
  *(float *)(iVar15 + 0x3c) = fVar1;
  *(undefined8 *)(iVar15 + 0x40) = *param_4;
  *(undefined8 *)(iVar15 + 0x48) = param_4[1];
  *(undefined8 *)(iVar15 + 0x50) = param_4[2];
  *(undefined8 *)(iVar15 + 0x58) = param_4[3];
  if ((*(ushort *)(iVar13 + 0x38) == 0) ||
     (puVar9 = (uint *)((uint)*(ushort *)(iVar13 + 0x38) + iVar13), puVar9 == (uint *)0x0)) {
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    pfVar3 = *(float **)(iVar12 + -0x7fb8);
    *(float *)(iVar15 + 0x60) =
         *(float *)(iVar14 + (iVar11 * 4 & 0x3ffcU)) * *(float *)(iVar13 + 0x14) +
         *(float *)(iVar13 + 0x10);
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    *(float *)(iVar15 + 100) =
         *(float *)(iVar14 + (iVar11 * 4 & 0x3ffcU)) * *(float *)(iVar13 + 0x1c) +
         *(float *)(iVar13 + 0x18);
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    fVar1 = *pfVar3;
    *(float *)(iVar15 + 0x68) =
         *(float *)(iVar14 + (iVar11 * 4 & 0x3ffcU)) * *(float *)(iVar13 + 0x24) +
         *(float *)(iVar13 + 0x20);
    if ((*(float *)(iVar15 + 0x60) == fVar1) &&
       ((*(float *)(iVar15 + 100) == pfVar3[1] && (*(float *)(iVar15 + 0x68) == pfVar3[2])))) {
      iVar14 = *(int *)(iVar12 + -0x7fc0);
    }
    else {
LAB_00d1c3b8:
      iVar14 = *(int *)(iVar12 + -0x7fc0);
      *(ushort *)(iVar15 + 0x34) = *(ushort *)(iVar15 + 0x34) | 2;
    }
  }
  else if ((*puVar9 & 0x800000) == 0) {
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    *(undefined4 *)(iVar15 + 0x20) = *(undefined4 *)(iVar14 + (iVar11 * 4 & 0x3ffcU));
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    *(undefined4 *)(iVar15 + 0x24) = *(undefined4 *)(iVar14 + (iVar11 * 4 & 0x3ffcU));
    iVar11 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar11;
    *(undefined4 *)(iVar15 + 0x28) = *(undefined4 *)(iVar14 + (iVar11 * 4 & 0x3ffcU));
    uVar7 = *puVar9 >> 5 & 7;
    if (uVar7 == 2) {
LAB_00d1c6b8:
      uVar10 = *(undefined4 *)(param_1 + 0x104);
    }
    else if (uVar7 < 3) {
      if (uVar7 == 1) {
        uVar10 = *(undefined4 *)(param_2 + 0x24);
      }
      else {
LAB_00d1c698:
        uVar10 = *(undefined4 *)(param_3 + 0xc);
      }
    }
    else if (uVar7 == 3) {
      if (*(int *)(param_1 + 0x1a0) == 0) goto LAB_00d1c6b8;
      uVar10 = *(undefined4 *)(*(int *)(param_1 + 0x1a0) + 0x104);
    }
    else {
      if (uVar7 != 4) goto LAB_00d1c698;
      uVar10 = *(undefined4 *)(**(int **)(iVar12 + -0x7fd4) + 100);
    }
    func_0x00ba187c(&uStack_d0,*(undefined1 *)puVar9,puVar9 + 1,*puVar9 >> 1 & 1,*puVar9 >> 2 & 7,
                    uVar10,auStack_f0,0);
    puVar4 = (undefined4 *)((uint)(iVar15 + 0x60) & 0xfffffff0);
    *puVar4 = uStack_d0;
    puVar4[1] = uStack_cc;
    puVar4[2] = uStack_c8;
    puVar4[3] = uStack_c4;
    if ((*puVar9 & 1) == 0) {
      iVar14 = *(int *)(iVar12 + -0x7fc0);
      *(ushort *)(iVar15 + 0x34) = *(ushort *)(iVar15 + 0x34) | 0x12;
    }
    else {
      pfVar3 = *(float **)(iVar12 + -0x7fb8);
      if (((*(float *)(iVar15 + 0x60) != *pfVar3) || (*(float *)(iVar15 + 100) != pfVar3[1])) ||
         (*(float *)(iVar15 + 0x68) != pfVar3[2])) goto LAB_00d1c3b8;
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
    uVar7 = *puVar9 >> 5 & 7;
    if (uVar7 == 2) {
LAB_00d1c738:
      uVar10 = *(undefined4 *)(param_1 + 0x104);
    }
    else if (uVar7 < 3) {
      if (uVar7 == 1) {
        uVar10 = *(undefined4 *)(param_2 + 0x24);
      }
      else {
LAB_00d1c304:
        uVar10 = *(undefined4 *)(param_3 + 0xc);
      }
    }
    else if (uVar7 == 3) {
      if (*(int *)(param_1 + 0x1a0) == 0) goto LAB_00d1c738;
      uVar10 = *(undefined4 *)(*(int *)(param_1 + 0x1a0) + 0x104);
    }
    else {
      if (uVar7 != 4) goto LAB_00d1c304;
      uVar10 = *(undefined4 *)(**(int **)(iVar12 + -0x7fd4) + 100);
    }
    func_0x00ba6018(&uStack_e0,*(undefined1 *)puVar9,puVar9 + 1,*puVar9 >> 1 & 1,*puVar9 >> 2 & 7,
                    uVar10,iVar15 + 0x20,0);
    puVar4 = (undefined4 *)((uint)(iVar15 + 0x60) & 0xfffffff0);
    *puVar4 = uStack_e0;
    puVar4[1] = uStack_dc;
    puVar4[2] = uStack_d8;
    puVar4[3] = uStack_d4;
    if ((*puVar9 & 1) == 0) {
      *(ushort *)(iVar15 + 0x34) = *(ushort *)(iVar15 + 0x34) | 0x32;
    }
    else {
      pfVar3 = *(float **)(iVar12 + -0x7fb8);
      if (((*(float *)(iVar15 + 0x60) != *pfVar3) || (*(float *)(iVar15 + 100) != pfVar3[1])) ||
         (*(float *)(iVar15 + 0x68) != pfVar3[2])) {
        *(ushort *)(iVar15 + 0x34) = *(ushort *)(iVar15 + 0x34) | 2;
      }
    }
  }
  if ((*(ushort *)(iVar13 + 0x42) == 0) ||
     (puVar9 = (uint *)((uint)*(ushort *)(iVar13 + 0x42) + iVar13), puVar9 == (uint *)0x0)) {
    iVar12 = **(int **)(param_1 + 0xec) + 1;
    **(int **)(param_1 + 0xec) = iVar12;
    uVar7 = *(uint *)(iVar14 + (iVar12 * 4 & 0x3ffcU));
    if (*(ushort *)(iVar13 + 0x46) == 0) {
      sVar6 = *(short *)(iVar13 + 0x44);
    }
    else {
      uVar5 = *(ushort *)(iVar13 + 0x46) + 1;
      sVar6 = *(short *)(iVar13 + 0x44) + ((short)uVar7 - (short)(uVar7 / uVar5) * (short)uVar5);
    }
    *(short *)(iVar15 + 0x36) = sVar6;
    goto joined_r0x00d1c4b0;
  }
  uVar7 = *puVar9 >> 5 & 7;
  if (uVar7 == 3) {
    if (*(int *)(param_1 + 0x1a0) == 0) {
LAB_00d1c6b0:
      uVar10 = *(undefined4 *)(param_1 + 0x104);
    }
    else {
      uVar10 = *(undefined4 *)(*(int *)(param_1 + 0x1a0) + 0x104);
    }
  }
  else if (uVar7 == 4) {
    uVar10 = *(undefined4 *)(**(int **)(iVar12 + -0x7fd4) + 100);
  }
  else {
    if (uVar7 == 2) goto LAB_00d1c6b0;
    uVar10 = *(undefined4 *)(param_2 + 0x24);
  }
  iVar13 = **(int **)(param_1 + 0xec) + 1;
  **(int **)(param_1 + 0xec) = iVar13;
  uVar8 = func_0x00ba5318(*(undefined1 *)puVar9,puVar9 + 1,*puVar9 >> 1 & 1,*puVar9 >> 2 & 7,uVar10,
                          *(undefined4 *)(iVar14 + (iVar13 * 4 & 0x3ffcU)),0);
  *(undefined2 *)(iVar15 + 0x36) = uVar8;
joined_r0x00d1c4b0:
  if ((param_7 & 0x10000) == 0) {
    uVar7 = func_0x00d1aef8(param_1,param_2,iVar15,param_5,*(undefined1 *)(param_3 + 0xb));
  }
  else {
    iVar13 = iVar15 + (uint)*(byte *)(param_3 + 0xb) * 4 + 0x30;
    dVar16 = (double)*(float *)(iVar13 + 8);
    *(float *)(iVar13 + 8) = (float)(dVar16 + (double)*(float *)(iVar15 + 0x10));
    func_0x00d1aef8(param_1,param_2,iVar15,auStack_a0,*(undefined1 *)(param_3 + 0xb));
    *(float *)(iVar15 + (uint)*(byte *)(param_3 + 0xb) * 4 + 0x38) = (float)dVar16;
    *(undefined4 *)(iVar15 + (uint)*(byte *)(param_3 + 0xb) * 4 + 0x70) = 0;
    uVar7 = func_0x00d1aef8(param_1,param_2,iVar15,param_5,*(undefined1 *)(param_3 + 0xb));
    vectorSubtractFloatingPoint(auStack_a0,*(undefined1 (*) [16])(param_5 & 0xfffffff0));
    func_0x0114f578(&uStack_b0,auStack_c0);
    uVar7 = uVar7 | param_7 | 0x180;
    puVar4 = (undefined4 *)((uint)param_6 & 0xfffffff0);
    *puVar4 = uStack_b0;
    puVar4[1] = uStack_ac;
    puVar4[2] = uStack_a8;
    puVar4[3] = uStack_a4;
  }
  return uVar7;
}


