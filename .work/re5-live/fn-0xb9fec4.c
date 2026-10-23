
void FUN_00b9fec4(undefined8 param_1,undefined8 param_2,uint param_3)

{
  byte in_cr7;
  
  if ((!(bool)(in_cr7 >> 1 & 1)) && (param_3 < 7)) {
                    /* WARNING: Could not recover jumptable at 0x00b9ff24. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (*(code *)(*(int *)(param_3 * 4 + *(int *)(iRam017153e8 + -0x7fb8)) +
              *(int *)(iRam017153e8 + -0x7fb8)))();
    return;
  }
  return;
}


