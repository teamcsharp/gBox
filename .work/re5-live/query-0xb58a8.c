
undefined4 * FUN_000b58a8(void)

{
  int iVar1;
  undefined4 uVar2;
  undefined4 uVar3;
  int iVar4;
  uint uVar5;
  undefined4 *puVar6;
  undefined4 *puVar7;
  
  iVar4 = iRam017147c4;
  puVar7 = (undefined4 *)func_0x00b30fe4(0x2e8);
  puVar6 = (undefined4 *)0x0;
  if (puVar7 != (undefined4 *)0x0) {
    *puVar7 = *(undefined4 *)(iVar4 + -0x7f20);
    func_0x00a0465c(puVar7 + 4);
    iVar1 = *(int *)(iVar4 + -0x8000);
    uVar2 = *(undefined4 *)(iVar4 + -0x7ffc);
    uVar3 = *(undefined4 *)(iVar4 + -0x7ff8);
    iVar4 = *(int *)(iVar1 + 0x6c);
    uVar5 = iVar4 + 1U & 7;
    puVar7[0x94] = uVar2;
    puVar7[0x9e] = uVar3;
    puVar7[0x97] = 0;
    *(undefined1 *)((int)puVar7 + 0x255) = 0;
    puVar7[0x98] = 0;
    puVar7[0x99] = 0;
    puVar7[0x9a] = 0;
    puVar7[0x9b] = 0;
    *(undefined1 *)(puVar7 + 0x95) = 0;
    puVar7[0x96] = iVar4 + 2;
    puVar7[0x9c] = 0;
    puVar7[0xa1] = 0;
    puVar7[0xa3] = 0;
    puVar7[0x9d] = 0;
    puVar7[0xa2] = 0xff;
    puVar7[0x9f] = 0;
    puVar7[0xa0] = 0;
    puVar7[0xa4] = 0;
    puVar7[0xa5] = uVar2;
    puVar7[0xaf] = uVar3;
    *(undefined1 *)(puVar7 + 0xa6) = 0;
    puVar7[0xa8] = 0;
    *(undefined1 *)((int)puVar7 + 0x299) = 0;
    puVar7[0xa9] = 0;
    puVar7[0xaa] = 0;
    puVar7[0xab] = 0;
    puVar7[0xac] = 0;
    puVar7[0xa7] = uVar5 + 2;
    puVar7[0xad] = 0;
    puVar7[0xae] = 0;
    puVar7[0xb2] = 0;
    puVar7[0xb4] = 0;
    puVar7[0xb3] = 0xff;
    puVar7[0xb0] = 0;
    puVar7[0xb1] = 0;
    puVar7[0xb5] = 0;
    *(uint *)(iVar1 + 0x6c) = uVar5 + 1 & 7;
    *(undefined1 *)(puVar7 + 1) = 0;
    puVar7[2] = 0;
    *(undefined1 *)(puVar7 + 5) = 0;
    puVar7[0xb9] = 0;
    puVar7[0xb6] = 0;
    puVar7[0xb7] = 0;
    puVar7[0xb8] = 0;
    puVar6 = puVar7;
  }
  return puVar6;
}


