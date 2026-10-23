
void FUN_00f435cc(uint param_1)

{
  if (param_1 < 0xd) {
                    /* WARNING: Could not recover jumptable at 0x00f4360c. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (*(code *)(*(int *)(param_1 * 4 + *(int *)(iRam017155d8 + -0x7fe0)) +
              *(int *)(iRam017155d8 + -0x7fe0)))();
    return;
  }
  return;
}


