
void FUN_00021568(int param_1,int param_2)

{
  int *piVar1;
  int iVar2;
  uint uVar3;
  int *piVar4;
  int *piVar5;
  undefined4 *puVar6;
  int iVar7;
  char cVar9;
  undefined4 *puVar8;
  int iVar10;
  
  iVar7 = iRam017145f4;
  piVar1 = *(int **)(iRam017145f4 + -0x7ff8);
  iVar2 = *(int *)(*piVar1 + 0x182d4);
  iVar10 = *(int *)(iVar2 + 0x58);
  if ((((iVar10 != 2) && (iVar10 != 5)) && (iVar10 != 1)) && (*(int *)(iVar2 + 0x18) != 2)) {
    uVar3 = *(uint *)(*piVar1 + 0x182dc);
    if (((uVar3 & 2) == 0) && ((uVar3 & 1) == 0)) {
      if ((param_2 < 2) &&
         ((*(char *)(param_1 + 0x20) == '\0' || (*(char *)(param_1 + 7) != '\x02')))) {
        param_2 = 0;
        *(undefined1 *)(iVar2 + 0x2a) = 1;
      }
    }
    else if (param_2 != 3) {
      return;
    }
    piVar4 = *(int **)(iVar7 + -0x7ff4);
    uVar3 = *(uint *)(*piVar4 + *(int *)(*piVar4 + 0x24) * 0x5940 + 0x23ce8);
    if ((uVar3 < 600) || (699 < uVar3)) {
      func_0x001471ec();
    }
    puVar8 = *(undefined4 **)(param_1 + 0x130);
    if (puVar8 == (undefined4 *)0x0) {
      puVar8 = (undefined4 *)func_0x00b30fe4(0x5940);
      if (puVar8 != (undefined4 *)0x0) {
        *puVar8 = *(undefined4 *)(iVar7 + -0x7e1c);
        func_0x00adcb5c(puVar8 + 1);
        func_0x00a47ac4(puVar8 + 0x3c);
      }
      *(undefined4 **)(param_1 + 0x130) = puVar8;
    }
    func_0x009be1f4(*piVar4 + *(int *)(*piVar4 + 0x24) * 0x5940 + 0x1fb20,puVar8);
    if (*(int *)(*(int *)(*piVar1 + 0x182d4) + 0x58) == 0) {
      iVar2 = *piVar4;
      uVar3 = *(uint *)(iVar2 + *(int *)(iVar2 + 0x24) * 0x5940 + 0x23cf0);
      if (*(uint *)(iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0xa0) < uVar3) {
        if ((*(char *)(iVar2 + 0x20) != '\0') || (**(char **)(iVar7 + -0x7e58) != '\0')) {
          func_0x01399428(iVar2 + 8,0);
        }
        *(uint *)(iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0xa0) = uVar3;
        if ((*(char *)(iVar2 + 0x20) != '\0') || (**(char **)(iVar7 + -0x7e58) != '\0')) {
          func_0x01399448(iVar2 + 8);
        }
      }
      iVar2 = *piVar4;
      if (0x496 < *(uint *)(iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0xa0)) {
        if ((*(char *)(iVar2 + 0x20) != '\0') || (**(char **)(iVar7 + -0x7e58) != '\0')) {
          func_0x01399428(iVar2 + 8,0);
        }
        iVar10 = iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0x40;
        *(uint *)(iVar10 + 100) = *(uint *)(iVar10 + 100) | 1;
        if ((*(char *)(iVar2 + 0x20) != '\0') || (**(char **)(iVar7 + -0x7e58) != '\0')) {
          func_0x01399448(iVar2 + 8);
        }
      }
    }
    func_0x001445d4(*piVar4);
    if (((param_2 != 0) && (iVar2 = *(int *)(*(int *)(*piVar1 + 0x182d4) + 0x58), iVar2 != 3)) &&
       (iVar2 != 4)) {
      puVar8 = *(undefined4 **)(iVar7 + -0x7f6c);
      func_0x000bbca0(*puVar8);
      piVar5 = *(int **)(iVar7 + -0x7f78);
      puVar6 = *(undefined4 **)(iVar7 + -0x7f7c);
      cVar9 = func_0x00201908(*puVar6,*(undefined4 *)(*piVar5 + 0x1f98));
      if (((cVar9 != '\0') && (iVar2 = *(int *)(*(int *)(*piVar1 + 0x182d4) + 0x200), -1 < iVar2))
         && (cVar9 = func_0x00201908(*puVar6,iVar2), cVar9 != '\0')) {
        FUN_001426ec(*piVar4,*(undefined4 *)(*(int *)(*piVar1 + 0x182d4) + 0x200));
        iVar2 = *piVar4;
        func_0x00aed274(iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0x40);
        func_0x009be624(iVar2 + *(int *)(iVar2 + 0x24) * 0x5940 + 0x1fb20);
        FUN_001426f0(*piVar4);
      }
      func_0x000bbca0(*puVar8);
      cVar9 = func_0x00201908(*puVar6,*(undefined4 *)(*piVar5 + 0x1f98));
      if (cVar9 == '\0') {
        return;
      }
      iVar2 = *(int *)(*(int *)(*piVar1 + 0x182d4) + 0x204);
      if (iVar2 < 0) {
        return;
      }
      cVar9 = func_0x00201908(*puVar6,iVar2);
      if (cVar9 == '\0') {
        return;
      }
      FUN_001426ec(*piVar4,*(undefined4 *)(*(int *)(*piVar1 + 0x182d4) + 0x204));
      iVar2 = *piVar4;
      func_0x00aed274(iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0x40);
      func_0x009be624(iVar2 + *(int *)(iVar2 + 0x24) * 0x5940 + 0x1fb20);
      FUN_001426f0(*piVar4);
      return;
    }
    if ((*(char *)(param_1 + 0x20) != '\0') && (*(char *)(param_1 + 7) == '\x02')) {
      *(undefined1 *)(*(int *)(*piVar1 + 0x182d4) + 0x2a) = 0;
      uVar3 = *(uint *)(*piVar1 + 0x182dc);
      if ((((uVar3 & 2) == 0) &&
          (((((uVar3 & 1) == 0 && (iVar2 = *(int *)(*(int *)(*piVar1 + 0x182d4) + 0x58), iVar2 != 2)
             ) && (iVar2 != 5)) && (iVar2 != 1)))) &&
         ((uVar3 = *(uint *)(*piVar4 + *(int *)(*piVar4 + 0x24) * 0x5940 + 0x23ce8), uVar3 < 600 ||
          (699 < uVar3)))) {
        *(undefined4 *)(param_1 + 0xd4) = 2;
      }
    }
  }
  return;
}


