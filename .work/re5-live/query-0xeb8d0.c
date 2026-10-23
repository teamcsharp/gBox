
void FUN_000eb8d0(int param_1,undefined8 param_2,uint *param_3)

{
  byte bVar1;
  undefined1 uVar2;
  undefined1 uVar3;
  undefined1 uVar4;
  int *piVar5;
  int iVar6;
  uint uVar7;
  
  piVar5 = *(int **)(iRam017147ec + -0x7ffc);
  if ((*param_3 >> 8 & 0xfff) == *(uint *)(*(int *)(*piVar5 + 0x182d4) + 0x2e8)) {
    bVar1 = *(byte *)(param_3 + 9);
    if (bVar1 >> 4 != 3) {
      func_0x00108700(param_1,0);
      return;
    }
    *(undefined4 *)(param_1 + 0x9a4) = 1;
    *(undefined1 *)(param_1 + 0x9ac) = 0;
    *(undefined4 *)(param_1 + 0x798) = 1;
    *(undefined4 *)(param_1 + 0x79c) = 0;
    *(undefined4 *)(param_1 + 0x7a0) = 0;
    *(undefined4 *)(param_1 + 0x7cc) = 0;
    *(undefined4 *)(param_1 + 0x7a4) = 0;
    *(undefined4 *)(param_1 + 0x7a8) = 0;
    *(undefined4 *)(param_1 + 0x7ac) = 0;
    *(undefined4 *)(param_1 + 0x7b0) = 0;
    *(undefined4 *)(param_1 + 0x7b4) = 0;
    *(undefined4 *)(param_1 + 0x7b8) = 0;
    *(undefined4 *)(param_1 + 0x7bc) = 0;
    *(undefined4 *)(param_1 + 0x7c0) = 0;
    *(undefined4 *)(param_1 + 0x7c4) = 0;
    *(undefined4 *)(param_1 + 0x7c8) = 0;
    uVar7 = bVar1 & 0xf;
    uVar2 = *(undefined1 *)((int)param_3 + 5);
    uVar3 = *(undefined1 *)((int)param_3 + 6);
    uVar4 = *(undefined1 *)((int)param_3 + 7);
    *(undefined1 *)(param_1 + 0x79c) = *(undefined1 *)(param_3 + 1);
    *(undefined1 *)(param_1 + 0x79d) = uVar2;
    *(undefined1 *)(param_1 + 0x79e) = uVar3;
    *(undefined1 *)(param_1 + 0x79f) = uVar4;
    uVar2 = *(undefined1 *)((int)param_3 + 9);
    uVar3 = *(undefined1 *)((int)param_3 + 10);
    uVar4 = *(undefined1 *)((int)param_3 + 0xb);
    *(undefined1 *)(param_1 + 0x7a0) = *(undefined1 *)(param_3 + 2);
    *(undefined1 *)(param_1 + 0x7a1) = uVar2;
    *(undefined1 *)(param_1 + 0x7a2) = uVar3;
    *(undefined1 *)(param_1 + 0x7a3) = uVar4;
    uVar2 = *(undefined1 *)((int)param_3 + 0xd);
    uVar3 = *(undefined1 *)((int)param_3 + 0xe);
    uVar4 = *(undefined1 *)((int)param_3 + 0xf);
    *(undefined1 *)(param_1 + 0x7a4) = *(undefined1 *)(param_3 + 3);
    *(undefined1 *)(param_1 + 0x7a5) = uVar2;
    *(undefined1 *)(param_1 + 0x7a6) = uVar3;
    *(undefined1 *)(param_1 + 0x7a7) = uVar4;
    uVar2 = *(undefined1 *)((int)param_3 + 0x11);
    uVar3 = *(undefined1 *)((int)param_3 + 0x12);
    uVar4 = *(undefined1 *)((int)param_3 + 0x13);
    *(undefined1 *)(param_1 + 0x7a8) = *(undefined1 *)(param_3 + 4);
    *(undefined1 *)(param_1 + 0x7a9) = uVar2;
    *(undefined1 *)(param_1 + 0x7aa) = uVar3;
    *(undefined1 *)(param_1 + 0x7ab) = uVar4;
    uVar2 = *(undefined1 *)((int)param_3 + 0x15);
    uVar3 = *(undefined1 *)((int)param_3 + 0x16);
    uVar4 = *(undefined1 *)((int)param_3 + 0x17);
    *(undefined1 *)(param_1 + 0x7ac) = *(undefined1 *)(param_3 + 5);
    *(undefined1 *)(param_1 + 0x7ad) = uVar2;
    *(undefined1 *)(param_1 + 0x7ae) = uVar3;
    *(undefined1 *)(param_1 + 0x7af) = uVar4;
    uVar2 = *(undefined1 *)((int)param_3 + 0x19);
    uVar3 = *(undefined1 *)((int)param_3 + 0x1a);
    uVar4 = *(undefined1 *)((int)param_3 + 0x1b);
    *(undefined1 *)(param_1 + 0x7b0) = *(undefined1 *)(param_3 + 6);
    *(undefined1 *)(param_1 + 0x7b3) = uVar4;
    *(undefined1 *)(param_1 + 0x7b1) = uVar2;
    *(undefined1 *)(param_1 + 0x7b2) = uVar3;
    uVar2 = *(undefined1 *)((int)param_3 + 0x1f);
    uVar3 = *(undefined1 *)((int)param_3 + 0x1d);
    uVar4 = *(undefined1 *)((int)param_3 + 0x1e);
    *(undefined1 *)(param_1 + 0x7b4) = *(undefined1 *)(param_3 + 7);
    *(undefined1 *)(param_1 + 0x7b5) = uVar3;
    *(undefined1 *)(param_1 + 0x7b6) = uVar4;
    *(undefined1 *)(param_1 + 0x7b7) = uVar2;
    uVar2 = *(undefined1 *)((int)param_3 + 0x21);
    uVar3 = *(undefined1 *)((int)param_3 + 0x22);
    uVar4 = *(undefined1 *)((int)param_3 + 0x23);
    *(undefined1 *)(param_1 + 0x7b8) = *(undefined1 *)(param_3 + 8);
    *(undefined1 *)(param_1 + 0x7b9) = uVar2;
    *(undefined1 *)(param_1 + 0x7ba) = uVar3;
    *(undefined1 *)(param_1 + 0x7bb) = uVar4;
    *(char *)(param_1 + 0x7bc) = (char)uVar7;
    *(undefined1 *)(param_1 + 0x7be) = *(undefined1 *)((int)param_3 + 0x25);
    *(undefined1 *)(param_1 + 0x7bf) = *(undefined1 *)((int)param_3 + 0x26);
    *(undefined1 *)(param_1 + 0x7c2) = *(undefined1 *)((int)param_3 + 0x27);
    *(undefined2 *)(param_1 + 0x7c0) = *(undefined2 *)(param_3 + 10);
    *(undefined1 *)(param_1 + 0x7c3) = *(undefined1 *)((int)param_3 + 0x2a);
    *(byte *)(param_1 + 0x7c4) = *(byte *)((int)param_3 + 0x2b) & 1;
    *(byte *)(param_1 + 0x7c5) = *(byte *)((int)param_3 + 0x2b) >> 1 & 1;
    *(uint *)(*(int *)(*piVar5 + 0x182d4) + 0x58) = uVar7;
    iVar6 = *(int *)(*(int *)(*piVar5 + 0x182d4) + 0x58);
    if ((iVar6 == 3) || (iVar6 == 4)) {
      *(undefined1 *)(param_1 + 0x7bf) = *(undefined1 *)((int)param_3 + 0x2d);
      *(undefined1 *)(param_1 + 0x7c5) = *(undefined1 *)(param_3 + 0xb);
      return;
    }
  }
  return;
}


