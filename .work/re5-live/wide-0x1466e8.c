
int FUN_001466e8(int param_1,int param_2)

{
  undefined4 *puVar1;
  int iVar2;
  int iVar3;
  int iVar4;
  int iVar5;
  uint uVar6;
  undefined4 auStack_a0 [4];
  undefined4 uStack_90;
  undefined4 uStack_8c;
  undefined1 auStack_88 [80];
  
  iVar3 = iRam0171482c;
  puVar1 = *(undefined4 **)(iRam0171482c + -0x7f4c);
  auStack_a0[0] = *puVar1;
  uStack_8c = puVar1[5];
  auStack_a0[1] = puVar1[1];
  auStack_a0[2] = puVar1[2];
  auStack_a0[3] = puVar1[3];
  uStack_90 = puVar1[4];
  iVar4 = func_0x00fe6bec(param_2,0x5c);
  if (iVar4 != 0) {
    func_0x00fe6bfc(auStack_88,param_2);
    iVar2 = *(int *)(param_1 + 0x24);
    auStack_88[iVar4 - param_2] = 0;
    uVar6 = *(uint *)(param_1 + iVar2 * 0x7eb8 + 0x7c);
    if (5 < uVar6) {
      uVar6 = 0;
    }
    if ((*(char *)(param_1 + 0x20) != '\0') || (**(char **)(iVar3 + -0x7f50) != '\0')) {
      func_0x01399428(param_1 + 8,0);
    }
    iVar2 = *(int *)(iVar3 + -0x8000);
    iVar5 = iVar2 + 0x28;
    func_0x00fe6bbc(iVar5,*(undefined4 *)(iVar3 + -0x7f48),auStack_88,auStack_a0[uVar6],
                    auStack_88 + (iVar4 - param_2) + 1);
    if ((*(char *)(param_1 + 0x20) == '\0') && (**(char **)(iVar3 + -0x7f50) == '\0')) {
      return iVar5;
    }
    param_2 = iVar2 + 0x28;
    func_0x01399448(param_1 + 8);
  }
  return param_2;
}


