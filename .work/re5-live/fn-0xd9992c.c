
void FUN_00d9992c(int *param_1,int param_2,longlong param_3)

{
  uint uVar1;
  int iVar2;
  longlong lVar3;
  
  iVar2 = iRam017154b8;
  if (*(char *)(**(int **)(iRam017154b8 + -0x7ffc) + 0x82e08) != '\0') {
    lVar3 = (*(code *)**(undefined4 **)(*param_1 + 0x38))(param_1);
    param_3 = param_3 + lVar3;
  }
  uVar1 = param_1[7];
  *(ulonglong *)(*(int *)(param_2 + 8) + 0x230) =
       ((ulonglong)*(uint *)(*(int *)(iVar2 + -0x7ff8) + (uint)*(ushort *)(param_1 + 6) * 4) & 0xf)
       << 0x14 | *(ulonglong *)(*(int *)(param_2 + 8) + 0x230) & 0xffffffffff0fffff;
  *(ulonglong *)(*(int *)(param_2 + 8) + 0x230) =
       param_3 + (ulonglong)uVar1 & 0xfffff |
       *(ulonglong *)(*(int *)(param_2 + 8) + 0x230) & 0xfffffffffff00000;
  return;
}


