
void FUN_000f350c(undefined8 param_1,undefined8 param_2,uint *param_3)

{
  int *piVar1;
  int *piVar2;
  int iVar3;
  ulonglong uVar4;
  ulonglong uVar5;
  int iVar6;
  char cVar8;
  int iVar7;
  int iVar9;
  undefined1 auStack_110 [224];
  
  iVar7 = iRam017147ec;
  piVar1 = *(int **)(iRam017147ec + -0x7ff8);
  uVar5 = (ulonglong)(*param_3 >> 8) & 0xfff;
  piVar2 = *(int **)(((int)(uVar5 << 4) - (int)(uVar5 << 2)) + *(int *)(*piVar1 + 0x84) + 8);
  if (piVar2 == (int *)0x0) {
    return;
  }
  iVar6 = (*(code *)**(undefined4 **)(*piVar2 + 0x14))(piVar2);
  iVar9 = *(int *)(*(int *)(iVar7 + -0x7f18) + 4);
  if (*(int *)(iVar6 + 4) != iVar9) {
    iVar6 = *(int *)(iVar6 + 0x10);
    if (iVar6 == 0) {
      return;
    }
    iVar3 = *(int *)(iVar6 + 4);
    while (iVar3 != iVar9) {
      iVar6 = *(int *)(iVar6 + 0x10);
      if (iVar6 == 0) {
        return;
      }
      iVar3 = *(int *)(iVar6 + 4);
    }
  }
  if (*(char *)(piVar2 + 0x687) < '\0') {
    return;
  }
  cVar8 = func_0x00204d8c(*piVar1,piVar2);
  if (cVar8 == '\0') {
    return;
  }
  *(undefined1 *)(piVar2 + 0x664) = 1;
  piVar2[0x668] = param_3[1];
  piVar2[0x669] = param_3[2];
  piVar2[0x66a] = param_3[3];
  piVar2[0x66c] = (uint)*(ushort *)(param_3 + 4);
  *(undefined1 *)(piVar2 + 0x66d) = *(undefined1 *)((int)param_3 + 0x12);
  *(undefined1 *)((int)piVar2 + 0x19b5) = *(undefined1 *)((int)param_3 + 0x13);
  *(undefined2 *)((int)piVar2 + 0x19b6) = *(undefined2 *)(param_3 + 5);
  piVar2[0x66e] = param_3[6];
  piVar2[0x670] = param_3[7];
  uVar5 = (ulonglong)*(ushort *)((int)param_3 + 0x16) & 0xf000;
  uVar4 = (ulonglong)*(ushort *)((int)param_3 + 0x16) & 0xfff;
  iVar9 = (int)uVar5;
  if (iVar9 == 0x2000) {
    iVar7 = *(int *)(((int)(uVar4 << 4) - (int)(uVar4 << 2)) + *(int *)(*piVar1 + 0x84) + 8);
    goto LAB_000f36bc;
  }
  if (uVar5 < 0x2001) {
    if (iVar9 == 0x1000) {
      iVar7 = func_0x001a617c(**(undefined4 **)(iVar7 + -0x7fe8),(int)uVar4);
      goto LAB_000f36bc;
    }
LAB_000f36b8:
    iVar7 = 0;
  }
  else {
    if (iVar9 == 0x3000) {
      iVar9 = (int)(uVar4 << 4);
      piVar1 = *(int **)(iVar7 + -0x7ff4);
      iVar7 = (int)(uVar4 << 2);
    }
    else {
      if (iVar9 != 0x4000) goto LAB_000f36b8;
      iVar9 = (int)(uVar4 << 4);
      piVar1 = *(int **)(iVar7 + -0x7ff0);
      iVar7 = (int)(uVar4 << 2);
    }
    iVar7 = *(int *)((iVar9 - iVar7) + *(int *)(*piVar1 + 0x84) + 8);
  }
LAB_000f36bc:
  piVar2[0x66f] = iVar7;
  piVar2[0x45d] = param_3[8];
  func_0x0082c0c0(piVar2,auStack_110);
  func_0x00541df8(piVar2,auStack_110);
  return;
}


