
undefined4
FUN_0003a604(int param_1,undefined8 param_2,uint param_3,int *param_4,undefined8 param_5,int param_6
            ,int param_7,int param_8)

{
  int *piVar1;
  int iVar2;
  uint uVar3;
  uint uVar4;
  uint uVar5;
  int unaff_r30;
  
  if ((param_3 & *(uint *)(param_7 + 0x1ea0)) != 0) {
    piVar1 = *(int **)(unaff_r30 + -0x7f98);
    *(undefined4 *)(param_8 + -0x7c98) = *(undefined4 *)(param_1 + 0x38);
    *(undefined4 *)(*param_4 + 0x1836c) = *(undefined4 *)(param_1 + 0x3c);
    iVar2 = *piVar1;
    if ((*(char *)(iVar2 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7edc) != '\0')) {
      func_0x01399428(iVar2 + 8,0);
    }
    func_0x00aeec2c(iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0x40,1);
    if ((*(char *)(iVar2 + 0x20) == '\0') && (**(char **)(unaff_r30 + -0x7edc) == '\0')) {
      return 0;
    }
    func_0x01399448(iVar2 + 8);
    return 0;
  }
  uVar5 = *(uint *)(param_1 + 0x34);
  uVar3 = uVar5;
  if (((param_3 & 0x40040) != 0) && (uVar3 = uVar5 + 1, 1 < (int)uVar3)) {
    uVar3 = 1;
  }
  if ((param_3 & 0x10010) != 0) {
    uVar3 = uVar3 - 1 & (int)~(uVar3 - 1) >> 0x1f;
  }
  if (uVar3 != uVar5) {
    *(uint *)(param_1 + 0x34) = uVar3;
    uVar5 = uVar3;
  }
  iVar2 = uVar5 * 4;
  uVar5 = *(uint *)(param_6 + iVar2 + 0x38);
  uVar3 = uVar5;
  if ((param_3 & 0x20020) != 0) {
    uVar4 = *(int *)(param_6 + iVar2 + 0x48) - 1;
    uVar3 = uVar5 + 1;
    if ((int)uVar4 < (int)uVar3) goto LAB_0003a6c4;
  }
  uVar4 = uVar3;
LAB_0003a6c4:
  if ((param_3 & 0x80080) != 0) {
    uVar4 = uVar4 - 1 & (int)~(uVar4 - 1) >> 0x1f;
  }
  if (uVar4 != uVar5) {
    *(uint *)(param_6 + iVar2 + 0x38) = uVar4;
  }
  func_0x0003a244(param_6);
  return 1;
}


