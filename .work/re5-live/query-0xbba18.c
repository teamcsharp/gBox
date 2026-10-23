
void FUN_000bba18(undefined4 param_1,int param_2)

{
  undefined4 uVar1;
  undefined4 uVar2;
  undefined4 uVar3;
  int iVar4;
  undefined4 *puVar5;
  undefined4 *puVar6;
  undefined1 auStack_50 [24];
  
  iVar4 = iRam017147d0;
  func_0x00b3f4f0(auStack_50);
  puVar5 = (undefined4 *)func_0x00b3f7a4(auStack_50,5,*(undefined4 *)(iVar4 + -0x7ff8));
  if (puVar5 != (undefined4 *)0x0) {
    puVar6 = (undefined4 *)func_0x00b3f6d4(param_2);
    uVar1 = puVar5[1];
    uVar2 = puVar5[2];
    uVar3 = puVar5[3];
    *puVar6 = *puVar5;
    puVar6[1] = uVar1;
    puVar6[2] = uVar2;
    puVar6[3] = uVar3;
    uVar1 = puVar5[5];
    uVar2 = puVar5[6];
    uVar3 = puVar5[7];
    puVar6[4] = puVar5[4];
    puVar6[7] = uVar3;
    puVar6[5] = uVar1;
    puVar6[6] = uVar2;
    uVar1 = puVar5[8];
    uVar2 = puVar5[0xb];
    uVar3 = puVar5[10];
    puVar6[9] = puVar5[9];
    puVar6[8] = uVar1;
    puVar6[10] = uVar3;
    puVar6[0xb] = uVar2;
    puVar6[0xd] = 0;
    puVar6[0xc] = 0;
    if (*(int *)(param_2 + 4) != 0) {
      *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar6;
      puVar6[0xd] = *(undefined4 *)(param_2 + 4);
    }
    *(undefined4 **)(param_2 + 4) = puVar6;
  }
  func_0x00bdf024(param_1,param_2);
  func_0x00b3fb28(auStack_50);
  return;
}


