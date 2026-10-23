
void FUN_00ca2c14(int param_1)

{
  undefined4 *puVar1;
  int *piVar2;
  int iVar3;
  undefined4 uVar4;
  int iVar5;
  uint *puVar6;
  undefined4 uVar7;
  
  iVar3 = iRam01715490;
  puVar1 = *(undefined4 **)(iRam01715490 + -0x7ff4);
  *(undefined1 *)(param_1 + 6) = 7;
  uVar4 = func_0x00c5ff9c(*puVar1,*(undefined4 *)(iVar3 + -0x7ff0),*(undefined4 *)(iVar3 + -0x7fec),
                          1);
  piVar2 = *(int **)(iVar3 + -0x7ffc);
  uVar7 = *(undefined4 *)(iVar3 + -0x7fe8);
  *(undefined4 *)(param_1 + 0x38) = uVar4;
  uVar4 = func_0x00c6fe24(*piVar2,uVar7);
  uVar7 = *(undefined4 *)(iVar3 + -0x7fe4);
  *(undefined4 *)(param_1 + 0x18) = uVar4;
  iVar5 = func_0x00c6a468(*piVar2,uVar7,0,1);
  *(int *)(param_1 + 0x1c) = iVar5;
  puVar6 = (uint *)func_0x00c62a8c(iVar5 * 0x14 + *piVar2 + 0x838);
  *puVar6 = *puVar6 & 0xffffff1f | 0x40;
  puVar6 = (uint *)func_0x00c62a8c(*(int *)(param_1 + 0x1c) * 0x14 + *piVar2 + 0x838);
  *puVar6 = *puVar6 & 0xffffffe3 | 8;
  iVar5 = func_0x00c62a8c(*(int *)(param_1 + 0x1c) * 0x14 + *piVar2 + 0x838);
  *(uint *)(iVar5 + 4) = *(uint *)(iVar5 + 4) & 0x1fffffff | 0x40000000;
  func_0x00c6646c(*(int *)(param_1 + 0x1c) * 0x14 + *piVar2 + 0x838,4);
  func_0x00c665f0(*(int *)(param_1 + 0x1c) * 0x14 + *piVar2 + 0x838,4);
  iVar5 = func_0x00c62a8c(*(int *)(param_1 + 0x1c) * 0x14 + *piVar2 + 0x838);
  uVar7 = *(undefined4 *)(iVar3 + -0x7fe0);
  *(undefined4 *)(iVar5 + 8) = 0;
  uVar4 = func_0x00c6a468(*piVar2,uVar7,4,4);
  uVar7 = *(undefined4 *)(iVar3 + -0x7fdc);
  *(undefined4 *)(param_1 + 0x20) = uVar4;
  uVar4 = func_0x00c6a468(*piVar2,uVar7,4,1);
  uVar7 = *(undefined4 *)(iVar3 + -0x7fd8);
  *(undefined4 *)(param_1 + 0x24) = uVar4;
  uVar4 = func_0x00c6a468(*piVar2,uVar7,4,1);
  uVar7 = *(undefined4 *)(iVar3 + -0x7fd4);
  *(undefined4 *)(param_1 + 0x28) = uVar4;
  uVar4 = func_0x00c6a468(*piVar2,uVar7,4,1);
  uVar7 = *(undefined4 *)(iVar3 + -0x7fd0);
  *(undefined4 *)(param_1 + 0x2c) = uVar4;
  uVar4 = func_0x00c6a468(*piVar2,uVar7,4,1);
  uVar7 = *(undefined4 *)(iVar3 + -0x7fcc);
  *(undefined4 *)(param_1 + 0x30) = uVar4;
  uVar7 = func_0x00c6a468(*piVar2,uVar7,4,1);
  *(undefined4 *)(param_1 + 0x7c) = *(undefined4 *)(iVar3 + -0x7fc8);
  *(undefined4 *)(param_1 + 0x34) = uVar7;
  *(undefined4 *)(param_1 + 0x80) = 3;
  *(undefined4 *)(param_1 + 0x78) = 0;
  *(undefined4 *)(param_1 + 0x3c) = 0;
  *(undefined4 *)(param_1 + 0x40) = 0;
  *(undefined4 *)(param_1 + 0x44) = 0;
  *(undefined4 *)(param_1 + 0x48) = 0;
  *(undefined4 *)(param_1 + 0x54) = 0;
  *(undefined4 *)(param_1 + 0x4c) = 0;
  *(undefined4 *)(param_1 + 0x58) = 0;
  *(undefined4 *)(param_1 + 100) = 0;
  *(undefined4 *)(param_1 + 0x5c) = 0;
  *(undefined4 *)(param_1 + 0x68) = 0;
  *(undefined4 *)(param_1 + 0x6c) = 0;
  *(undefined4 *)(param_1 + 0x70) = 0;
  return;
}


