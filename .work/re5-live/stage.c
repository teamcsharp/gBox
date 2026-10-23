
void FUN_0061852c(int param_1)

{
  int iVar1;
  
  iVar1 = iRam01714c1c;
  FUN_0054bad0(param_1);
  func_0x0054ba74(param_1);
  FUN_0054c2cc(param_1);
  if (*(byte *)(param_1 + 0x17) < 0x5d) {
                    /* WARNING: Could not recover jumptable at 0x006185c8. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (*(code *)(*(int *)((uint)*(byte *)(param_1 + 0x17) * 4 + *(int *)(iVar1 + -0x7db8)) +
              *(int *)(iVar1 + -0x7db8)))();
    return;
  }
  func_0x006115dc(param_1);
  func_0x005bbc2c(param_1);
  return;
}


