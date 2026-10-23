
void FUN_00610698(int param_1)

{
  uint uVar1;
  int *piVar2;
  int iVar3;
  char cVar4;
  int iVar5;
  
  iVar3 = iRam01714c1c;
  cVar4 = func_0x005bb910(param_1,0,0xff,0);
  func_0x0054bd6c(param_1);
  if (cVar4 == '\0') {
    return;
  }
  func_0x0054d468(param_1,cVar4);
  func_0x005bd5e0(param_1,0x726);
  func_0x0054d264(param_1,*(undefined4 *)(iVar3 + -0x7ed8));
  func_0x0054d264(param_1,*(undefined4 *)(iVar3 + -0x7ed4));
  func_0x0054d264(param_1,*(undefined4 *)(iVar3 + -0x7ed0));
  func_0x0060f998(param_1);
  uVar1 = *(uint *)(param_1 + 0x180);
  if ((1 << (uVar1 & 0x3f) & *(uint *)(param_1 + 0x188)) != 0) {
    piVar2 = *(int **)(iVar3 + -0x7ff8);
    iVar5 = uVar1 + 10;
    iVar3 = *(int *)(*(int *)(*piVar2 + 0x182d4) + 0x58);
    if ((iVar3 != 2) && (iVar5 = uVar1 + 0x38, iVar3 != 5)) {
      cVar4 = func_0x009c0abc();
      if (cVar4 == '\0') {
        cVar4 = func_0x009c1964(*(undefined4 *)(*piVar2 + 0x182d4));
        if (cVar4 == '\0') goto LAB_006107d8;
        iVar5 = *(int *)(param_1 + 0x180) + 0x1e;
      }
      else {
        iVar5 = *(int *)(param_1 + 0x180) + 0x14;
      }
    }
    if (-1 < iVar5) {
      func_0x0060ab4c(param_1,0,iVar5,0x184,0x19c);
    }
  }
LAB_006107d8:
  if (*(char *)(param_1 + 0x3b) != '\0') {
    return;
  }
  func_0x005bd24c(param_1,0,*(undefined4 *)(param_1 + 0x174));
  return;
}


