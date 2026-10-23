
void FUN_005bd3b4(int *param_1)

{
  int *piVar1;
  int iVar2;
  int iVar3;
  uint uVar4;
  int iVar5;
  
  iVar3 = iRam01714bec;
  piVar1 = *(int **)(iRam01714bec + -0x7fc0);
  if ((*(uint *)(*piVar1 + 0x182dc) & 0x200000) == 0) {
    *(undefined1 *)(param_1 + 0x14) = 0;
  }
  else {
    *(undefined1 *)(param_1 + 0x14) = 1;
  }
  param_1[0x13] = 3;
  iVar2 = *(int *)(*(int *)(*piVar1 + 0x182d4) + 0x58);
  if (iVar2 == 0) {
    iVar3 = **(int **)(iVar3 + -0x7f9c);
    uVar4 = *(uint *)(iVar3 + *(int *)(iVar3 + 0x24) * 0x7eb8 + 0xa4) & 0x10;
joined_r0x005bd4c4:
    if (uVar4 == 0) goto LAB_005bd444;
  }
  else {
    iVar5 = 0;
    if (iVar2 != 3) {
      if (iVar2 != 4) goto LAB_005bd444;
      iVar5 = 1;
    }
    iVar3 = **(int **)(iVar3 + -0x7f9c);
    uVar4 = *(uint *)(iVar3 + (*(int *)(iVar3 + 0x24) * 0x1fae + iVar5) * 4 + 0x3f78);
    if ((uVar4 & 4) == 0) {
      uVar4 = uVar4 & 8;
      goto joined_r0x005bd4c4;
    }
  }
  param_1[0x13] = 4;
LAB_005bd444:
  (*(code *)**(undefined4 **)(*param_1 + 0x3c))(param_1);
  return;
}


