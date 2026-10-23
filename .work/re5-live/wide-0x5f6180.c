
void FUN_005f6180(void)

{
  bool bVar1;
  char cVar2;
  byte bVar3;
  byte bVar4;
  int iVar5;
  int iVar6;
  uint uVar7;
  short in_r6;
  byte *pbVar8;
  undefined4 *puVar9;
  byte *pbVar10;
  int iVar11;
  short *psVar12;
  int iVar13;
  int iVar14;
  int iVar15;
  int unaff_r27;
  int iVar16;
  int unaff_r30;
  int unaff_r31;
  longlong lVar17;
  ulonglong uVar18;
  
  lVar17 = 100;
  iVar15 = 0;
  psVar12 = *(short **)(unaff_r30 + -0x7fd8);
  do {
    if (*psVar12 == in_r6) {
      iVar15 = *(int *)(*(short **)(unaff_r30 + -0x7fd8) + iVar15 * 6 + 2);
      goto LAB_005f6080;
    }
    lVar17 = lVar17 + -1;
    iVar15 = iVar15 + 1;
    psVar12 = psVar12 + 6;
  } while (lVar17 != 0);
  iVar15 = 0;
LAB_005f6080:
  puVar9 = *(undefined4 **)(unaff_r30 + -0x7ff8);
  iVar13 = 0;
  lVar17 = 0x12;
  *(undefined1 *)(unaff_r31 + 0x40) = 0;
  *(undefined4 *)(unaff_r31 + 0x2c) = 0;
  *(undefined1 *)(unaff_r31 + 8) = 0;
  *(undefined1 *)(unaff_r31 + 9) = 0;
  *(undefined1 *)(unaff_r31 + 10) = 0;
  *(undefined1 *)(unaff_r31 + 0x38) = 0;
  *(undefined4 *)(unaff_r31 + 0x10) = 0;
  *(undefined1 *)(unaff_r31 + 0x39) = 0;
  *(undefined1 *)(unaff_r31 + 0x41) = 0;
  *(undefined4 *)(unaff_r31 + 0x14) = 0;
  *(undefined1 *)(unaff_r31 + 0x3a) = 0;
  *(undefined1 *)(unaff_r31 + 0x42) = 0;
  *(undefined4 *)(unaff_r31 + 0x18) = 0;
  *(undefined1 *)(unaff_r31 + 0x3b) = 0;
  *(undefined1 *)(unaff_r31 + 0x43) = 0;
  *(undefined4 *)(unaff_r31 + 0x1c) = 0;
  *(undefined1 *)(unaff_r31 + 0x3c) = 0;
  *(undefined1 *)(unaff_r31 + 0x44) = 0;
  *(undefined4 *)(unaff_r31 + 0x20) = 0;
  *(undefined1 *)(unaff_r31 + 0x3d) = 0;
  *(undefined1 *)(unaff_r31 + 0x45) = 0;
  *(undefined4 *)(unaff_r31 + 0x24) = 0;
  *(undefined1 *)(unaff_r31 + 0x3e) = 0;
  *(undefined1 *)(unaff_r31 + 0x46) = 0;
  *(undefined4 *)(unaff_r31 + 0x28) = 0;
  *(undefined1 *)(unaff_r31 + 0x3f) = 0;
  *(undefined1 *)(unaff_r31 + 0x47) = 0;
  do {
    if (*(short *)*puVar9 == in_r6) {
      if (-1 < iVar13) {
        iVar5 = func_0x00aee354(**(int **)(unaff_r30 + -0x7ffc) +
                                *(int *)(**(int **)(unaff_r30 + -0x7ffc) + 0x24) * 0x7eb8 + 0x40);
        uVar7 = 0;
        iVar16 = 0;
        iVar13 = *(int *)(*(int *)(unaff_r30 + -0x7ff8) + iVar13 * 4);
        pbVar8 = (byte *)(iVar13 + 0xc);
        goto LAB_005f61e8;
      }
      break;
    }
    iVar13 = iVar13 + 1;
    lVar17 = lVar17 + -1;
    puVar9 = puVar9 + 1;
  } while (lVar17 != 0);
  iVar13 = 0;
  goto LAB_005f612c;
  while( true ) {
    bVar4 = (byte)(1 << ((int)cVar2 & 0x3fU));
    *(byte *)(unaff_r31 + 8) = bVar4 | *(byte *)(unaff_r31 + 8);
    if (*pbVar8 != 0) {
      iVar6 = iVar14 + 0x30;
      bVar3 = *(byte *)(unaff_r27 + iVar6);
      if (bVar3 != 0) {
        uVar18 = (ulonglong)bVar3;
        pbVar10 = pbVar8;
        do {
          uVar7 = uVar7 + *(int *)(pbVar10 + 4);
          uVar18 = uVar18 - 1;
          pbVar10 = pbVar10 + 8;
        } while (uVar18 != 0);
      }
      *(byte *)(unaff_r31 + 9) = bVar4 | *(byte *)(unaff_r31 + 9);
      *(byte *)(unaff_r27 + iVar14 + 0x40) = *pbVar8;
      *(undefined4 *)(unaff_r27 + iVar14 * 4 + 0x10) = *(undefined4 *)(pbVar8 + (uint)bVar3 * 8 + 4)
      ;
      if (*pbVar8 != 0) {
        iVar14 = 1;
        iVar11 = 0;
        do {
          if ((int)(uint)pbVar8[iVar11 + 8] <= iVar5) {
            *(char *)(unaff_r27 + iVar6 + 8) = (char)iVar14;
          }
          bVar1 = iVar14 < (int)(uint)*pbVar8;
          iVar14 = iVar14 + 1;
          iVar11 = iVar11 + 8;
        } while (bVar1);
      }
      if (*(byte *)(unaff_r27 + iVar6 + 8) <= bVar3) {
        *(byte *)(unaff_r31 + 10) = bVar4 | *(byte *)(unaff_r31 + 10);
      }
    }
    bVar1 = iVar16 == 7;
    pbVar8 = pbVar8 + 0x6c;
    iVar16 = iVar16 + 1;
    if (bVar1) break;
LAB_005f61e8:
    cVar2 = *(char *)(iVar16 + iVar13 + 2);
    iVar14 = (int)cVar2;
    if (cVar2 < 0) break;
  }
  iVar13 = ((int)uVar7 >> 2) + (uint)((int)uVar7 < 0 && (uVar7 & 3) != 0);
LAB_005f612c:
  *(int *)(unaff_r31 + 0xc) = iVar15 / 10 + iVar13;
  return;
}


