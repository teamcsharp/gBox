
undefined4 * FUN_009c2554(void)

{
  undefined4 uVar1;
  int iVar2;
  undefined4 *puVar3;
  undefined4 *puVar4;
  
  iVar2 = iRam01714ec8;
  puVar3 = (undefined4 *)func_0x00b30fe4(0x500);
  puVar4 = (undefined4 *)0x0;
  if (puVar3 != (undefined4 *)0x0) {
    uVar1 = *(undefined4 *)(iVar2 + -0x7ffc);
    puVar3[0xb7] = 0;
    *puVar3 = uVar1;
    puVar4 = puVar3;
  }
  return puVar4;
}


