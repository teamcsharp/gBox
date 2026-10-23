
void FUN_00609dd0(int param_1)

{
  undefined4 *puVar1;
  int iVar2;
  int iVar3;
  
  iVar2 = iRam01714c1c;
  iVar3 = *(int *)(param_1 + 400);
  if (iVar3 != 0) {
    *(uint *)(iVar3 + 4) = *(uint *)(iVar3 + 4) & 0xfff7ffff;
    (*(code *)**(undefined4 **)(**(int **)(param_1 + 400) + 0x34))(*(int **)(param_1 + 400));
    *(undefined4 *)(param_1 + 400) = 0;
  }
  iVar3 = func_0x00e4ab14(*(undefined4 *)(iVar2 + -0x7fdc));
  *(int *)(param_1 + 400) = iVar3;
  if (iVar3 != 0) {
    *(uint *)(iVar3 + 4) =
         *(uint *)(iVar3 + 4) & 0xffc0ffff | *(uint *)(iVar3 + 4) & 0x3f0000 | 0x80000;
    func_0x00e4a554(*(undefined4 *)(param_1 + 400),*(undefined4 *)(param_1 + 0x18c));
    func_0x00e49af4(*(undefined4 *)(param_1 + 400),0);
    puVar1 = *(undefined4 **)(iVar2 + -0x7fd8);
    *(undefined1 *)(*(int *)(param_1 + 400) + 0x29) = 0;
    func_0x00c9a40c(*puVar1,2,*(undefined4 *)(param_1 + 400));
  }
  return;
}


