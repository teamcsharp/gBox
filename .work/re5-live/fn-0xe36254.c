
void FUN_00e36254(int param_1)

{
  int iVar1;
  int iVar2;
  int iVar3;
  
  iVar3 = iRam017154ec;
  if ((*(int *)(param_1 + 0x40) != 0) &&
     ((*(int *)(param_1 + 0x20) == 4 || (*(int *)(param_1 + 0x20) == 6)))) {
    iVar1 = *(int *)(param_1 + 0x4c);
    *(undefined4 *)(param_1 + 0x20) = 7;
    func_0x01399428(iVar1 + 0x30,0);
    if ((*(int *)(iVar1 + 0x28) == 4) || (*(int *)(iVar1 + 0x28) == 6)) {
      if (*(char *)(iVar1 + 0x50) == '\0') {
        *(ulonglong *)(*(int *)(iVar1 + 0x1e0) + 0x180) =
             *(ulonglong *)(*(int *)(iVar1 + 0x1e0) + 0x180) | 0x40;
        iVar2 = *(int *)(iVar1 + 0x1dc);
      }
      else {
        iVar2 = *(int *)(iVar1 + 0x1dc);
      }
      if (iVar2 != -1) {
        func_0x00c8211c(**(undefined4 **)(iVar3 + -0x7fc8),iVar1);
        *(undefined4 *)(iVar1 + 0x1d4) = 0xffffffff;
        *(undefined1 *)(iVar1 + 0x1d0) = 0;
      }
      *(undefined4 *)(iVar1 + 0x28) = 7;
    }
    func_0x01399448(iVar1 + 0x30);
    return;
  }
  return;
}


