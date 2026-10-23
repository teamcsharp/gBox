
void FUN_000f1710(undefined8 param_1,int param_2,int param_3)

{
  byte bVar1;
  ushort uVar2;
  ulonglong uVar3;
  int iVar4;
  int iVar5;
  undefined4 uVar6;
  int *piVar7;
  int iVar8;
  
  iVar5 = iRam017147ec;
  bVar1 = *(byte *)(param_3 + 3);
  if (bVar1 == 2) {
    if ((uint)*(byte *)(param_3 + 6) !=
        *(uint *)(*(int *)(**(int **)(iRam017147ec + -0x7ffc) + 0x182d4) + 0x2e8)) {
      return;
    }
    uVar3 = (ulonglong)*(ushort *)(param_3 + 4);
    iVar5 = (int)(uVar3 & 0xf000);
    if (iVar5 == 0x2000) {
      iVar5 = (int)((uVar3 & 0xfff) << 4);
      piVar7 = *(int **)(iRam017147ec + -0x7ff8);
      iVar4 = (int)((uVar3 & 0xfff) << 2);
    }
    else {
      if ((uVar3 & 0xf000) < 0x2001) {
        if (iVar5 != 0x1000) {
          return;
        }
        iVar5 = func_0x001a617c(**(undefined4 **)(iRam017147ec + -0x7fe8),
                                *(ushort *)(param_3 + 4) & 0xfff);
        goto LAB_000f19c0;
      }
      if (iVar5 == 0x3000) {
        iVar5 = (int)((uVar3 & 0xfff) << 4);
        piVar7 = *(int **)(iRam017147ec + -0x7ff4);
        iVar4 = (int)((uVar3 & 0xfff) << 2);
      }
      else {
        if (iVar5 != 0x4000) {
          return;
        }
        iVar5 = (int)((uVar3 & 0xfff) << 4);
        piVar7 = *(int **)(iRam017147ec + -0x7ff0);
        iVar4 = (int)((uVar3 & 0xfff) << 2);
      }
    }
    iVar5 = *(int *)((iVar5 - iVar4) + *(int *)(*piVar7 + 0x84) + 8);
LAB_000f19c0:
    if (iVar5 == 0) {
      return;
    }
    *(undefined1 *)(iVar5 + 0x1930) = 0;
    *(uint *)(iVar5 + 0x1934) = (uint)*(byte *)(param_3 + 7);
    return;
  }
  if (bVar1 < 3) {
    if (bVar1 != 1) {
      return;
    }
    if (*(int *)(*(int *)(**(int **)(iRam017147ec + -0x7ffc) + 0x182d4) + 0x2e8) == param_2) {
      return;
    }
    uVar3 = (ulonglong)*(ushort *)(param_3 + 4);
    uVar2 = *(ushort *)(param_3 + 4) & 0xf000;
    if (uVar2 == 0x3000) {
      iVar5 = (int)((uVar3 & 0xfff) << 4);
      piVar7 = *(int **)(iRam017147ec + -0x7ff4);
      iVar4 = (int)((uVar3 & 0xfff) << 2);
    }
    else if (uVar2 == 0x4000) {
      iVar5 = (int)((uVar3 & 0xfff) << 4);
      piVar7 = *(int **)(iRam017147ec + -0x7ff0);
      iVar4 = (int)((uVar3 & 0xfff) << 2);
    }
    else {
      if (uVar2 != 0x2000) {
        return;
      }
      iVar5 = (int)((uVar3 & 0xfff) << 4);
      piVar7 = *(int **)(iRam017147ec + -0x7ff8);
      iVar4 = (int)((uVar3 & 0xfff) << 2);
    }
    *(undefined1 *)((iVar5 - iVar4) + *(int *)(*piVar7 + 0x84) + 3) = *(undefined1 *)(param_3 + 6);
    return;
  }
  if (bVar1 == 3) {
    if (*(int *)(*(int *)(**(int **)(iRam017147ec + -0x7ffc) + 0x182d4) + 0x2e8) == param_2) {
      return;
    }
    if ((*(ushort *)(param_3 + 4) & 0xf000) != 0x1000) {
      return;
    }
    func_0x001a617c(**(undefined4 **)(iRam017147ec + -0x7fe8),*(ushort *)(param_3 + 4) & 0xfff);
    return;
  }
  if (bVar1 != 4) {
    return;
  }
  if (*(int *)(*(int *)(**(int **)(iRam017147ec + -0x7ffc) + 0x182d4) + 0x2e8) == param_2) {
    return;
  }
  uVar3 = (ulonglong)*(ushort *)(param_3 + 4);
  iVar4 = (int)(uVar3 & 0xf000);
  if (iVar4 == 0x2000) {
    iVar4 = (int)((uVar3 & 0xfff) << 4);
    piVar7 = *(int **)(iRam017147ec + -0x7ff8);
    iVar8 = (int)((uVar3 & 0xfff) << 2);
LAB_000f19fc:
    iVar4 = *(int *)((iVar4 - iVar8) + *(int *)(*piVar7 + 0x84) + 8);
  }
  else {
    if (0x2000 < (uVar3 & 0xf000)) {
      if (iVar4 == 0x3000) {
        iVar4 = (int)((uVar3 & 0xfff) << 4);
        piVar7 = *(int **)(iRam017147ec + -0x7ff4);
        iVar8 = (int)((uVar3 & 0xfff) << 2);
      }
      else {
        if (iVar4 != 0x4000) {
          return;
        }
        iVar4 = (int)((uVar3 & 0xfff) << 4);
        piVar7 = *(int **)(iRam017147ec + -0x7ff0);
        iVar8 = (int)((uVar3 & 0xfff) << 2);
      }
      goto LAB_000f19fc;
    }
    if (iVar4 != 0x1000) {
      return;
    }
    iVar4 = func_0x001a617c(**(undefined4 **)(iRam017147ec + -0x7fe8),
                            *(ushort *)(param_3 + 4) & 0xfff);
  }
  if (iVar4 == 0) {
    return;
  }
  iVar8 = 0;
  if (*(char *)(iVar4 + 0x1990) != '\0') {
    iVar8 = *(int *)(iVar4 + 0x19b0);
  }
  *(undefined4 *)(iVar4 + 0x19a0) = *(undefined4 *)(param_3 + 0x18);
  *(undefined4 *)(iVar4 + 0x19a4) = *(undefined4 *)(param_3 + 0x1c);
  *(undefined4 *)(iVar4 + 0x19a8) = *(undefined4 *)(param_3 + 0x20);
  *(int *)(iVar4 + 0x19b0) = iVar8 + *(int *)(param_3 + 0x24);
  *(undefined1 *)(iVar4 + 0x19b4) = *(undefined1 *)(param_3 + 0x28);
  *(undefined1 *)(iVar4 + 0x19b5) = *(undefined1 *)(param_3 + 0x29);
  *(undefined2 *)(iVar4 + 0x19b6) = *(undefined2 *)(param_3 + 0x2a);
  *(undefined4 *)(iVar4 + 0x19b8) = *(undefined4 *)(param_3 + 0x2c);
  uVar3 = (ulonglong)*(ushort *)(param_3 + 6);
  iVar8 = (int)(uVar3 & 0xf000);
  if (iVar8 == 0x2000) {
    iVar8 = (int)((uVar3 & 0xfff) << 4);
    piVar7 = *(int **)(iVar5 + -0x7ff8);
    iVar5 = (int)((uVar3 & 0xfff) << 2);
  }
  else {
    if ((uVar3 & 0xf000) < 0x2001) {
      if (iVar8 == 0x1000) {
        uVar6 = func_0x001a617c(**(undefined4 **)(iVar5 + -0x7fe8),*(ushort *)(param_3 + 6) & 0xfff)
        ;
        goto LAB_000f183c;
      }
LAB_000f1838:
      uVar6 = 0;
      goto LAB_000f183c;
    }
    if (iVar8 == 0x3000) {
      iVar8 = (int)((uVar3 & 0xfff) << 4);
      piVar7 = *(int **)(iVar5 + -0x7ff4);
      iVar5 = (int)((uVar3 & 0xfff) << 2);
    }
    else {
      if (iVar8 != 0x4000) goto LAB_000f1838;
      iVar8 = (int)((uVar3 & 0xfff) << 4);
      piVar7 = *(int **)(iVar5 + -0x7ff0);
      iVar5 = (int)((uVar3 & 0xfff) << 2);
    }
  }
  uVar6 = *(undefined4 *)((iVar8 - iVar5) + *(int *)(*piVar7 + 0x84) + 8);
LAB_000f183c:
  *(undefined4 *)(iVar4 + 0x19bc) = uVar6;
  *(char *)(iVar4 + 0x1990) = '\x01';
  return;
}


