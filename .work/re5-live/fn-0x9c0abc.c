
undefined4 FUN_009c0abc(int param_1)

{
  undefined4 uVar1;
  
  uVar1 = 0;
  if (*(int *)(param_1 + 0x58) == 1) {
    if ((*(int *)(param_1 + 0x340) != 0) && (*(int *)(param_1 + 0x340) != 2)) {
      return 0;
    }
    uVar1 = 1;
  }
  return uVar1;
}


