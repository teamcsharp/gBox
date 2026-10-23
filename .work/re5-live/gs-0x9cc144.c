
void FUN_009cc144(undefined4 *param_1)

{
  int iVar1;
  int *piVar2;
  
  iVar1 = param_1[0x31];
  *param_1 = *(undefined4 *)(iRam01714ed0 + -0x7fe0);
  if (((iVar1 == 1) || (iVar1 == 2)) || (iVar1 == 0)) {
    piVar2 = (int *)param_1[0x30];
    if (piVar2 != (int *)0x0) {
      (*(code *)**(undefined4 **)(*piVar2 + 4))(piVar2);
      param_1[0x30] = 0;
      func_0x0091452c(param_1);
      func_0x00914878(param_1);
      return;
    }
  }
  func_0x0091452c(param_1);
  func_0x00914878(param_1);
  return;
}


