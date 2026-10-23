
undefined4 * FUN_000b485c(void)

{
  int iVar1;
  undefined4 uVar2;
  int iVar3;
  undefined4 *puVar4;
  undefined4 *puVar5;
  
  iVar3 = iRam017147c4;
  puVar4 = (undefined4 *)func_0x00b30fe4(0x44);
  puVar5 = (undefined4 *)0x0;
  if (puVar4 != (undefined4 *)0x0) {
    iVar1 = *(int *)(iVar3 + -0x8000);
    uVar2 = *(undefined4 *)(iVar3 + -0x7ffc);
    puVar4[10] = *(undefined4 *)(iVar3 + -0x7ff8);
    *puVar4 = uVar2;
    puVar4[0xb] = 0;
    puVar4[0xc] = 0;
    *(undefined1 *)(puVar4 + 1) = 0;
    puVar4[3] = 0;
    *(undefined1 *)((int)puVar4 + 5) = 0;
    iVar3 = *(int *)(iVar1 + 0x6c);
    *(uint *)(iVar1 + 0x6c) = iVar3 + 1U & 7;
    puVar4[2] = iVar3 + 2;
    puVar4[0xe] = 0xff;
    puVar4[4] = 0;
    puVar4[5] = 0;
    puVar4[6] = 0;
    puVar4[7] = 0;
    puVar4[8] = 0;
    puVar4[9] = 0;
    puVar4[0xd] = 0;
    puVar4[0xf] = 0;
    puVar4[0xb] = 0;
    puVar4[0xc] = 0;
    puVar4[0x10] = 0;
    puVar5 = puVar4;
  }
  return puVar5;
}


