
void FUN_000bfe60(int param_1)

{
  byte bVar1;
  int *piVar2;
  int *piVar3;
  int *piVar4;
  int iVar5;
  undefined8 uVar6;
  int iVar7;
  uint uVar8;
  undefined4 uVar9;
  int iVar10;
  int iVar11;
  uint uVar12;
  int *piVar13;
  int iStack_a8;
  int iStack_a4;
  
  iVar5 = iRam017147d4;
  piVar2 = *(int **)(iRam017147d4 + -0x7ff4);
  iVar10 = *piVar2;
  if ((*(char *)(iVar10 + 0x20) == '\0') && (**(char **)(iRam017147d4 + -0x7fb4) == '\0')) {
    iVar10 = *(int *)(param_1 + 0x3054);
  }
  else {
    func_0x01399428(iVar10 + 8,0);
    iVar10 = *(int *)(param_1 + 0x3054);
  }
  if (iVar10 != 0) {
    if (iVar10 == 1) {
      func_0x000bd878(param_1);
      piVar13 = *(int **)(iVar5 + -0x7fe0);
      uVar6 = *(undefined8 *)(*piVar13 + 0x6e998);
      iStack_a8 = (int)((ulonglong)uVar6 >> 0x20);
      iStack_a4 = (int)uVar6;
      if (iStack_a4 * 0x500 < iStack_a8 * 0x2d0) {
        iVar11 = 0;
        iVar10 = (iStack_a4 * 0x500) / 0x2d0;
        uVar12 = iStack_a8 - iVar10;
        iVar7 = ((int)uVar12 >> 1) + (uint)((int)uVar12 < 0 && (uVar12 & 1) != 0);
        iStack_a8 = iVar10;
        iVar10 = iStack_a4;
      }
      else {
        iVar7 = 0;
        iVar10 = (iStack_a8 * 0x2d0) / 0x500;
        uVar12 = iStack_a4 - iVar10;
        iVar11 = ((int)uVar12 >> 1) + (uint)((int)uVar12 < 0 && (uVar12 & 1) != 0);
      }
      piVar3 = *(int **)(iVar5 + -0x7ffc);
      *(int *)(param_1 + 0x3120) = iVar7 + iStack_a8;
      *(int *)(param_1 + 0x3124) = iVar10 + iVar11;
      *(int *)(param_1 + 0x311c) = iVar11;
      *(int *)(param_1 + 0x3118) = iVar7;
      *(undefined4 *)(param_1 + 0x3064) = 1;
      *(undefined4 *)(param_1 + 0x3068) = 0;
      uVar12 = func_0x009c0a2c(*(undefined4 *)(*piVar3 + 0x182d4));
      if (uVar12 < 8) {
                    /* WARNING: Could not recover jumptable at 0x000c01fc. Too many branches */
                    /* WARNING: Treating indirect jump as call */
        (*(code *)(*(int *)(uVar12 * 4 + *(int *)(iVar5 + -0x7f7c)) + *(int *)(iVar5 + -0x7f7c)))();
        return;
      }
      *(undefined4 *)(param_1 + 0x301c) = 1;
      *(undefined4 *)(param_1 + 0x3020) = 0;
      func_0x000bd384(param_1,0,0);
      iVar10 = *piVar3;
      if ((*(char *)(iVar10 + 0x20) != '\0') || (**(char **)(iVar5 + -0x7fb4) != '\0')) {
        func_0x01399428(iVar10 + 8,0);
      }
      *(uint *)(iVar10 + 0x182e0) = *(uint *)(iVar10 + 0x182e0) & 0xfffdffff;
      if ((*(char *)(iVar10 + 0x20) == '\0') && (**(char **)(iVar5 + -0x7fb4) == '\0')) {
        piVar4 = *(int **)(iVar5 + -0x7fc8);
      }
      else {
        func_0x01399448(iVar10 + 8);
        piVar4 = *(int **)(iVar5 + -0x7fc8);
      }
      uVar9 = func_0x009c0a2c(*(undefined4 *)(*piVar3 + 0x182d4));
      *(undefined4 *)(param_1 + 0x3018) = uVar9;
      iVar10 = func_0x009c0a38(*(undefined4 *)(*piVar3 + 0x182d4),0);
      *(int *)(param_1 + 0x3030) = iVar10;
      if ((-1 < iVar10) &&
         (iVar10 = func_0x001a617c(**(undefined4 **)(iVar5 + -0x7fb0),iVar10), iVar10 != 0)) {
        func_0x0083cd24(iVar10,*(undefined4 *)(param_1 + *(int *)(param_1 + 0x3030) * 4 + 0x3040));
      }
      iVar10 = func_0x009c0a38(*(undefined4 *)(*piVar3 + 0x182d4),1);
      *(int *)(param_1 + 0x3034) = iVar10;
      if ((-1 < iVar10) &&
         (iVar10 = func_0x001a617c(**(undefined4 **)(iVar5 + -0x7fb0),iVar10), iVar10 != 0)) {
        func_0x0083cd24(iVar10,*(undefined4 *)(param_1 + *(int *)(param_1 + 0x3034) * 4 + 0x3040));
      }
      iVar10 = func_0x009c0a38(*(undefined4 *)(*piVar3 + 0x182d4),2);
      *(int *)(param_1 + 0x3038) = iVar10;
      if ((-1 < iVar10) &&
         (iVar10 = func_0x001a617c(**(undefined4 **)(iVar5 + -0x7fb0),iVar10), iVar10 != 0)) {
        func_0x0083cd24(iVar10,*(undefined4 *)(param_1 + *(int *)(param_1 + 0x3038) * 4 + 0x3040));
      }
      iVar10 = func_0x009c0a38(*(undefined4 *)(*piVar3 + 0x182d4),3);
      *(int *)(param_1 + 0x303c) = iVar10;
      if ((-1 < iVar10) &&
         (iVar10 = func_0x001a617c(**(undefined4 **)(iVar5 + -0x7fb0),iVar10), iVar10 != 0)) {
        func_0x0083cd24(iVar10,*(undefined4 *)(param_1 + *(int *)(param_1 + 0x303c) * 4 + 0x3040));
      }
      if (*(int *)(param_1 + 0x30cc) != 0) {
        iVar10 = func_0x009c0a2c(*(undefined4 *)(*piVar3 + 0x182d4));
        if (iVar10 == 7) {
          func_0x0028d240(*(undefined4 *)(param_1 + 0x30cc));
        }
        else {
          func_0x0028d508(*(undefined4 *)(param_1 + 0x30cc));
        }
      }
      func_0x00116e34(*piVar13,*(undefined4 *)(param_1 + 0x301c));
      piVar13 = *(int **)(*piVar4 + 0x150);
      if (piVar13 != (int *)0x0) {
        iVar10 = *(int *)(iVar5 + -0x7f60);
        do {
          iVar11 = (*(code *)**(undefined4 **)(*piVar13 + 0x14))(piVar13);
          iVar7 = *(int *)(iVar11 + 4);
          while (iVar7 != *(int *)(iVar10 + 4)) {
            iVar11 = *(int *)(iVar11 + 0x10);
            if (iVar11 == 0) goto LAB_000c050c;
            iVar7 = *(int *)(iVar11 + 4);
          }
          if (1 < *(int *)(param_1 + 0x301c)) {
            func_0x0082ab50(piVar13,1);
          }
LAB_000c050c:
          piVar13 = (int *)piVar13[2];
        } while (piVar13 != (int *)0x0);
      }
      if ((*(uint *)(*piVar3 + 0x182e0) & 0x20000) != 0) {
        *(undefined1 *)(**(int **)(iVar5 + -0x7ff8) + 0xd8) = 1;
      }
      *(undefined1 *)(param_1 + 0x305c) = 0;
      *(undefined4 *)(param_1 + 0x3054) = 0;
    }
    goto LAB_000bfef8;
  }
  bVar1 = *(byte *)(param_1 + 0x305c);
  uVar12 = (uint)bVar1;
  if (*(int *)(param_1 + 0x3060) == 0) {
    piVar13 = *(int **)(iVar5 + -0x7ffc);
    iVar10 = *(int *)(param_1 + 0x3018);
    iVar7 = func_0x009c0a2c(*(undefined4 *)(*piVar13 + 0x182d4));
    if ((iVar10 == iVar7) && (bVar1 == 0)) {
      uVar12 = *(uint *)(param_1 + 0x3030);
      uVar8 = func_0x009c0a38(*(undefined4 *)(*piVar13 + 0x182d4),0);
      uVar8 = uVar8 ^ uVar12;
      iVar10 = *(int *)(param_1 + 0x3034);
      uVar12 = (int)uVar8 >> 0x1f;
      uVar12 = uVar12 - (uVar12 ^ uVar8) >> 0x1f;
      iVar7 = func_0x009c0a38(*(undefined4 *)(*piVar13 + 0x182d4),1);
      if (iVar10 != iVar7) {
        uVar12 = 1;
      }
      iVar10 = *(int *)(param_1 + 0x3038);
      iVar7 = func_0x009c0a38(*(undefined4 *)(*piVar13 + 0x182d4),2);
      if (iVar10 != iVar7) {
        uVar12 = 1;
      }
      iVar10 = *(int *)(param_1 + 0x303c);
      iVar7 = func_0x009c0a38(*(undefined4 *)(*piVar13 + 0x182d4),3);
      if (iVar10 != iVar7) {
        uVar12 = 1;
      }
      goto LAB_000bffb0;
    }
  }
  else {
LAB_000bffb0:
    if (uVar12 == 0) goto LAB_000bfef8;
    piVar13 = *(int **)(iVar5 + -0x7ffc);
  }
  iVar10 = *piVar13;
  if ((*(char *)(iVar10 + 0x20) != '\0') || (**(char **)(iVar5 + -0x7fb4) != '\0')) {
    func_0x01399428(iVar10 + 8,0);
  }
  *(uint *)(iVar10 + 0x182e0) = *(uint *)(iVar10 + 0x182e0) | 0x20000;
  if ((*(char *)(iVar10 + 0x20) != '\0') || (**(char **)(iVar5 + -0x7fb4) != '\0')) {
    func_0x01399448(iVar10 + 8);
  }
  *(int *)(param_1 + 0x3054) = *(int *)(param_1 + 0x3054) + 1;
LAB_000bfef8:
  iVar10 = *piVar2;
  if ((*(char *)(iVar10 + 0x20) != '\0') || (**(char **)(iVar5 + -0x7fb4) != '\0')) {
    func_0x01399448(iVar10 + 8);
  }
  return;
}


