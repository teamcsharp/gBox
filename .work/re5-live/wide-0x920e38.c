
void FUN_00920e38(undefined4 *param_1)

{
  int iVar1;
  int *piVar2;
  undefined1 *puVar3;
  int iVar4;
  char cVar5;
  int *piVar6;
  
  iVar4 = iRam01714e70;
  func_0x0091a174();
  iVar1 = *(int *)(iVar4 + -0x8000);
  piVar2 = *(int **)(iVar4 + -0x7fc4);
  *param_1 = *(undefined4 *)(iVar4 + -0x7ec8);
  *(undefined4 *)(iVar1 + 0x24) = 0;
  *(undefined1 *)((int)param_1 + 0x26) = 0;
  *(undefined1 *)(param_1 + 2) = 0;
  param_1[5] = 0;
  param_1[6] = 0;
  param_1[7] = 0;
  param_1[8] = 0;
  *(undefined1 *)((int)param_1 + 7) = 0;
  *(undefined1 *)((int)param_1 + 6) = 0;
  *(undefined1 *)((int)param_1 + 5) = 0;
  *(undefined1 *)(param_1 + 1) = 0;
  *(undefined1 *)(param_1 + 9) = 0;
  *(undefined1 *)((int)param_1 + 0x25) = 0;
  *(undefined1 *)(*(int *)(*piVar2 + 0x182d4) + 0x28) = 1;
  if ((*(uint *)(*piVar2 + 0x182dc) & 1) == 0) {
    piVar6 = *(int **)(iVar4 + -0x7ef8);
    iVar1 = *piVar6;
    func_0x00aee8b0(iVar1 + *(int *)(iVar1 + 0x24) * 0x7eb8 + 0x40);
    FUN_00147714(iVar1);
  }
  else {
    piVar6 = *(int **)(iVar4 + -0x7ef8);
  }
  cVar5 = func_0x00aee51c(*piVar6 + *(int *)(*piVar6 + 0x24) * 0x7eb8 + 0x40);
  if (cVar5 == '\0') {
    iVar1 = *piVar2;
    if ((*(char *)(iVar1 + 0x20) == '\0') && (**(char **)(iVar4 + -0x7eac) == '\0')) {
      *(uint *)(iVar1 + 0x182dc) = *(uint *)(iVar1 + 0x182dc) & 0xffdfffff;
      cVar5 = *(char *)(iVar1 + 0x20);
    }
    else {
      func_0x01399428(iVar1 + 8,0);
      *(uint *)(iVar1 + 0x182dc) = *(uint *)(iVar1 + 0x182dc) & 0xffdfffff;
      cVar5 = *(char *)(iVar1 + 0x20);
    }
  }
  else {
    iVar1 = *piVar2;
    if ((*(char *)(iVar1 + 0x20) != '\0') || (**(char **)(iVar4 + -0x7eac) != '\0')) {
      func_0x01399428(iVar1 + 8,0);
    }
    *(uint *)(iVar1 + 0x182dc) = *(uint *)(iVar1 + 0x182dc) | 0x200000;
    cVar5 = *(char *)(iVar1 + 0x20);
  }
  if ((cVar5 != '\0') || (**(char **)(iVar4 + -0x7eac) != '\0')) {
    func_0x01399448(iVar1 + 8);
  }
  puVar3 = *(undefined1 **)(iVar4 + -0x7edc);
  **(undefined4 **)(iVar4 + -0x7ee4) = 0;
  *puVar3 = 0;
  return;
}


