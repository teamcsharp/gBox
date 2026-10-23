
void FUN_00148ff0(void)

{
  bool bVar1;
  short sVar2;
  uint *puVar3;
  char *pcVar4;
  char cVar6;
  int iVar5;
  uint uVar7;
  uint uVar8;
  short *psVar9;
  int iVar10;
  int unaff_r25;
  int iVar11;
  int unaff_r27;
  undefined4 *unaff_r28;
  int iVar12;
  int unaff_r29;
  int iVar13;
  int unaff_r30;
  undefined4 unaff_r31;
  uint uVar14;
  ulonglong uVar15;
  
  cVar6 = func_0x00201908(*unaff_r28,unaff_r31);
  if (cVar6 != '\0') {
    iVar10 = unaff_r27 + 8;
    puVar3 = *(uint **)(unaff_r30 + -0x7fdc);
    iVar12 = 0;
    pcVar4 = *(char **)(unaff_r30 + -0x7f50);
    iVar11 = unaff_r27 + unaff_r29 * 0xd8 + *(int *)(unaff_r25 + 0x24) * 0x5940 + 0x20e50;
    do {
      while( true ) {
        iVar13 = iVar12 * 4;
        if (0 < (int)*puVar3) break;
LAB_001490b0:
        iVar5 = iVar13 + unaff_r27 + 0x40;
        bVar1 = iVar12 == 0x35;
        iVar12 = iVar12 + 1;
        *(undefined2 *)(iVar5 + 0x33d8) = *(undefined2 *)(iVar11 + iVar13);
        *(undefined2 *)(iVar5 + 0x33da) = ((undefined2 *)(iVar11 + iVar13))[1];
        if (bVar1) {
          return;
        }
      }
      uVar14 = 0;
      uVar8 = 0;
      uVar7 = 1;
      if (**(short **)(unaff_r30 + -0x7fd8) != *(short *)(iVar13 + iVar11)) {
        uVar15 = (ulonglong)*puVar3;
        psVar9 = *(short **)(unaff_r30 + -0x7fe0);
        do {
          uVar14 = uVar14 + 1;
          uVar15 = uVar15 - 1;
          if (uVar15 == 0) goto LAB_001490b0;
          sVar2 = *psVar9;
          psVar9 = psVar9 + 1;
        } while (*(short *)(iVar13 + iVar11) != sVar2);
        if ((int)uVar14 < 0) goto LAB_001490b0;
        uVar8 = uVar14 >> 5;
        uVar7 = 1 << (uVar14 & 0x1f);
      }
      iVar5 = *(int *)(unaff_r25 + 0x24);
      if ((uVar7 & *(uint *)(unaff_r27 + (iVar5 * 0x1fae + uVar8) * 4 + 0xf4)) != 0)
      goto LAB_001490b0;
      if ((*(char *)(unaff_r27 + 0x20) != '\0') || (*pcVar4 != '\0')) {
        func_0x01399428(iVar10,0);
        iVar5 = *(int *)(unaff_r25 + 0x24);
      }
      func_0x00aec8d4(unaff_r27 + iVar5 * 0x7eb8 + 0x40,uVar14);
      if (((*(char *)(unaff_r27 + 0x20) != '\0') || (*pcVar4 != '\0')) &&
         ((func_0x01399448(iVar10), *(char *)(unaff_r27 + 0x20) != '\0' || (*pcVar4 != '\0')))) {
        func_0x01399428(iVar10,0);
      }
      func_0x00aec90c(unaff_r27 + *(int *)(unaff_r25 + 0x24) * 0x7eb8 + 0x40,uVar14);
      if ((*(char *)(unaff_r27 + 0x20) == '\0') && (*pcVar4 == '\0')) goto LAB_001490b0;
      func_0x01399448(iVar10);
      iVar5 = iVar13 + unaff_r27 + 0x40;
      bVar1 = iVar12 != 0x35;
      iVar12 = iVar12 + 1;
      *(undefined2 *)(iVar5 + 0x33d8) = *(undefined2 *)(iVar11 + iVar13);
      *(undefined2 *)(iVar5 + 0x33da) = ((undefined2 *)(iVar11 + iVar13))[1];
    } while (bVar1);
  }
  return;
}


