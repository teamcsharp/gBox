
void FUN_00363fe4(int param_1)

{
  int iVar1;
  int iVar2;
  int iVar3;
  int *piVar4;
  
  iVar1 = iRam01714a8c;
  if (*(int *)(param_1 + 0x20) != 0) goto LAB_00364018;
  piVar4 = *(int **)(param_1 + 8);
  if (piVar4 == (int *)0x0) {
LAB_003640e8:
    piVar4 = (int *)0x0;
  }
  else {
    iVar3 = (*(code *)**(undefined4 **)(*piVar4 + 0x14))(piVar4);
    iVar1 = *(int *)(*(int *)(iVar1 + -0x7fe0) + 4);
    if (*(int *)(iVar3 + 4) != iVar1) {
      iVar3 = *(int *)(iVar3 + 0x10);
      if (iVar3 == 0) goto LAB_003640e8;
      iVar2 = *(int *)(iVar3 + 4);
      while (iVar2 != iVar1) {
        iVar3 = *(int *)(iVar3 + 0x10);
        if (iVar3 == 0) goto LAB_003640e8;
        iVar2 = *(int *)(iVar3 + 4);
      }
    }
  }
  *(int **)(param_1 + 0x20) = piVar4;
  *(undefined1 *)(piVar4 + 0x818) = 1;
LAB_00364018:
  *(undefined4 *)(param_1 + 0x24) = 0;
  *(undefined1 *)(param_1 + 0x14) = 0;
  *(byte *)(*(int *)(param_1 + 0x20) + 0x1a1c) = *(byte *)(*(int *)(param_1 + 0x20) + 0x1a1c) | 0x40
  ;
  *(undefined1 *)(param_1 + 0x28) = 0;
  return;
}


