
void FUN_00146c88(void)

{
  bool bVar1;
  short sVar2;
  undefined4 *puVar3;
  uint *puVar4;
  char cVar8;
  int iVar5;
  undefined4 uVar6;
  int iVar7;
  uint uVar9;
  uint uVar10;
  int iVar11;
  short *psVar12;
  int unaff_r24;
  undefined4 *unaff_r26;
  int iVar13;
  ulonglong unaff_r27;
  int iVar14;
  int unaff_r28;
  int *unaff_r29;
  int unaff_r30;
  undefined4 unaff_r31;
  uint uVar15;
  ulonglong uVar16;
  
  cVar8 = func_0x00201908(*unaff_r26,unaff_r31);
  if (cVar8 == '\0') {
    return;
  }
  if ((*(char *)(unaff_r28 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f50) != '\0')) {
    func_0x01399428(unaff_r28 + 8,0);
  }
  puVar3 = *(undefined4 **)(unaff_r30 + -0x7f3c);
  iVar5 = func_0x000bbca0(*puVar3);
  if (iVar5 != 0) {
    uVar6 = func_0x000bbca0(*puVar3);
    uVar6 = func_0x0001791c(uVar6);
    if ((*(char *)(unaff_r28 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f50) != '\0')) {
      func_0x01399428(unaff_r28 + 8,0);
    }
    *(undefined4 *)(unaff_r28 + *(int *)(unaff_r24 + 0x24) * 0x5940 + 0x23cdc) = uVar6;
    if ((*(char *)(unaff_r28 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f50) != '\0')) {
      func_0x01399448(unaff_r28 + 8);
    }
  }
  iVar13 = unaff_r28 + *(int *)(unaff_r24 + 0x24) * 0x5940 + 0x1fc10;
  func_0x00a48ac4(iVar13);
  iVar11 = *(int *)(unaff_r24 + 0x24) * 0x5940;
  iVar5 = *(int *)(unaff_r28 + iVar11 + 0x23ce8);
  iVar14 = (int)unaff_r27;
  if ((iVar5 - 600U < 100) || ((99 < iVar5 && (*(uint *)(unaff_r28 + iVar11 + 0x23cf0) < 0x498))))
  goto LAB_00146e44;
  iVar11 = iVar13 + 0x15a0;
  iVar5 = *(int *)(*(int *)(*unaff_r29 + 0x182d4) + 0x200);
  if (iVar5 < 0) {
    iVar5 = iVar13 + 0x2b30;
    if ((*(uint *)(*(int *)(*unaff_r29 + 0x182d4) + 0x2f0) & 1) == 0) goto LAB_001471b0;
LAB_001471b4:
    func_0x00a47da8(iVar13,iVar5,iVar13 + 0x10,0);
  }
  else if ((iVar14 == 0) ||
          (cVar8 = func_0x00201908(**(undefined4 **)(unaff_r30 + -0x7fc4),iVar5), cVar8 == '\0')) {
LAB_001471b0:
    iVar5 = iVar11;
    goto LAB_001471b4;
  }
  iVar5 = *(int *)(*(int *)(*unaff_r29 + 0x182d4) + 0x204);
  if (iVar5 < 0) {
    if ((*(uint *)(*(int *)(*unaff_r29 + 0x182d4) + 0x2f0) & 2) != 0) {
      iVar11 = iVar13 + 0x2b30;
    }
  }
  else if ((iVar14 != 1) &&
          (cVar8 = func_0x00201908(**(undefined4 **)(unaff_r30 + -0x7fc4),iVar5), cVar8 != '\0'))
  goto LAB_00146e44;
  func_0x00a47da8(iVar13,iVar11,iVar13 + 0x10,1);
LAB_00146e44:
  uVar6 = *(undefined4 *)
           (iVar13 + (int)((unaff_r27 & 0xffffffff) << 4) + (int)((unaff_r27 & 0xffffffff) << 6) +
                     0x50);
  if ((*(char *)(unaff_r28 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f50) != '\0')) {
    func_0x01399428(unaff_r28 + 8,0);
  }
  *(undefined4 *)(unaff_r28 + *(int *)(unaff_r24 + 0x24) * 0x7eb8 + 0x118) = uVar6;
  if ((*(char *)(unaff_r28 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f50) != '\0')) {
    func_0x01399448(unaff_r28 + 8);
  }
  iVar11 = 0;
  puVar4 = *(uint **)(unaff_r30 + -0x7fdc);
  iVar5 = *(int *)(unaff_r24 + 0x24) * 0x1fae;
  iVar13 = iVar13 + iVar14 * 0xd8 + 0x1240;
  do {
    while( true ) {
      iVar14 = iVar11 * 4;
      if (0 < (int)*puVar4) break;
LAB_00146f30:
      iVar7 = (iVar5 + iVar11) * 4 + unaff_r28;
      bVar1 = iVar11 == 0x35;
      iVar11 = iVar11 + 1;
      *(undefined2 *)(iVar7 + 0x3418) = *(undefined2 *)(iVar13 + iVar14);
      *(undefined2 *)(iVar7 + 0x341a) = ((undefined2 *)(iVar13 + iVar14))[1];
      if (bVar1) goto LAB_00146f68;
    }
    uVar15 = 0;
    uVar10 = 0;
    uVar9 = 1;
    if (**(short **)(unaff_r30 + -0x7fd8) != *(short *)(iVar14 + iVar13)) {
      uVar16 = (ulonglong)*puVar4;
      psVar12 = *(short **)(unaff_r30 + -0x7fe0);
      do {
        uVar15 = uVar15 + 1;
        uVar16 = uVar16 - 1;
        if (uVar16 == 0) goto LAB_00146f30;
        sVar2 = *psVar12;
        psVar12 = psVar12 + 1;
      } while (*(short *)(iVar14 + iVar13) != sVar2);
      if ((int)uVar15 < 0) goto LAB_00146f30;
      uVar10 = uVar15 >> 5;
      uVar9 = 1 << (uVar15 & 0x1f);
    }
    iVar7 = *(int *)(unaff_r24 + 0x24);
    if ((uVar9 & *(uint *)(unaff_r28 + (iVar7 * 0x1fae + uVar10) * 4 + 0xf4)) != 0)
    goto LAB_00146f30;
    if ((*(char *)(unaff_r28 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f50) != '\0')) {
      func_0x01399428(unaff_r28 + 8,0);
      iVar7 = *(int *)(unaff_r24 + 0x24);
    }
    func_0x00aec8d4(unaff_r28 + iVar7 * 0x7eb8 + 0x40,uVar15);
    if ((*(char *)(unaff_r28 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f50) != '\0')) {
      func_0x01399448(unaff_r28 + 8);
      if ((*(char *)(unaff_r28 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f50) != '\0')) {
        func_0x01399428(unaff_r28 + 8,0);
      }
    }
    func_0x00aec90c(unaff_r28 + *(int *)(unaff_r24 + 0x24) * 0x7eb8 + 0x40,uVar15);
    if ((*(char *)(unaff_r28 + 0x20) == '\0') && (**(char **)(unaff_r30 + -0x7f50) == '\0'))
    goto LAB_00146f30;
    func_0x01399448(unaff_r28 + 8);
    iVar7 = (iVar5 + iVar11) * 4 + unaff_r28;
    bVar1 = iVar11 != 0x35;
    iVar11 = iVar11 + 1;
    *(undefined2 *)(iVar7 + 0x3418) = *(undefined2 *)(iVar13 + iVar14);
    *(undefined2 *)(iVar7 + 0x341a) = ((undefined2 *)(iVar13 + iVar14))[1];
  } while (bVar1);
LAB_00146f68:
  if ((*(char *)(unaff_r28 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f50) != '\0')) {
    func_0x01399448(unaff_r28 + 8);
  }
  return;
}


