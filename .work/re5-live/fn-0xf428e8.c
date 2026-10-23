
void FUN_00f428e8(undefined8 param_1,uint param_2)

{
  if (param_2 < 0xd) {
                    /* WARNING: Could not recover jumptable at 0x00f42928. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (*(code *)(*(int *)(param_2 * 4 + *(int *)(iRam017155d8 + -0x8000)) +
              *(int *)(iRam017155d8 + -0x8000)))();
    return;
  }
  return;
}


