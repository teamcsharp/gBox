
undefined4 * FUN_000e9d14(void)

{
  int iVar1;
  undefined4 *puVar2;
  undefined4 *puVar3;
  
  iVar1 = iRam017147e8;
  puVar3 = (undefined4 *)
           (*(code *)**(undefined4 **)(**(int **)(iRam017147e8 + -0x7fdc) + 0x18))
                     (*(int **)(iRam017147e8 + -0x7fdc),0x18378,0x10);
  puVar2 = (undefined4 *)0x0;
  if (puVar3 != (undefined4 *)0x0) {
    func_0x00c27390(puVar3);
    *puVar3 = *(undefined4 *)(iVar1 + -0x7e8c);
    func_0x00b7f838((int)puVar3 + 0x182d2);
    FUN_000e426c(puVar3);
    puVar2 = puVar3;
  }
  return puVar2;
}


