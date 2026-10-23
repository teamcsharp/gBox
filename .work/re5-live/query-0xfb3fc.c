
void FUN_000fb3fc(undefined4 param_1,int param_2,uint *param_3)

{
  int *piVar1;
  uint uVar2;
  int iVar3;
  int iVar4;
  int iVar5;
  undefined4 uVar6;
  char cVar7;
  
  iVar5 = iRam017147ec;
  iVar3 = 0x171c590;
  piVar1 = *(int **)(iRam017147ec + -0x7fb4);
  iVar4 = func_0x000bbca0(*piVar1);
  if (iVar4 == 0) {
    return;
  }
  if (*(int *)(*piVar1 + 0x3834) == 0) {
    return;
  }
  uVar2 = *param_3 >> 8 & 0xfff;
  if (uVar2 == 0) {
    if (*(int *)(*(int *)(**(int **)(iVar5 + -0x7ffc) + 0x182d4) + 0x2e8) == param_2) {
      return;
    }
    iVar5 = func_0x000bbca0();
    if (*(char *)(iVar5 + 0x58) != '\0') {
      if (*(char *)(*(int *)(**(int **)(*(int *)(iVar3 + -0x7da4) + -0x7ffc) + 0x182d4) + 0x2e0) !=
          '\0') {
        iVar5 = *(int *)(*(int *)(iVar3 + -0x7da4) + -0x7e68);
                    /* WARNING: Could not recover jumptable at 0x000f9214. Too many branches */
                    /* WARNING: Treating indirect jump as call */
        (*(code *)(*(int *)(iVar5 + 0x2c) + iVar5))(param_1,0xb,1);
        return;
      }
      return;
    }
    uVar6 = func_0x000bbca0(*piVar1);
    cVar7 = func_0x00026060(uVar6);
    if (cVar7 == '\0') {
      return;
    }
    iVar5 = func_0x000bbca0(*piVar1);
    *(undefined1 *)(iVar5 + 0x58) = 1;
    iVar5 = func_0x000bbca0(*piVar1);
    *(uint *)(iVar5 + 0x5c) = param_3[1];
    iVar5 = func_0x000bbca0(*piVar1);
    *(byte *)(iVar5 + 0x74) = (byte)(-(ulonglong)*(byte *)(param_3 + 2) >> 0x3f);
    *(undefined2 *)(iVar5 + 0x76) = *(undefined2 *)((int)param_3 + 10);
    *(undefined1 *)(iVar5 + 0x78) = *(undefined1 *)(param_3 + 3);
    *(undefined1 *)(iVar5 + 0x79) = *(undefined1 *)((int)param_3 + 0xd);
    *(undefined1 *)(iVar5 + 0x7a) = *(undefined1 *)((int)param_3 + 0xe);
    *(undefined1 *)(iVar5 + 0x7b) = *(undefined1 *)((int)param_3 + 0xf);
    *(uint *)(iVar5 + 0x80) = param_3[4];
    *(uint *)(iVar5 + 0x84) = param_3[5];
    *(uint *)(iVar5 + 0x88) = param_3[6];
    *(undefined4 *)(iVar5 + 0x90) = 0;
    *(uint *)(iVar5 + 0x94) = param_3[7];
    *(undefined4 *)(iVar5 + 0x98) = 0;
    iVar5 = func_0x000bbca0(*piVar1);
  }
  else {
    if (uVar2 != 1) {
      return;
    }
    iVar5 = func_0x000bbca0();
  }
  if (iVar5 != 0) {
    iVar5 = func_0x000bbca0(*piVar1);
    *(undefined4 *)(iVar5 + 0x6c) = 3;
  }
  return;
}


