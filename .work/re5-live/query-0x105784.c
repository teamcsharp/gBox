
void FUN_00105784(int param_1)

{
  uint uVar1;
  int in_r0;
  int iVar2;
  int *piVar3;
  int iVar4;
  undefined4 *puVar5;
  ulonglong uVar6;
  undefined4 in_vr31_32_0;
  undefined4 uVar7;
  undefined4 in_vr31_32_1;
  undefined4 uVar8;
  undefined4 in_vr31_32_2;
  undefined4 uVar9;
  undefined4 in_vr31_32_3;
  undefined4 uVar10;
  ulonglong auStack_150 [5];
  undefined8 uStack_128;
  undefined4 uStack_e0;
  undefined4 uStack_dc;
  undefined4 uStack_d8;
  undefined4 uStack_d4;
  undefined4 uStack_d0;
  undefined4 uStack_cc;
  undefined4 uStack_c8;
  undefined4 uStack_c4;
  undefined4 uStack_c0;
  undefined4 uStack_bc;
  undefined4 uStack_b8;
  undefined4 uStack_b4;
  undefined4 uStack_b0;
  undefined4 uStack_ac;
  undefined4 uStack_a8;
  undefined4 uStack_a4;
  undefined4 uStack_a0;
  
  puVar5 = (undefined4 *)((int)auStack_150 + in_r0 & 0xfffffff0);
  *puVar5 = in_vr31_32_0;
  puVar5[1] = in_vr31_32_1;
  puVar5[2] = in_vr31_32_2;
  puVar5[3] = in_vr31_32_3;
  iVar4 = iRam017147f0;
  uStack_128 = 0x171c590;
  auStack_150[0] = ZEXT48(&stack0x00000000);
  iVar2 = (*(code *)**(undefined4 **)(**(int **)(param_1 + 0x3c) + 0x60))(*(int **)(param_1 + 0x3c))
  ;
  *(undefined4 *)(param_1 + 0x9a4) = 0;
  *(int *)(param_1 + 0x798) = iVar2;
  if (0 < iVar2) {
    piVar3 = *(int **)(iVar4 + -0x7ff4);
    iVar4 = 0;
    uVar10 = 0;
    uVar9 = 0;
    uVar8 = 0;
    uVar7 = 0;
    puVar5 = (undefined4 *)(param_1 + 0x79c);
    do {
      *puVar5 = 0;
      puVar5[1] = 0;
      puVar5[2] = 0;
      puVar5[3] = 0;
      puVar5[4] = 0;
      puVar5[5] = 0;
      puVar5[6] = 0;
      puVar5[7] = 0;
      puVar5[8] = 0;
      puVar5[9] = 0;
      puVar5[10] = 0;
      puVar5[0xc] = 0;
      puVar5[0xb] = 1;
      uStack_a0 = 0;
      uStack_e0 = uVar7;
      uStack_dc = uVar8;
      uStack_d8 = uVar9;
      uStack_d4 = uVar10;
      uStack_d0 = uVar7;
      uStack_cc = uVar8;
      uStack_c8 = uVar9;
      uStack_c4 = uVar10;
      uStack_c0 = uVar7;
      uStack_bc = uVar8;
      uStack_b8 = uVar9;
      uStack_b4 = uVar10;
      uStack_b0 = uVar7;
      uStack_ac = uVar8;
      uStack_a8 = uVar9;
      uStack_a4 = uVar10;
      (*(code *)**(undefined4 **)(**(int **)(param_1 + 0x3c) + 100))
                (*(int **)(param_1 + 0x3c),puVar5,0x20,iVar4);
      (*(code *)**(undefined4 **)(**(int **)(param_1 + 0x3c) + 0x84))
                (*(int **)(param_1 + 0x3c),iVar4,ZEXT48(&stack0x00000000) - 0xe0 & 0xffffffff);
      *(byte *)(puVar5 + 8) = (byte)uStack_d8 & 7;
      *(char *)((int)puVar5 + 0x21) = (char)((uint)uStack_d8 >> 0x10);
      *(char *)((int)puVar5 + 0x22) = (char)uStack_d0;
      *(char *)((int)puVar5 + 0x23) = (char)uStack_c8;
      *(char *)((int)puVar5 + 0x26) = (char)uStack_c0;
      *(char *)(puVar5 + 10) = (char)uStack_b8;
      *(char *)((int)puVar5 + 0x29) = (char)uStack_b0;
      *(short *)(puVar5 + 9) = (short)uStack_a8;
      *(char *)((int)puVar5 + 0x27) = (char)uStack_a0;
      if (*(uint *)(*(int *)(*piVar3 + 0x182d4) + 100) < 2) {
        iVar2 = *(int *)(param_1 + 0x9a4);
        *(int *)(param_1 + 0x9a4) = iVar2 + 1;
        *(char *)(param_1 + iVar2 + 0x9ac) = (char)iVar4;
      }
      iVar4 = iVar4 + 1;
      iVar2 = *(int *)(param_1 + 0x798);
      puVar5 = puVar5 + 0xd;
    } while (iVar4 < iVar2);
  }
  if (iVar2 != 0) {
    uVar1 = *(uint *)(param_1 + 0x798);
    if (0 < (int)uVar1) {
      uVar6 = (ulonglong)uVar1;
      iVar2 = 0;
      piVar3 = (int *)(param_1 + 0x770);
      do {
        *piVar3 = iVar2;
        iVar2 = iVar2 + 1;
        piVar3 = piVar3 + 1;
        uVar6 = uVar6 - 1;
      } while (uVar6 != 0);
    }
    (*(code *)**(undefined4 **)(**(int **)(param_1 + 0x3c) + 0x5c))
              (*(int **)(param_1 + 0x3c),uVar1,(int *)(param_1 + 0x770));
    *(undefined1 *)(param_1 + 0x1334) = 1;
  }
  return;
}


