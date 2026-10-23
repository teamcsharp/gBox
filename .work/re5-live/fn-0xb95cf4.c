
undefined4 * FUN_00b95cf4(ulonglong param_1)

{
  undefined4 uVar1;
  int iVar2;
  undefined4 *puVar3;
  undefined4 *puVar4;
  
  iVar2 = iRam017153d4;
  puVar4 = (undefined4 *)func_0x00b30fe4(param_1 | 0x40);
  puVar3 = (undefined4 *)0x0;
  if (puVar4 != (undefined4 *)0x0) {
    uVar1 = *(undefined4 *)(iVar2 + -0x7fdc);
    *puVar4 = *(undefined4 *)(iVar2 + -0x7fd8);
    puVar4[0x10001] = 0;
    puVar4[0x1000c] = 0;
    puVar4[0x1000a] = 0;
    puVar4[0x1000b] = 0;
    func_0x00eee534(puVar4 + 0x10002,6,uVar1,0x38);
    puVar4[0x10005] = puVar4 + 1;
    puVar4[0x10006] = 0x40000;
    puVar3 = puVar4;
  }
  return puVar3;
}


