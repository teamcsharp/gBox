
int FUN_001426f8(void)

{
  uint uVar1;
  uint uVar2;
  
  uVar2 = *(uint *)(*(int *)(**(int **)(iRam0171482c + -0x7ffc) + 0x182d4) + 0x58) ^ 2;
  uVar1 = (int)uVar2 >> 0x1f;
  return ((int)(uVar1 - (uVar1 ^ uVar2)) >> 0x1f & 0xfffffffeU) + 10;
}


