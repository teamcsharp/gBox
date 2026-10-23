
undefined4 FUN_000ddbdc(undefined4 param_1,undefined4 param_2)

{
  undefined4 *puVar1;
  int *piVar2;
  undefined4 *puVar3;
  int iVar4;
  undefined4 *puVar5;
  undefined4 uVar6;
  undefined4 uVar7;
  
  iVar4 = iRam017147e8;
  puVar1 = *(undefined4 **)(iRam017147e8 + -0x7fb8);
  piVar2 = (int *)*puVar1;
  puVar5 = (undefined4 *)(*(code *)**(undefined4 **)(*piVar2 + 0x18))(piVar2,0x330,0x10);
  if (puVar5 != (undefined4 *)0x0) {
    func_0x0116aa88(puVar5,**(undefined4 **)(iVar4 + -0x7ec4),**(undefined4 **)(iVar4 + -0x7ec0));
    puVar5[200] = 0;
    func_0x01173df0(puVar5);
    puVar3 = *(undefined4 **)(iVar4 + -0x7fe8);
    piVar2 = (int *)*puVar3;
    uVar7 = **(undefined4 **)(iVar4 + -0x7ebc);
    uVar6 = (*(code *)**(undefined4 **)(*piVar2 + 0x18))(piVar2,uVar7,0x20);
    puVar5[200] = uVar6;
    func_0x0116a7d0(puVar5,uVar6,uVar7);
    uVar7 = func_0x00c2836c(param_1,param_2);
    func_0x01173c98();
    if (puVar5[200] != 0) {
      piVar2 = (int *)*puVar3;
      (*(code *)**(undefined4 **)(*piVar2 + 0x1c))(piVar2,puVar5[200]);
    }
    *puVar5 = *(undefined4 *)(iVar4 + -0x7eb8);
    func_0x0116a8d0(puVar5);
    piVar2 = (int *)*puVar1;
    (*(code *)**(undefined4 **)(*piVar2 + 0x1c))(piVar2,puVar5);
    return uVar7;
  }
  uVar7 = func_0x00c2836c(param_1,param_2);
  return uVar7;
}


