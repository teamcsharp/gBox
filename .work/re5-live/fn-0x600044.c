
void FUN_00600044(void)

{
  uint uVar1;
  undefined4 *puVar2;
  int *piVar3;
  undefined4 *puVar4;
  ulonglong uVar5;
  char cVar8;
  undefined4 uVar6;
  int iVar7;
  ulonglong uVar9;
  int iVar10;
  undefined2 *puVar11;
  int *unaff_r25;
  int unaff_r26;
  undefined2 uVar12;
  undefined4 unaff_r27;
  uint uVar13;
  uint unaff_r28;
  int iVar15;
  ulonglong uVar14;
  uint unaff_r29;
  int unaff_r30;
  int iVar16;
  int unaff_r31;
  undefined8 uVar17;
  
  iVar10 = 0x171c590;
  puVar2 = *(undefined4 **)(unaff_r30 + -0x7f54);
  cVar8 = func_0x00103640(*puVar2);
  if (cVar8 == '\0') {
    piVar3 = *(int **)(unaff_r30 + -0x7f48);
  }
  else {
    piVar3 = *(int **)(unaff_r30 + -0x7f48);
    uVar13 = *(uint *)(*piVar3 + 0x1ea0);
    *(undefined4 *)(unaff_r31 + 0x44) = 1;
    unaff_r29 = unaff_r29 | uVar13;
  }
  puVar4 = *(undefined4 **)(unaff_r30 + -0x7e7c);
  func_0x0013e848(*puVar4,1,4,0);
  if (((unaff_r29 & *(uint *)(*piVar3 + 0x1ea0)) == 0) && ((unaff_r28 & 0x200) == 0)) {
    uVar13 = *(uint *)(*piVar3 + 0x1ea4);
    if (((unaff_r29 & uVar13) == 0) && ((unaff_r28 & uVar13) == 0)) {
      uVar6 = func_0x0054cbf0(unaff_r27,*(undefined4 *)(unaff_r31 + 0x44),
                              *(undefined4 *)(unaff_r31 + 0x17c));
      iVar7 = func_0x0013fd34(*puVar4,uVar6,*(undefined4 *)(unaff_r31 + 0x17c),0,4,0);
      if (*(int *)(unaff_r31 + 0x44) != iVar7) {
        *(int *)(unaff_r31 + 0x44) = iVar7;
        func_0x006337dc(*(undefined4 *)(unaff_r31 + 0x120),iVar7);
        func_0x0054bff8(unaff_r27);
      }
    }
    else {
      func_0x0013e454(*puVar4,4,0,1);
      func_0x0054c138(unaff_r27);
      *(undefined1 *)(unaff_r31 + 0x3a) = 1;
      *(undefined4 *)(unaff_r31 + 0x40) = 0;
      *(char *)(unaff_r31 + 0x17) = *(char *)(unaff_r31 + 0x17) + '\x01';
    }
  }
  else {
    func_0x0013e454(*puVar4,4,0,1);
    if ((1 << (*(uint *)(unaff_r31 + 0x44) & 0x3f) & *(uint *)(unaff_r31 + 0x180)) == 0) {
      func_0x0054bf78(unaff_r27);
    }
    else {
      *(uint *)(*(int *)(*unaff_r25 + 0x182d4) + 0x1c) = *(uint *)(unaff_r31 + 0x44);
      uVar13 = *(uint *)(unaff_r31 + 0x44);
      if (uVar13 == 7) {
        if (*(char *)(unaff_r31 + 0x184) != '\0') {
          *(undefined4 *)(unaff_r31 + 0x188) = 0;
          func_0x0054c0b8(unaff_r27);
          uVar6 = *(undefined4 *)(unaff_r30 + -0x7e78);
          *(undefined1 *)(unaff_r31 + 0x39) = 1;
          *(undefined4 *)(unaff_r31 + 0x40) = uVar6;
          *(undefined1 *)(unaff_r31 + 0x17) = 10;
          goto LAB_00600110;
        }
        uVar6 = func_0x000bbe20(**(undefined4 **)(unaff_r30 + -0x7e4c));
        func_0x00010c74(uVar6,1);
        piVar3 = *(int **)(unaff_r30 + -0x7e50);
        iVar7 = *piVar3;
        *(uint *)(iVar7 + 0x307b4) = *(uint *)(iVar7 + 0x307b4) | 8;
        func_0x001795bc(*piVar3);
      }
      else if (uVar13 < 8) {
                    /* WARNING: Could not recover jumptable at 0x00600770. Too many branches */
                    /* WARNING: Treating indirect jump as call */
        (*(code *)(*(int *)(uVar13 * 4 + *(int *)(unaff_r30 + -0x7e54)) +
                  *(int *)(unaff_r30 + -0x7e54)))();
        return;
      }
      func_0x006337fc(*(undefined4 *)(unaff_r31 + 0x120),1);
      cVar8 = func_0x00103640(*puVar2);
      if (cVar8 == '\0') {
        func_0x0054c178(unaff_r27);
      }
      *(undefined4 *)(unaff_r31 + 0x40) = *(undefined4 *)(unaff_r30 + -0x7e78);
      *(undefined1 *)(unaff_r31 + 0x39) = 1;
      *(char *)(unaff_r31 + 0x17) = *(char *)(unaff_r31 + 0x17) + '\x01';
    }
  }
LAB_00600110:
  if ((*(uint *)(*unaff_r25 + 0x182dc) & 1) != 0) {
    iVar10 = *(int *)(iVar10 + -0x797c);
    func_0x0054bd6c(unaff_r26);
    if (*(int *)(unaff_r26 + 0x17c) < 1) {
      iVar10 = *(int *)(iVar10 + -0x7fe8);
    }
    else {
      iVar10 = *(int *)(iVar10 + -0x7fe8);
      uVar14 = 0;
      iVar7 = 300;
      puVar11 = (undefined2 *)(iVar10 + 0x62);
      do {
        uVar5 = uVar14 ^ *(uint *)(unaff_r26 + 0x44);
        uVar9 = (ulonglong)((int)uVar5 >> 0x1f);
        func_0x005bd968(&stack0x00000040,unaff_r26,((uVar9 ^ uVar5) - uVar9) - 1 >> 0x1f & 1,0xff,0)
        ;
        uVar5 = uVar14 ^ *(uint *)(unaff_r26 + 0x44);
        uVar9 = (ulonglong)((int)uVar5 >> 0x1f);
        uVar17 = func_0x005bb950(unaff_r26,((uVar9 ^ uVar5) - uVar9) - 1 >> 0x1f & 1);
        iVar15 = (int)uVar14;
        uVar12 = *puVar11;
        if ((*(int *)(unaff_r26 + 0x44) == iVar15) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
          func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
        }
        func_0x005bc9d0(uVar17,unaff_r26,uVar12,0x280,iVar7,&stack0x00000044);
        uVar5 = uVar14 ^ *(uint *)(unaff_r26 + 0x44);
        uVar9 = (ulonglong)((int)uVar5 >> 0x1f);
        uVar14 = uVar14 + 1;
        func_0x005bdbd8(unaff_r26,iVar15 + 4,uVar12,((uVar9 ^ uVar5) - uVar9) - 1 >> 0x1f & 1,
                        0xffffffffffffffff);
        iVar7 = iVar7 + 0x32;
        puVar11 = puVar11 + 1;
      } while ((int)uVar14 < *(int *)(unaff_r26 + 0x17c));
    }
    func_0x005bd8d0(unaff_r26,*(undefined2 *)(*(int *)(unaff_r26 + 0x44) * 2 + iVar10 + 0x68),0x23a)
    ;
    func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
    return;
  }
  if (*(int *)(unaff_r31 + 0x174) != 0) {
    iVar10 = *(int *)(iVar10 + -0x797c);
    func_0x0054bd6c(unaff_r26);
    if (0 < *(int *)(unaff_r26 + 0x18c)) {
      uVar14 = 0;
      puVar11 = (undefined2 *)(*(int *)(iVar10 + -0x7fe8) + 0x6e);
      iVar7 = 0xfa;
      do {
        uVar5 = uVar14 ^ *(uint *)(unaff_r26 + 0x188);
        uVar9 = (ulonglong)((int)uVar5 >> 0x1f);
        func_0x005bd968(&stack0x00000050,unaff_r26,((uVar9 ^ uVar5) - uVar9) - 1 >> 0x1f & 1,0xff,0)
        ;
        uVar5 = uVar14 ^ *(uint *)(unaff_r26 + 0x188);
        uVar9 = (ulonglong)((int)uVar5 >> 0x1f);
        uVar17 = func_0x005bb950(unaff_r26,((uVar9 ^ uVar5) - uVar9) - 1 >> 0x1f & 1);
        uVar13 = (uint)uVar14;
        uVar12 = *puVar11;
        if ((*(uint *)(unaff_r26 + 0x188) == uVar13) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
          func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
        }
        if ((*(int *)(unaff_r26 + 400) >> (uVar13 & 0x3f) & 1U) == 0) {
          cVar8 = func_0x000dbff4(**(undefined4 **)(iVar10 + -0x7fa4));
          if ((cVar8 != '\0') && (0 < (int)uVar13)) {
            uVar12 = 0x331;
          }
        }
        puVar11 = puVar11 + 1;
        func_0x005bc9d0(uVar17,unaff_r26,uVar12,0x280,iVar7,&stack0x00000054);
        uVar5 = uVar14 ^ *(uint *)(unaff_r26 + 0x188);
        uVar9 = (ulonglong)((int)uVar5 >> 0x1f);
        uVar14 = uVar14 + 1;
        func_0x005bdbd8(unaff_r26,uVar13 + 3,uVar12,((uVar9 ^ uVar5) - uVar9) - 1 >> 0x1f & 1,
                        0xffffffffffffffff);
        iVar7 = iVar7 + 0x32;
      } while ((int)uVar14 < *(int *)(unaff_r26 + 0x18c));
    }
    uVar13 = *(uint *)(unaff_r26 + 0x188);
    if ((*(int *)(unaff_r26 + 400) >> (uVar13 & 0x3f) & 1U) == 0) {
      cVar8 = func_0x000dbff4(**(undefined4 **)(iVar10 + -0x7fa4));
      if (cVar8 == '\0') {
        uVar13 = *(uint *)(unaff_r26 + 0x188);
      }
      else {
        uVar13 = 0;
        if (*(int *)(unaff_r26 + 0x188) != 0) goto LAB_005fa9cc;
      }
    }
    func_0x005bd8d0(unaff_r26,*(undefined2 *)(uVar13 * 2 + *(int *)(iVar10 + -0x7fe8) + 0x78),0x23a)
    ;
LAB_005fa9cc:
    func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
    return;
  }
  iVar10 = *(int *)(iVar10 + -0x797c);
  func_0x0054bd6c(unaff_r26);
  if (0 < *(int *)(unaff_r26 + 0x17c)) {
    iVar7 = *(int *)(iVar10 + -0x7fe8);
    puVar11 = (undefined2 *)(iVar7 + 0x82);
    uVar14 = 0;
    iVar15 = 0x96;
    do {
      uVar5 = uVar14 ^ *(uint *)(unaff_r26 + 0x44);
      uVar9 = (ulonglong)((int)uVar5 >> 0x1f);
      func_0x005bd968(&stack0x00000040,unaff_r26,((uVar9 ^ uVar5) - uVar9) - 1 >> 0x1f & 1,0xff,0);
      uVar5 = uVar14 ^ *(uint *)(unaff_r26 + 0x44);
      uVar9 = (ulonglong)((int)uVar5 >> 0x1f);
      uVar17 = func_0x005bb950(unaff_r26,((uVar9 ^ uVar5) - uVar9) - 1 >> 0x1f & 1);
      uVar13 = (uint)uVar14;
      if (uVar13 == 0) {
        if (*(int *)(unaff_r26 + 0x178) == 0) goto LAB_005fabf8;
        uVar12 = *(undefined2 *)(*(int *)(unaff_r26 + 0x178) * 2 + iVar7 + 0x90);
LAB_005faad0:
        uVar1 = *(uint *)(unaff_r26 + 0x44);
      }
      else {
        if ((uVar13 == 7) && (uVar12 = 0x325, *(char *)(unaff_r26 + 0x184) != '\0'))
        goto LAB_005faad0;
LAB_005fabf8:
        uVar1 = *(uint *)(unaff_r26 + 0x44);
        uVar12 = *puVar11;
      }
      if ((uVar1 == uVar13) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
        func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
      }
      if (((1 << (uVar13 & 0x3f) & *(uint *)(unaff_r26 + 0x180)) == 0) && (uVar13 == 6)) {
        uVar12 = 0x331;
      }
      puVar11 = puVar11 + 1;
      func_0x005bc9d0(uVar17,unaff_r26,uVar12,0x280,iVar15,&stack0x00000044);
      uVar5 = uVar14 ^ *(uint *)(unaff_r26 + 0x44);
      uVar9 = (ulonglong)((int)uVar5 >> 0x1f);
      iVar16 = (int)(uVar14 + 1);
      func_0x005bdbd8(unaff_r26,iVar16,uVar12,((uVar9 ^ uVar5) - uVar9) - 1 >> 0x1f & 1,
                      0xffffffffffffffff);
      uVar14 = uVar14 + 1;
      iVar15 = iVar15 + 0x32;
    } while (iVar16 < *(int *)(unaff_r26 + 0x17c));
  }
  iVar7 = *(int *)(unaff_r26 + 0x44);
  if (iVar7 == 6) {
    if ((*(uint *)(unaff_r26 + 0x180) & 0x40) == 0) goto LAB_005facc4;
LAB_005fac9c:
    uVar12 = *(undefined2 *)(iVar7 * 2 + *(int *)(iVar10 + -0x7fe8) + 0x98);
  }
  else {
    if (iVar7 != 0) {
      if (iVar7 == 7) {
        uVar12 = 0x32f;
        if (*(char *)(unaff_r26 + 0x184) != '\0') goto LAB_005facb0;
      }
      else if (7 < iVar7) goto LAB_005facc4;
      goto LAB_005fac9c;
    }
    if (*(int *)(unaff_r26 + 0x178) == 0) goto LAB_005fac9c;
    uVar12 = *(undefined2 *)(*(int *)(unaff_r26 + 0x178) * 2 + *(int *)(iVar10 + -0x7fe8) + 0xa6);
  }
LAB_005facb0:
  func_0x005bd8d0(unaff_r26,uVar12,0x23a);
LAB_005facc4:
  func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
  return;
}


