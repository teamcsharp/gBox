
void FUN_003b4cd4(int param_1)

{
  float fVar1;
  int iVar2;
  int iVar3;
  ulonglong uVar4;
  int iVar5;
  int iVar6;
  ulonglong uVar7;
  int *piVar8;
  
  iVar5 = iRam01714aa4;
  func_0x00951664(param_1);
  piVar8 = *(int **)(param_1 + 8);
  *(undefined1 *)(param_1 + 0x17) = 0;
  *(undefined1 *)(param_1 + 0x14) = 0;
  *(undefined1 *)(param_1 + 0x15) = 0;
  *(undefined1 *)(param_1 + 0x16) = 0;
  if (piVar8 != (int *)0x0) {
    iVar6 = (*(code *)**(undefined4 **)(*piVar8 + 0x14))(piVar8);
    iVar2 = *(int *)(*(int *)(iVar5 + -0x7fe8) + 4);
    if (*(int *)(iVar6 + 4) == iVar2) goto LAB_003b4db4;
    iVar6 = *(int *)(iVar6 + 0x10);
    if (iVar6 != 0) {
      iVar3 = *(int *)(iVar6 + 4);
      while (iVar3 != iVar2) {
        iVar6 = *(int *)(iVar6 + 0x10);
        if (iVar6 == 0) goto LAB_003b4db0;
        iVar3 = *(int *)(iVar6 + 4);
      }
      goto LAB_003b4db4;
    }
  }
LAB_003b4db0:
  piVar8 = (int *)0x0;
LAB_003b4db4:
  *(int **)(param_1 + 0x1c) = piVar8;
  fVar1 = *(float *)(iVar5 + -0x7f4c);
  *(undefined4 *)(param_1 + 0x20) = 0;
  *(undefined4 *)(param_1 + 0x24) = 0;
  *(undefined4 *)(param_1 + 0x28) = 0;
  *(undefined4 *)(param_1 + 0x2c) = 0;
  *(undefined4 *)(param_1 + 0x30) = 0;
  *(uint *)(*(int *)(param_1 + 0x1c) + 0x1c9c) = *(uint *)(*(int *)(param_1 + 0x1c) + 0x1c9c) | 0x40
  ;
  *(uint *)(*(int *)(param_1 + 0x1c) + 0x1c9c) = *(uint *)(*(int *)(param_1 + 0x1c) + 0x1c9c) | 1;
  *(uint *)(*(int *)(param_1 + 0x1c) + 0x1c9c) =
       *(uint *)(*(int *)(param_1 + 0x1c) + 0x1c9c) | 0x200000;
  *(float *)(param_1 + 0x34) = fVar1;
  uVar7 = (ulonglong)*(uint *)(*(int *)(param_1 + 0x1c) + 0x1174);
  *(undefined4 *)(param_1 + 0x40) = 0;
  *(undefined1 *)(param_1 + 0x3c) = 0;
  uVar4 = uVar7 / 0xf;
  *(float *)(param_1 + 0x38) =
       (float)(uVar7 - ((uVar4 & 0xfffffff) * 0x10 - uVar4) & 0xffffffff) + fVar1;
  return;
}


