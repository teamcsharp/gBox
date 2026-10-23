
void FUN_009c3a64(int param_1,int param_2)

{
  undefined4 uVar1;
  int iVar2;
  undefined4 uVar3;
  undefined4 uVar4;
  undefined4 uVar5;
  int iVar6;
  undefined4 *puVar7;
  undefined4 uVar8;
  undefined4 uStack_540;
  undefined4 uStack_538;
  undefined4 uStack_508;
  undefined4 uStack_500;
  undefined4 uStack_4d0;
  undefined4 uStack_4c8;
  undefined4 uStack_498;
  undefined4 uStack_490;
  undefined4 uStack_460;
  undefined4 uStack_45c;
  undefined4 uStack_458;
  undefined4 uStack_428;
  undefined4 uStack_420;
  undefined4 uStack_3f0;
  undefined4 uStack_3e8;
  undefined4 uStack_3c8;
  undefined4 uStack_3c4;
  undefined4 uStack_3c0;
  undefined4 uStack_3bc;
  undefined4 uStack_3b8;
  undefined4 uStack_3b4;
  undefined4 uStack_3b0;
  undefined4 uStack_3ac;
  undefined4 uStack_3a8;
  undefined4 uStack_3a4;
  undefined4 uStack_3a0;
  undefined4 uStack_39c;
  undefined4 uStack_380;
  undefined4 uStack_37c;
  undefined4 uStack_378;
  undefined4 uStack_348;
  undefined4 uStack_340;
  undefined4 uStack_310;
  undefined4 uStack_308;
  undefined4 uStack_2d8;
  undefined4 uStack_2d0;
  undefined4 uStack_268;
  undefined4 uStack_264;
  undefined4 uStack_260;
  undefined4 uStack_1f8;
  undefined4 uStack_1f4;
  undefined4 uStack_1f0;
  undefined4 uStack_1c0;
  undefined4 uStack_1b8;
  undefined4 uStack_188;
  undefined4 uStack_180;
  undefined4 uStack_150;
  undefined4 uStack_148;
  undefined4 uStack_118;
  undefined4 uStack_110;
  undefined4 uStack_e0;
  undefined4 uStack_d8;
  undefined4 uStack_a8;
  undefined4 uStack_a0;
  
  iVar6 = iRam01714ecc;
  puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
  *puVar7 = *(undefined4 *)(iVar6 + -0x7fc8);
  puVar7[1] = 0x30000;
  puVar7[3] = param_1 + 0x1d;
  puVar7[2] = param_1;
  puVar7[5] = 0;
  puVar7[4] = uStack_a8;
  puVar7[6] = uStack_a0;
  puVar7[7] = 0;
  puVar7[9] = 0;
  puVar7[8] = 0;
  puVar7[10] = 0;
  puVar7[0xb] = 0;
  puVar7[0xc] = 0;
  puVar7[0xd] = 0;
  if (*(int *)(param_2 + 4) != 0) {
    *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
    puVar7[0xd] = *(undefined4 *)(param_2 + 4);
  }
  *(undefined4 **)(param_2 + 4) = puVar7;
  puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
  *puVar7 = *(undefined4 *)(iVar6 + -0x7fc4);
  puVar7[1] = 0x30000;
  puVar7[3] = param_1 + 0x1c;
  puVar7[2] = param_1;
  puVar7[5] = 0;
  puVar7[4] = uStack_3f0;
  puVar7[6] = uStack_3e8;
  puVar7[7] = 0;
  puVar7[9] = 0;
  puVar7[8] = 0;
  puVar7[10] = 0;
  puVar7[0xb] = 0;
  puVar7[0xc] = 0;
  puVar7[0xd] = 0;
  if (*(int *)(param_2 + 4) != 0) {
    *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
    puVar7[0xd] = *(undefined4 *)(param_2 + 4);
  }
  uVar8 = *(undefined4 *)(iVar6 + -0x7fc0);
  uVar1 = *(undefined4 *)(iVar6 + -0x7fbc);
  *(undefined4 **)(param_2 + 4) = puVar7;
  func_0x00b34ccc(&uStack_3c8,param_1,uVar8,uVar1,param_1 + 8,0,0);
  puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
  puVar7[1] = uStack_3c4;
  *puVar7 = uStack_3c8;
  puVar7[2] = uStack_3c0;
  puVar7[3] = uStack_3bc;
  puVar7[5] = uStack_3b4;
  puVar7[4] = uStack_3b8;
  puVar7[6] = uStack_3b0;
  puVar7[7] = uStack_3ac;
  puVar7[9] = uStack_3a4;
  puVar7[8] = uStack_3a8;
  puVar7[10] = uStack_3a0;
  puVar7[0xb] = uStack_39c;
  puVar7[0xc] = 0;
  puVar7[0xd] = 0;
  if (*(int *)(param_2 + 4) != 0) {
    *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
    puVar7[0xd] = *(undefined4 *)(param_2 + 4);
  }
  *(undefined4 **)(param_2 + 4) = puVar7;
  puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
  *puVar7 = *(undefined4 *)(iVar6 + -0x7fb8);
  puVar7[1] = 0x20000;
  puVar7[3] = param_1 + 0x10;
  puVar7[2] = param_1;
  puVar7[5] = 0;
  puVar7[4] = uStack_348;
  puVar7[6] = uStack_340;
  puVar7[7] = 0;
  puVar7[9] = 0;
  puVar7[8] = 0;
  puVar7[10] = 0;
  puVar7[0xb] = 0;
  puVar7[0xc] = 0;
  puVar7[0xd] = 0;
  if (*(int *)(param_2 + 4) != 0) {
    *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
    puVar7[0xd] = *(undefined4 *)(param_2 + 4);
  }
  *(undefined4 **)(param_2 + 4) = puVar7;
  puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
  *puVar7 = *(undefined4 *)(iVar6 + -0x7fb4);
  puVar7[1] = 0x60001;
  puVar7[3] = param_1 + 0x18;
  puVar7[2] = param_1;
  puVar7[5] = 0;
  puVar7[4] = uStack_428;
  puVar7[6] = uStack_420;
  puVar7[7] = 0;
  puVar7[9] = 0;
  puVar7[8] = 0;
  puVar7[10] = 0;
  puVar7[0xb] = 0;
  puVar7[0xc] = 0;
  puVar7[0xd] = 0;
  if (*(int *)(param_2 + 4) != 0) {
    *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
    puVar7[0xd] = *(undefined4 *)(param_2 + 4);
  }
  *(undefined4 **)(param_2 + 4) = puVar7;
  if (*(int *)(param_1 + 0xc) == 0) {
    uVar8 = *(undefined4 *)(iVar6 + -0x7f80);
  }
  else {
    puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
    *puVar7 = *(undefined4 *)(iVar6 + -0x7fb0);
    puVar7[1] = 0x190002;
    puVar7[3] = 0;
    puVar7[2] = param_1;
    puVar7[5] = uStack_45c;
    puVar7[4] = uStack_460;
    puVar7[6] = uStack_458;
    puVar7[7] = 0;
    puVar7[9] = 0;
    puVar7[8] = 0;
    puVar7[10] = 0;
    puVar7[0xb] = 0;
    puVar7[0xc] = 0;
    puVar7[0xd] = 0;
    if (*(int *)(param_2 + 4) != 0) {
      *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
      puVar7[0xd] = *(undefined4 *)(param_2 + 4);
    }
    *(undefined4 **)(param_2 + 4) = puVar7;
    uVar8 = *(undefined4 *)(param_1 + 0xc);
    puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
    *puVar7 = *(undefined4 *)(iVar6 + -0x7fac);
    puVar7[1] = 0x140001;
    puVar7[3] = uVar8;
    puVar7[2] = param_1;
    puVar7[5] = 0;
    puVar7[4] = uStack_540;
    puVar7[6] = uStack_538;
    puVar7[7] = 0;
    puVar7[9] = 0;
    puVar7[8] = 0;
    puVar7[10] = 0;
    puVar7[0xb] = 0;
    puVar7[0xd] = 0;
    puVar7[0xc] = 0;
    if (*(int *)(param_2 + 4) != 0) {
      *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
      puVar7[0xd] = *(undefined4 *)(param_2 + 4);
    }
    *(undefined4 **)(param_2 + 4) = puVar7;
    iVar2 = *(int *)(param_1 + 0xc);
    puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
    *puVar7 = *(undefined4 *)(iVar6 + -0x7fa8);
    puVar7[1] = 0x140001;
    puVar7[3] = iVar2 + 0x10;
    puVar7[2] = param_1;
    puVar7[5] = 0;
    puVar7[4] = uStack_508;
    puVar7[6] = uStack_500;
    puVar7[7] = 0;
    puVar7[9] = 0;
    puVar7[8] = 0;
    puVar7[10] = 0;
    puVar7[0xb] = 0;
    puVar7[0xd] = 0;
    puVar7[0xc] = 0;
    if (*(int *)(param_2 + 4) != 0) {
      *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
      puVar7[0xd] = *(undefined4 *)(param_2 + 4);
    }
    *(undefined4 **)(param_2 + 4) = puVar7;
    iVar2 = *(int *)(param_1 + 0xc);
    puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
    *puVar7 = *(undefined4 *)(iVar6 + -0x7fa4);
    puVar7[1] = 0xa0001;
    puVar7[3] = iVar2 + 0x28;
    puVar7[2] = param_1;
    puVar7[5] = 0;
    puVar7[4] = uStack_4d0;
    puVar7[6] = uStack_4c8;
    puVar7[7] = 0;
    puVar7[9] = 0;
    puVar7[8] = 0;
    puVar7[10] = 0;
    puVar7[0xb] = 0;
    puVar7[0xc] = 0;
    puVar7[0xd] = 0;
    if (*(int *)(param_2 + 4) != 0) {
      *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
      puVar7[0xd] = *(undefined4 *)(param_2 + 4);
    }
    *(undefined4 **)(param_2 + 4) = puVar7;
    iVar2 = *(int *)(param_1 + 0xc);
    puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
    *puVar7 = *(undefined4 *)(iVar6 + -0x7fa0);
    puVar7[1] = 0xa0001;
    puVar7[3] = iVar2 + 0x30;
    puVar7[2] = param_1;
    puVar7[5] = 0;
    puVar7[4] = uStack_498;
    puVar7[6] = uStack_490;
    puVar7[7] = 0;
    puVar7[9] = 0;
    puVar7[8] = 0;
    puVar7[10] = 0;
    puVar7[0xb] = 0;
    puVar7[0xc] = 0;
    puVar7[0xd] = 0;
    if (*(int *)(param_2 + 4) != 0) {
      *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
      puVar7[0xd] = *(undefined4 *)(param_2 + 4);
    }
    *(undefined4 **)(param_2 + 4) = puVar7;
    iVar2 = *(int *)(param_1 + 0xc);
    puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
    *puVar7 = *(undefined4 *)(iVar6 + -0x7f9c);
    puVar7[1] = 0xc0001;
    puVar7[3] = iVar2 + 0x34;
    puVar7[2] = param_1;
    puVar7[5] = 0;
    puVar7[4] = uStack_310;
    puVar7[6] = uStack_308;
    puVar7[7] = 0;
    puVar7[9] = 0;
    puVar7[8] = 0;
    puVar7[10] = 0;
    puVar7[0xb] = 0;
    puVar7[0xc] = 0;
    puVar7[0xd] = 0;
    if (*(int *)(param_2 + 4) != 0) {
      *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
      puVar7[0xd] = *(undefined4 *)(param_2 + 4);
    }
    *(undefined4 **)(param_2 + 4) = puVar7;
    iVar2 = *(int *)(param_1 + 0xc);
    puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
    *puVar7 = *(undefined4 *)(iVar6 + -0x7f98);
    puVar7[1] = 0xc0001;
    puVar7[3] = iVar2 + 0x38;
    puVar7[2] = param_1;
    puVar7[5] = 0;
    puVar7[4] = uStack_2d8;
    puVar7[6] = uStack_2d0;
    puVar7[7] = 0;
    puVar7[9] = 0;
    puVar7[8] = 0;
    puVar7[10] = 0;
    puVar7[0xb] = 0;
    puVar7[0xc] = 0;
    puVar7[0xd] = 0;
    if (*(int *)(param_2 + 4) != 0) {
      *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
      puVar7[0xd] = *(undefined4 *)(param_2 + 4);
    }
    *(undefined4 **)(param_2 + 4) = puVar7;
    iVar2 = *(int *)(param_1 + 0xc);
    puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
    *puVar7 = *(undefined4 *)(iVar6 + -0x7f94);
    puVar7[1] = 0x60001;
    puVar7[3] = iVar2 + 0x3c;
    puVar7[2] = param_1;
    puVar7[5] = 0;
    puVar7[4] = uStack_e0;
    puVar7[6] = uStack_d8;
    puVar7[7] = 0;
    puVar7[9] = 0;
    puVar7[8] = 0;
    puVar7[10] = 0;
    puVar7[0xb] = 0;
    puVar7[0xc] = 0;
    puVar7[0xd] = 0;
    if (*(int *)(param_2 + 4) != 0) {
      *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
      puVar7[0xd] = *(undefined4 *)(param_2 + 4);
    }
    *(undefined4 **)(param_2 + 4) = puVar7;
    iVar2 = *(int *)(param_1 + 0xc);
    puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
    *puVar7 = *(undefined4 *)(iVar6 + -0x7f90);
    puVar7[1] = 0x60001;
    puVar7[3] = iVar2 + 0x40;
    puVar7[2] = param_1;
    puVar7[5] = 0;
    puVar7[4] = uStack_118;
    puVar7[6] = uStack_110;
    puVar7[7] = 0;
    puVar7[9] = 0;
    puVar7[8] = 0;
    puVar7[10] = 0;
    puVar7[0xb] = 0;
    puVar7[0xc] = 0;
    puVar7[0xd] = 0;
    if (*(int *)(param_2 + 4) != 0) {
      *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
      puVar7[0xd] = *(undefined4 *)(param_2 + 4);
    }
    *(undefined4 **)(param_2 + 4) = puVar7;
    iVar2 = *(int *)(param_1 + 0xc);
    puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
    *puVar7 = *(undefined4 *)(iVar6 + -0x7f8c);
    puVar7[1] = 0x60001;
    puVar7[3] = iVar2 + 0x44;
    puVar7[2] = param_1;
    puVar7[5] = 0;
    puVar7[4] = uStack_150;
    puVar7[6] = uStack_148;
    puVar7[7] = 0;
    puVar7[9] = 0;
    puVar7[8] = 0;
    puVar7[10] = 0;
    puVar7[0xb] = 0;
    puVar7[0xc] = 0;
    puVar7[0xd] = 0;
    if (*(int *)(param_2 + 4) != 0) {
      *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
      puVar7[0xd] = *(undefined4 *)(param_2 + 4);
    }
    *(undefined4 **)(param_2 + 4) = puVar7;
    iVar2 = *(int *)(param_1 + 0xc);
    puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
    *puVar7 = *(undefined4 *)(iVar6 + -0x7f88);
    puVar7[1] = 0x30001;
    puVar7[3] = iVar2 + 0x48;
    puVar7[2] = param_1;
    puVar7[5] = 0;
    puVar7[4] = uStack_188;
    puVar7[6] = uStack_180;
    puVar7[7] = 0;
    puVar7[9] = 0;
    puVar7[8] = 0;
    puVar7[10] = 0;
    puVar7[0xb] = 0;
    puVar7[0xc] = 0;
    puVar7[0xd] = 0;
    if (*(int *)(param_2 + 4) != 0) {
      *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
      puVar7[0xd] = *(undefined4 *)(param_2 + 4);
    }
    *(undefined4 **)(param_2 + 4) = puVar7;
    iVar2 = *(int *)(param_1 + 0xc);
    puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
    *puVar7 = *(undefined4 *)(iVar6 + -0x7f84);
    puVar7[1] = 0x40001;
    puVar7[3] = iVar2 + 0x49;
    puVar7[2] = param_1;
    puVar7[5] = 0;
    puVar7[4] = uStack_1c0;
    puVar7[6] = uStack_1b8;
    puVar7[7] = 0;
    puVar7[9] = 0;
    puVar7[8] = 0;
    puVar7[10] = 0;
    puVar7[0xb] = 0;
    puVar7[0xc] = 0;
    puVar7[0xd] = 0;
    if (*(int *)(param_2 + 4) != 0) {
      *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
      puVar7[0xd] = *(undefined4 *)(param_2 + 4);
    }
    *(undefined4 **)(param_2 + 4) = puVar7;
    puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
    uVar8 = *(undefined4 *)(iVar6 + -0x7f80);
    puVar7[1] = 0x1f0002;
    puVar7[3] = 0;
    *puVar7 = uVar8;
    puVar7[2] = param_1;
    puVar7[5] = uStack_1f4;
    puVar7[4] = uStack_1f8;
    puVar7[6] = uStack_1f0;
    puVar7[7] = 0;
    puVar7[9] = 0;
    puVar7[8] = 0;
    puVar7[10] = 0;
    puVar7[0xb] = 0;
    puVar7[0xd] = 0;
    puVar7[0xc] = 0;
    if (*(int *)(param_2 + 4) != 0) {
      *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
      puVar7[0xd] = *(undefined4 *)(param_2 + 4);
    }
    *(undefined4 **)(param_2 + 4) = puVar7;
  }
  uVar1 = *(undefined4 *)(iVar6 + -0x7f7c);
  uVar3 = *(undefined4 *)(iVar6 + -0x7f78);
  puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
  *puVar7 = *(undefined4 *)(iVar6 + -0x7f74);
  puVar7[1] = 0x60081;
  puVar7[3] = uVar1;
  puVar7[2] = param_1;
  puVar7[5] = 0;
  puVar7[4] = 0;
  puVar7[6] = 0;
  puVar7[7] = uVar3;
  puVar7[9] = 0;
  puVar7[8] = 0;
  puVar7[10] = 0;
  puVar7[0xb] = 0;
  puVar7[0xc] = 0;
  puVar7[0xd] = 0;
  if (*(int *)(param_2 + 4) != 0) {
    *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
    puVar7[0xd] = *(undefined4 *)(param_2 + 4);
  }
  *(undefined4 **)(param_2 + 4) = puVar7;
  puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
  *puVar7 = *(undefined4 *)(iVar6 + -0x7f70);
  puVar7[1] = 0x190006;
  puVar7[3] = 0;
  puVar7[2] = param_1;
  puVar7[5] = uStack_264;
  puVar7[4] = uStack_268;
  puVar7[6] = uStack_260;
  puVar7[7] = 0;
  puVar7[9] = 0;
  puVar7[8] = 0;
  puVar7[10] = 0;
  puVar7[0xb] = 0;
  puVar7[0xc] = 0;
  puVar7[0xd] = 0;
  if (*(int *)(param_2 + 4) != 0) {
    *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
    puVar7[0xd] = *(undefined4 *)(param_2 + 4);
  }
  uVar4 = *(undefined4 *)(iVar6 + -0x7f6c);
  uVar5 = *(undefined4 *)(iVar6 + -0x7f68);
  *(undefined4 **)(param_2 + 4) = puVar7;
  puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
  *puVar7 = *(undefined4 *)(iVar6 + -0x7f64);
  puVar7[1] = 0x200a1;
  puVar7[3] = uVar4;
  puVar7[2] = param_1;
  puVar7[5] = uVar1;
  puVar7[4] = 0;
  puVar7[6] = 0;
  puVar7[7] = uVar5;
  puVar7[9] = uVar3;
  puVar7[8] = 0;
  puVar7[10] = 0;
  puVar7[0xb] = 0;
  puVar7[0xc] = 0;
  puVar7[0xd] = 0;
  if (*(int *)(param_2 + 4) != 0) {
    *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
    puVar7[0xd] = *(undefined4 *)(param_2 + 4);
  }
  *(undefined4 **)(param_2 + 4) = puVar7;
  puVar7 = (undefined4 *)func_0x00b3f6d4(param_2);
  *puVar7 = uVar8;
  puVar7[1] = 0x1f0002;
  puVar7[2] = param_1;
  puVar7[3] = 0;
  puVar7[5] = uStack_37c;
  puVar7[4] = uStack_380;
  puVar7[6] = uStack_378;
  puVar7[7] = 0;
  puVar7[9] = 0;
  puVar7[8] = 0;
  puVar7[10] = 0;
  puVar7[0xb] = 0;
  puVar7[0xc] = 0;
  puVar7[0xd] = 0;
  if (*(int *)(param_2 + 4) != 0) {
    *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar7;
    puVar7[0xd] = *(undefined4 *)(param_2 + 4);
  }
  *(undefined4 **)(param_2 + 4) = puVar7;
  return;
}


