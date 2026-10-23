
void FUN_00021978(void)

{
  int *piVar1;
  uint uVar2;
  int iVar3;
  int *piVar4;
  undefined4 *puVar5;
  char cVar7;
  undefined4 *puVar6;
  int iVar8;
  uint in_r9;
  int in_r11;
  int *unaff_r27;
  int unaff_r28;
  int unaff_r30;
  int unaff_r31;
  
  if ((in_r9 & 1) == 0) {
    if ((unaff_r31 < 2) &&
       ((*(char *)(unaff_r28 + 0x20) == '\0' || (*(char *)(unaff_r28 + 7) != '\x02')))) {
      unaff_r31 = 0;
      *(undefined1 *)(in_r11 + 0x2a) = 1;
    }
  }
  else if (unaff_r31 != 3) {
    return;
  }
  piVar1 = *(int **)(unaff_r30 + -0x7ff4);
  uVar2 = *(uint *)(*piVar1 + *(int *)(*piVar1 + 0x24) * 0x5940 + 0x23ce8);
  if ((uVar2 < 600) || (699 < uVar2)) {
    func_0x001471ec();
  }
  puVar6 = *(undefined4 **)(unaff_r28 + 0x130);
  if (puVar6 == (undefined4 *)0x0) {
    puVar6 = (undefined4 *)func_0x00b30fe4(0x5940);
    if (puVar6 != (undefined4 *)0x0) {
      *puVar6 = *(undefined4 *)(unaff_r30 + -0x7e1c);
      func_0x00adcb5c(puVar6 + 1);
      func_0x00a47ac4(puVar6 + 0x3c);
    }
    *(undefined4 **)(unaff_r28 + 0x130) = puVar6;
  }
  func_0x009be1f4(*piVar1 + *(int *)(*piVar1 + 0x24) * 0x5940 + 0x1fb20,puVar6);
  if (*(int *)(*(int *)(*unaff_r27 + 0x182d4) + 0x58) == 0) {
    iVar3 = *piVar1;
    uVar2 = *(uint *)(iVar3 + *(int *)(iVar3 + 0x24) * 0x5940 + 0x23cf0);
    if (*(uint *)(iVar3 + *(int *)(iVar3 + 0x24) * 0x7eb8 + 0xa0) < uVar2) {
      if ((*(char *)(iVar3 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
        func_0x01399428(iVar3 + 8,0);
      }
      *(uint *)(iVar3 + *(int *)(iVar3 + 0x24) * 0x7eb8 + 0xa0) = uVar2;
      if ((*(char *)(iVar3 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
        func_0x01399448(iVar3 + 8);
      }
    }
    iVar3 = *piVar1;
    if (0x496 < *(uint *)(iVar3 + *(int *)(iVar3 + 0x24) * 0x7eb8 + 0xa0)) {
      if ((*(char *)(iVar3 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
        func_0x01399428(iVar3 + 8,0);
      }
      iVar8 = iVar3 + *(int *)(iVar3 + 0x24) * 0x7eb8 + 0x40;
      *(uint *)(iVar8 + 100) = *(uint *)(iVar8 + 100) | 1;
      if ((*(char *)(iVar3 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
        func_0x01399448(iVar3 + 8);
      }
    }
  }
  func_0x001445d4(*piVar1);
  if (((unaff_r31 == 0) || (iVar3 = *(int *)(*(int *)(*unaff_r27 + 0x182d4) + 0x58), iVar3 == 3)) ||
     (iVar3 == 4)) {
    if ((*(char *)(unaff_r28 + 0x20) != '\0') && (*(char *)(unaff_r28 + 7) == '\x02')) {
      *(undefined1 *)(*(int *)(*unaff_r27 + 0x182d4) + 0x2a) = 0;
      uVar2 = *(uint *)(*unaff_r27 + 0x182dc);
      if ((((uVar2 & 2) == 0) &&
          (((((uVar2 & 1) == 0 &&
             (iVar3 = *(int *)(*(int *)(*unaff_r27 + 0x182d4) + 0x58), iVar3 != 2)) && (iVar3 != 5))
           && (iVar3 != 1)))) &&
         ((uVar2 = *(uint *)(*piVar1 + *(int *)(*piVar1 + 0x24) * 0x5940 + 0x23ce8), uVar2 < 600 ||
          (699 < uVar2)))) {
        *(undefined4 *)(unaff_r28 + 0xd4) = 2;
      }
    }
    return;
  }
  puVar6 = *(undefined4 **)(unaff_r30 + -0x7f6c);
  func_0x000bbca0(*puVar6);
  piVar4 = *(int **)(unaff_r30 + -0x7f78);
  puVar5 = *(undefined4 **)(unaff_r30 + -0x7f7c);
  cVar7 = func_0x00201908(*puVar5,*(undefined4 *)(*piVar4 + 0x1f98));
  if (((cVar7 != '\0') && (iVar3 = *(int *)(*(int *)(*unaff_r27 + 0x182d4) + 0x200), -1 < iVar3)) &&
     (cVar7 = func_0x00201908(*puVar5,iVar3), cVar7 != '\0')) {
    FUN_001426ec(*piVar1,*(undefined4 *)(*(int *)(*unaff_r27 + 0x182d4) + 0x200));
    iVar3 = *piVar1;
    func_0x00aed274(iVar3 + *(int *)(iVar3 + 0x24) * 0x7eb8 + 0x40);
    func_0x009be624(iVar3 + *(int *)(iVar3 + 0x24) * 0x5940 + 0x1fb20);
    FUN_001426f0(*piVar1);
  }
  func_0x000bbca0(*puVar6);
  cVar7 = func_0x00201908(*puVar5,*(undefined4 *)(*piVar4 + 0x1f98));
  if (cVar7 == '\0') {
    return;
  }
  iVar3 = *(int *)(*(int *)(*unaff_r27 + 0x182d4) + 0x204);
  if (iVar3 < 0) {
    return;
  }
  cVar7 = func_0x00201908(*puVar5,iVar3);
  if (cVar7 == '\0') {
    return;
  }
  FUN_001426ec(*piVar1,*(undefined4 *)(*(int *)(*unaff_r27 + 0x182d4) + 0x204));
  iVar3 = *piVar1;
  func_0x00aed274(iVar3 + *(int *)(iVar3 + 0x24) * 0x7eb8 + 0x40);
  func_0x009be624(iVar3 + *(int *)(iVar3 + 0x24) * 0x5940 + 0x1fb20);
  FUN_001426f0(*piVar1);
  return;
}


