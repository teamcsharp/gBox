
void FUN_005f4ec0(uint param_1)

{
  int *piVar1;
  int iVar2;
  int iVar3;
  ushort *puVar4;
  uint uVar5;
  longlong lVar6;
  
  iVar3 = iRam01714c10;
  uVar5 = 0;
  lVar6 = 0x21;
  puVar4 = *(ushort **)(iRam01714c10 + -0x7fd8);
  while (*puVar4 != param_1) {
    uVar5 = uVar5 + 1;
    lVar6 = lVar6 + -1;
    puVar4 = puVar4 + 6;
    if (lVar6 == 0) {
      return;
    }
  }
  if ((int)uVar5 < 0) {
    return;
  }
  piVar1 = *(int **)(iRam01714c10 + -0x7ffc);
  iVar2 = *piVar1;
  if ((1 << (uVar5 & 0x1f) &
      *(uint *)(iVar2 + (*(int *)(iVar2 + 0x24) * 0x1fae + (uVar5 >> 5)) * 4 + 0xcc)) != 0) {
    return;
  }
  if ((*(char *)(iVar2 + 0x20) != '\0') || (**(char **)(iRam01714c10 + -0x7f8c) != '\0')) {
    func_0x01399428(iVar2 + 8,0);
  }
  func_0x00aec784(iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0x40,uVar5);
  if ((*(char *)(iVar2 + 0x20) != '\0') || (**(char **)(iVar3 + -0x7f8c) != '\0')) {
    func_0x01399448(iVar2 + 8);
  }
  iVar2 = *piVar1;
  if ((*(char *)(iVar2 + 0x20) != '\0') || (**(char **)(iVar3 + -0x7f8c) != '\0')) {
    func_0x01399428(iVar2 + 8,0);
  }
  func_0x00aec7bc(iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0x40,uVar5);
  if ((*(char *)(iVar2 + 0x20) == '\0') && (**(char **)(iVar3 + -0x7f8c) == '\0')) {
    return;
  }
  func_0x01399448(iVar2 + 8);
  return;
}


