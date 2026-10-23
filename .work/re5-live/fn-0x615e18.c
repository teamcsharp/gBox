
void FUN_00615e18(void)

{
  undefined4 uVar1;
  float fVar2;
  uint uVar3;
  int *piVar4;
  int iVar5;
  float fVar6;
  bool bVar7;
  uint uVar8;
  undefined8 uVar9;
  int in_r8;
  int iVar10;
  int iVar11;
  int iVar12;
  int iVar13;
  undefined4 *puVar14;
  uint unaff_r23;
  int *unaff_r24;
  uint unaff_r25;
  uint unaff_r26;
  int unaff_r27;
  int *unaff_r28;
  int unaff_r29;
  int unaff_r30;
  ulonglong uVar15;
  
  if (*(char *)(unaff_r29 + 0x3c) != '\0') {
    uVar3 = *(uint *)(in_r8 + 0x182dc);
    bVar7 = (uVar3 & 0x400) != 0;
    if ((bVar7) || ((uVar3 & 0x100) != 0)) {
LAB_006163e4:
      if ((((*(int *)(unaff_r29 + 0x174) == 0) || (bVar7)) || ((uVar3 & 0x100) != 0)) ||
         (*(int *)(*(int *)(in_r8 + 0x182d4) + *(int *)(unaff_r29 + 0x174) * 4 + 900) != 5))
      goto LAB_006161cc;
      piVar4 = *(int **)(unaff_r30 + -0x7ff4);
      *(undefined1 *)(unaff_r29 + 0x3b) = 1;
      *(undefined4 *)(unaff_r29 + 0x160) = 0x21;
      iVar5 = *piVar4;
    }
    else {
      piVar4 = *(int **)(unaff_r30 + -0x7ff4);
      iVar5 = *piVar4;
      if ((*(int *)(iVar5 + 0x12e8) == 0) &&
         ((*(int *)(iVar5 + 0x12e4) == 0 && ((*(uint *)(in_r8 + 0x182e0) & 0x2000) == 0)))) {
        if ((*(int *)(*(int *)(in_r8 + 0x182d4) + 900) == 0) || (*(int *)(iVar5 + 0x12f0) != 0)) {
          func_0x009c2d40(*(int *)(in_r8 + 0x182d4),0);
          *(undefined1 *)(unaff_r29 + 0x3b) = 1;
          *(undefined4 *)(unaff_r29 + 0x160) = 0x20;
          func_0x0010abe8(*piVar4);
          *(undefined1 *)(unaff_r29 + 0x17) = 0x46;
          goto LAB_00615ec8;
        }
        goto LAB_006163e4;
      }
      *(undefined1 *)(unaff_r29 + 0x3b) = 1;
      *(undefined4 *)(unaff_r29 + 0x160) = 0x23;
      iVar5 = *piVar4;
    }
    func_0x0010abe8(iVar5);
    *(undefined1 *)(unaff_r29 + 0x17) = 0x46;
    goto LAB_00615ec8;
  }
LAB_006161cc:
  if (*(int *)(*(int *)(in_r8 + 0x182d4) + 0x58) == 5) {
    if (*(int *)(unaff_r29 + 0x178) == *(int *)(*unaff_r28 + 0x1f98)) {
      puVar14 = *(undefined4 **)(unaff_r30 + -0x7fd0);
      uVar9 = 0x39;
      goto LAB_006164d4;
    }
    puVar14 = *(undefined4 **)(unaff_r30 + -0x7fd0);
    uVar9 = 0x39;
LAB_006161fc:
    func_0x0013e848(*puVar14,uVar9,*(undefined4 *)(unaff_r29 + 0x174),0);
  }
  else {
    if (*(int *)(unaff_r29 + 0x178) != *(int *)(*unaff_r28 + 0x1f98)) {
      puVar14 = *(undefined4 **)(unaff_r30 + -0x7fd0);
      uVar9 = 0x37;
      goto LAB_006161fc;
    }
    puVar14 = *(undefined4 **)(unaff_r30 + -0x7fd0);
    uVar9 = 0x37;
LAB_006164d4:
    func_0x0013e848(*puVar14,uVar9,0,0);
  }
  iVar5 = *unaff_r28;
  if (((unaff_r26 & *(uint *)(iVar5 + 0x1ea0)) != 0) || ((unaff_r23 & 0x200) != 0)) {
    if ((1 << (*(uint *)(unaff_r29 + 0x180) & 0x3f) & *(uint *)(unaff_r29 + 0x188)) == 0) {
      func_0x0054bf78(unaff_r27);
    }
    else {
      if (*(int *)(unaff_r29 + 0x178) == *(int *)(iVar5 + 0x1f98)) {
        func_0x0013e454(*puVar14,0,0,1);
      }
      else {
        func_0x0013e454(*puVar14,*(undefined4 *)(unaff_r29 + 0x174),0,1);
      }
      *(undefined4 *)(*(int *)(*unaff_r24 + 0x182d4) + *(int *)(unaff_r29 + 0x174) * 4 + 0x364) =
           *(undefined4 *)(unaff_r29 + 0x180);
      func_0x0054c078(unaff_r27);
      *(undefined4 *)(unaff_r29 + 0x40) = *(undefined4 *)(unaff_r30 + -0x7f44);
      *(char *)(unaff_r29 + 0x17) = *(char *)(unaff_r29 + 0x17) + '\x01';
      *(undefined1 *)(unaff_r29 + 0x39) = 1;
    }
    goto LAB_00615ec8;
  }
  if (((unaff_r26 & *(uint *)(iVar5 + 0x1ea4)) != 0) ||
     ((unaff_r23 & *(uint *)(iVar5 + 0x1ea4)) != 0)) {
    if (*(int *)(unaff_r29 + 0x178) == *(int *)(iVar5 + 0x1f98)) {
      func_0x0013e454(*puVar14,0,0,1);
    }
    else {
      func_0x0013e454(*puVar14,*(undefined4 *)(unaff_r29 + 0x174),0,1);
    }
    func_0x0054c038(unaff_r27);
    *(undefined1 *)(unaff_r29 + 0x3a) = 1;
    *(undefined1 *)(unaff_r29 + 0x17) = 0x5a;
    goto LAB_00615ec8;
  }
  uVar3 = *(uint *)(unaff_r29 + 0x180);
  iVar13 = *(int *)(unaff_r29 + 0x184);
  if ((unaff_r25 & 0x20020) == 0) {
    if (((unaff_r25 & 0x80080) != 0) && (uVar8 = uVar3 - 1, -1 < (int)uVar8)) {
      uVar15 = (ulonglong)uVar3;
      do {
        if ((1 << (uVar8 & 0x3f) & *(uint *)(unaff_r29 + 0x188)) != 0) goto LAB_00616560;
        uVar8 = uVar8 - 1;
        uVar15 = uVar15 - 1;
      } while (uVar15 != 0);
    }
  }
  else {
    uVar8 = uVar3 + 1;
    if ((int)uVar8 < iVar13) {
      uVar15 = (ulonglong)(iVar13 - uVar8);
      do {
        if ((1 << (uVar8 & 0x3f) & *(uint *)(unaff_r29 + 0x188)) != 0) goto LAB_00616560;
        uVar8 = uVar8 + 1;
        uVar15 = uVar15 - 1;
      } while (uVar15 != 0);
    }
  }
LAB_006162b8:
  if (*(int *)(unaff_r29 + 0x178) == *(int *)(iVar5 + 0x1f98)) {
    uVar8 = func_0x0013fd34(*puVar14,uVar3,iVar13,0,0,0);
  }
  else {
    uVar8 = func_0x0013fd34(*puVar14,uVar3,iVar13,0,*(undefined4 *)(unaff_r29 + 0x174),0);
  }
  if (((1 << (uVar8 & 0x3f) & *(uint *)(unaff_r29 + 0x188)) == 0) ||
     (*(uint *)(unaff_r29 + 0x180) == uVar8)) goto LAB_00615ec8;
  goto LAB_00616310;
LAB_00616560:
  if (uVar8 == uVar3) goto LAB_006162b8;
LAB_00616310:
  *(uint *)(unaff_r29 + 0x180) = uVar8;
  func_0x0054bff8(unaff_r27);
LAB_00615ec8:
  if (0 < (int)*(uint *)(unaff_r29 + 0x184)) {
    uVar15 = (ulonglong)*(uint *)(unaff_r29 + 0x184);
    iVar5 = *(int *)(unaff_r29 + 0x180);
    uVar1 = *(undefined4 *)(unaff_r30 + -0x7f54);
    iVar12 = 0;
    iVar10 = 0x180;
    iVar13 = unaff_r27;
    do {
      while (iVar5 != iVar12) {
        *(undefined4 *)(iVar13 + 0x18c) = uVar1;
LAB_00615efc:
        iVar12 = iVar12 + 1;
        iVar10 = iVar10 + 4;
        iVar13 = iVar13 + 4;
        uVar15 = uVar15 - 1;
        if (uVar15 == 0) goto LAB_00615f50;
      }
      fVar2 = *(float *)(unaff_r30 + -0x7f38);
      iVar11 = unaff_r27 + iVar10;
      fVar6 = *(float *)(iVar11 + 0xc) - *(float *)(unaff_r29 + 0x10);
      *(float *)(iVar11 + 0xc) = fVar6;
      if (fVar2 < fVar6) goto LAB_00615efc;
      *(float *)(iVar11 + 0xc) = fVar2;
      iVar12 = iVar12 + 1;
      iVar10 = iVar10 + 4;
      iVar13 = iVar13 + 4;
      uVar15 = uVar15 - 1;
    } while (uVar15 != 0);
  }
LAB_00615f50:
  FUN_00610698(unaff_r27);
  func_0x005bbc2c(unaff_r27);
  return;
}


