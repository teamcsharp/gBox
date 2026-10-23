
void FUN_00e339e8(int param_1)

{
  int iVar1;
  int iVar2;
  int iVar3;
  
  iVar1 = iRam017154ec;
  iVar2 = param_1 + 0x30;
  while( true ) {
    func_0x01399428(iVar2,0);
    if (*(int *)(param_1 + 0x28) != 1) break;
    syscall(0);
    func_0x01399448(iVar2);
  }
  func_0x01399448(iVar2);
  func_0x01399428(iVar2,0);
  iVar3 = *(int *)(param_1 + 0x28);
  if ((iVar3 == 4) || (iVar3 == 6)) {
    if (*(char *)(param_1 + 0x50) == '\0') {
      *(ulonglong *)(*(int *)(param_1 + 0x1e0) + 0x180) =
           *(ulonglong *)(*(int *)(param_1 + 0x1e0) + 0x180) | 0x40;
    }
    if (*(int *)(param_1 + 0x1dc) == -1) {
      iVar3 = *(int *)(param_1 + 0x28);
    }
    else {
      func_0x00c8211c(**(undefined4 **)(iVar1 + -0x7fc8),param_1);
      iVar3 = *(int *)(param_1 + 0x28);
      *(undefined4 *)(param_1 + 0x1d4) = 0xffffffff;
      *(undefined1 *)(param_1 + 0x1d0) = 0;
    }
  }
  if (1 < iVar3 - 8U) {
    *(undefined4 *)(param_1 + 0x28) = 8;
  }
  func_0x01399448(iVar2);
  return;
}


