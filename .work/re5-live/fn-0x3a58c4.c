
void FUN_003a58c4(int param_1)

{
  int iVar1;
  int iVar2;
  int *piVar3;
  int iVar4;
  uint uVar5;
  uint uVar6;
  longlong lVar7;
  
  iVar4 = iRam01714a9c;
  func_0x00951664(param_1);
  piVar3 = *(int **)(param_1 + 8);
  *(undefined1 *)(param_1 + 0x17) = 0;
  *(undefined1 *)(param_1 + 0x14) = 0;
  *(undefined1 *)(param_1 + 0x15) = 0;
  *(undefined1 *)(param_1 + 0x16) = 0;
  if (piVar3 != (int *)0x0) {
    iVar2 = (*(code *)**(undefined4 **)(*piVar3 + 0x14))(piVar3);
    iVar4 = *(int *)(*(int *)(iVar4 + -0x7fe8) + 4);
    if (*(int *)(iVar2 + 4) == iVar4) goto LAB_003a59a4;
    iVar2 = *(int *)(iVar2 + 0x10);
    if (iVar2 != 0) {
      iVar1 = *(int *)(iVar2 + 4);
      while (iVar1 != iVar4) {
        iVar2 = *(int *)(iVar2 + 0x10);
        if (iVar2 == 0) goto LAB_003a59a0;
        iVar1 = *(int *)(iVar2 + 4);
      }
      goto LAB_003a59a4;
    }
  }
LAB_003a59a0:
  piVar3 = (int *)0x0;
LAB_003a59a4:
  iVar4 = 0;
  lVar7 = 4;
  *(int **)(param_1 + 0x74) = piVar3;
  *(undefined4 *)(param_1 + 0x78) = 0;
  do {
    iVar2 = param_1 + iVar4;
    iVar4 = iVar4 + 0xc;
    *(undefined4 *)(iVar2 + 0x30) = 0;
    *(undefined4 *)(iVar2 + 0x28) = 0;
    *(undefined4 *)(iVar2 + 0x2c) = 0;
    lVar7 = lVar7 + -1;
  } while (lVar7 != 0);
  iVar4 = *(int *)(param_1 + 0x74);
  *(undefined4 *)(param_1 + 0x24) = 0;
  *(undefined4 *)(param_1 + 0x1c) = 0;
  *(undefined4 *)(param_1 + 0x20) = 0;
  if (*(int *)(iVar4 + 0x13b8) != 0) {
    uVar5 = 0;
    do {
      uVar6 = uVar5 + 1;
      iVar2 = func_0x009f8a48(iVar4 + 0x1320,uVar5);
      *(undefined4 *)(iVar2 + 0x2c4) = 1;
      uVar5 = uVar6;
    } while (uVar6 < *(uint *)(iVar4 + 0x13b8));
  }
  *(undefined1 *)(*(int *)(param_1 + 0x74) + 0x1254) = 1;
  *(undefined1 *)(param_1 + 0x14) = 0;
  *(undefined4 *)(param_1 + 0x7c) = 0;
  *(undefined1 *)(*(int *)(param_1 + 0x74) + 0x13c4) = 1;
  iVar4 = *(int *)(param_1 + 0x74);
  if (*(int *)(iVar4 + 0x21c0) != 0) {
    func_0x0046cb14(*(int *)(iVar4 + 0x21c0),5);
    *(uint *)(*(int *)(iVar4 + 0x21c0) + 0x1cf4) =
         *(uint *)(*(int *)(iVar4 + 0x21c0) + 0x1cf4) | 0x40;
  }
  if (*(int *)(iVar4 + 0x21cc) != 0) {
    func_0x0046cb14(*(int *)(iVar4 + 0x21cc),5);
    *(uint *)(*(int *)(iVar4 + 0x21cc) + 0x1cf4) =
         *(uint *)(*(int *)(iVar4 + 0x21cc) + 0x1cf4) | 0x40;
  }
  if (*(int *)(iVar4 + 0x21d8) != 0) {
    func_0x0046cb14(*(int *)(iVar4 + 0x21d8),5);
    *(uint *)(*(int *)(iVar4 + 0x21d8) + 0x1cf4) =
         *(uint *)(*(int *)(iVar4 + 0x21d8) + 0x1cf4) | 0x40;
  }
  if (*(int *)(iVar4 + 0x21e4) != 0) {
    func_0x0046cb14(*(int *)(iVar4 + 0x21e4),5);
    *(uint *)(*(int *)(iVar4 + 0x21e4) + 0x1cf4) =
         *(uint *)(*(int *)(iVar4 + 0x21e4) + 0x1cf4) | 0x40;
  }
  return;
}


