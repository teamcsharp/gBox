
undefined4 FUN_00110c68(int param_1,int param_2)

{
  longlong lVar1;
  
  if (param_2 == -1) {
    return 0xffffffff;
  }
  if (-1 < param_2) {
    if ((*(int *)(param_1 + 0x1fac) == -1) || (lVar1 = 0, *(int *)(param_1 + 0x1fb0) != param_2)) {
      if (*(int *)(param_1 + 0x1fdc) == -1) {
        return 0xffffffff;
      }
      if (*(int *)(param_1 + 0x1fe0) != param_2) {
        return 0xffffffff;
      }
      lVar1 = 1;
    }
    param_1 = ((int)(lVar1 << 6) - (int)(lVar1 << 4)) + param_1;
    if (param_1 != -0x1fa8) {
      return *(undefined4 *)(param_1 + 0x1fac);
    }
  }
  return 0xffffffff;
}


