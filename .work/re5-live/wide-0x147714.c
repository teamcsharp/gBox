
void FUN_00147714(int param_1)

{
  int iVar1;
  int iVar2;
  char cVar3;
  
  iVar1 = iRam0171482c;
  func_0x00aee844(param_1 + *(int *)(param_1 + 0x24) * 0x7eb8 + 0x40);
  func_0x009be718(param_1 + *(int *)(param_1 + 0x24) * 0x5940 + 0x1fb20);
  cVar3 = func_0x00aee51c(param_1 + *(int *)(param_1 + 0x24) * 0x7eb8 + 0x40);
  if (cVar3 == '\0') {
    iVar2 = *(int *)(param_1 + 0x24);
    if (*(int *)(param_1 + iVar2 * 0x5940 + 0x23cd4) == 0) goto LAB_001478b4;
    if ((*(char *)(param_1 + 0x20) != '\0') || (**(char **)(iVar1 + -0x7f50) != '\0')) {
      func_0x01399428(param_1 + 8,0);
      iVar2 = *(int *)(param_1 + 0x24);
    }
    func_0x009bded8(param_1 + iVar2 * 0x5940 + 0x1fb20);
    if ((*(char *)(param_1 + 0x20) != '\0') || (**(char **)(iVar1 + -0x7f50) != '\0')) {
      iVar2 = param_1 + 8;
      func_0x01399448(iVar2);
      if (*(char *)(param_1 + 0x20) == '\0') {
        if (**(char **)(iVar1 + -0x7f50) != '\0') {
          func_0x01399428(iVar2,0);
        }
      }
      else {
        func_0x01399428(iVar2,0);
      }
    }
    func_0x00a48370(param_1 + *(int *)(param_1 + 0x24) * 0x5940 + 0x1fc10);
    if ((*(char *)(param_1 + 0x20) != '\0') || (**(char **)(iVar1 + -0x7f50) != '\0')) {
      iVar2 = param_1 + 8;
      func_0x01399448(iVar2);
      if (*(char *)(param_1 + 0x20) == '\0') {
        if (**(char **)(iVar1 + -0x7f50) != '\0') {
          func_0x01399428(iVar2,0);
        }
      }
      else {
        func_0x01399428(iVar2,0);
      }
    }
    *(undefined4 *)(param_1 + *(int *)(param_1 + 0x24) * 0x5940 + 0x23cd4) = 0;
    if ((*(char *)(param_1 + 0x20) != '\0') || (**(char **)(iVar1 + -0x7f50) != '\0')) {
      func_0x01399448(param_1 + 8);
      iVar2 = *(int *)(param_1 + 0x24);
      goto LAB_001478b4;
    }
  }
  iVar2 = *(int *)(param_1 + 0x24);
LAB_001478b4:
  func_0x009be624(param_1 + iVar2 * 0x5940 + 0x1fb20);
  return;
}


