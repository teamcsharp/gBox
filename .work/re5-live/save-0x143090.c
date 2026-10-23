
/* WARNING: Type propagation algorithm not settling */

uint FUN_00143090(int param_1)

{
  undefined4 *puVar1;
  undefined4 uVar2;
  uint uVar3;
  uint uVar4;
  uint uVar5;
  int iVar6;
  int iVar7;
  int iVar8;
  
  if (*(int *)(*(int *)(**(int **)(iRam0171482c + -0x7ffc) + 0x182d4) + 0x58) == 2) {
    uVar4 = *(uint *)(param_1 + *(int *)(param_1 + 0x24) * 0x7eb8 + 0x108);
    uVar3 = (uVar4 & 2) + 9;
    if ((uVar4 & 4) != 0) {
      uVar3 = uVar3 | 4;
    }
    if ((uVar4 & 8) != 0) {
      uVar3 = uVar3 | 8;
    }
    if ((uVar4 & 0x10) != 0) {
      uVar3 = uVar3 | 0x10;
    }
    if ((uVar4 & 0x20) != 0) {
      uVar3 = uVar3 | 0x20;
    }
    if ((uVar4 & 0x40) != 0) {
      uVar3 = uVar3 | 0x40;
    }
    if ((uVar4 & 0x80) != 0) {
      uVar3 = uVar3 | 0x80;
    }
    if ((uVar4 & 0x100) != 0) {
      uVar3 = uVar3 | 0x100;
    }
    if ((uVar4 & 0x200) != 0) {
      return uVar3 | 0x200;
    }
  }
  else {
    puVar1 = *(undefined4 **)(iRam0171482c + -0x7fc4);
    uVar2 = *puVar1;
    uVar3 = func_0x00201ba8(uVar2,1);
    uVar4 = func_0x00201ba8(uVar2,6);
    uVar5 = func_0x00201ba8(uVar2,7);
    uVar2 = *puVar1;
    uVar5 = uVar3 | uVar4 | uVar5;
    uVar3 = (int)uVar5 >> 0x1f;
    iVar6 = func_0x00201ba8(uVar2,2);
    uVar3 = ((int)(((uVar3 ^ uVar5) - uVar3) + -1) >> 0x1f & 0xffffffb8U) + 0x48;
    iVar7 = func_0x00201ba8(uVar2,6);
    iVar8 = func_0x00201ba8(uVar2,7);
    if ((iVar6 != 0 || iVar7 != 0) || iVar8 != 0) {
      uVar3 = uVar3 | 0x84;
    }
    uVar2 = *puVar1;
    iVar6 = func_0x00201ba8(uVar2,3);
    iVar7 = func_0x00201ba8(uVar2,6);
    iVar8 = func_0x00201ba8(uVar2,7);
    if ((iVar6 != 0 || iVar7 != 0) || iVar8 != 0) {
      uVar3 = uVar3 | 0x12;
    }
    uVar2 = *puVar1;
    iVar6 = func_0x00201ba8(uVar2,4);
    iVar7 = func_0x00201ba8(uVar2,6);
    iVar8 = func_0x00201ba8(uVar2,7);
    if ((iVar6 != 0 || iVar7 != 0) || iVar8 != 0) {
      return uVar3 | 0x21;
    }
  }
  return uVar3;
}


