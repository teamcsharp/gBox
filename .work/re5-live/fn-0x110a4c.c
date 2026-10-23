
undefined4 FUN_00110a4c(int param_1,int param_2)

{
  undefined4 uVar1;
  
  uVar1 = 0;
  if (*(char *)(param_1 + 0x1f9c) == '\0') {
    uVar1 = *(undefined4 *)(param_1 + param_2 * 0x360 + 0x1b4);
  }
  return uVar1;
}


