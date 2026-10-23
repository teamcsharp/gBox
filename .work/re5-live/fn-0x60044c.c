
void FUN_0060044c(void)

{
  uint uVar1;
  undefined4 *puVar2;
  ulonglong uVar3;
  char cVar6;
  undefined4 uVar4;
  int iVar5;
  ulonglong uVar7;
  int iVar8;
  undefined2 *puVar9;
  int *unaff_r25;
  int unaff_r26;
  undefined2 uVar10;
  undefined4 unaff_r27;
  uint uVar11;
  uint unaff_r28;
  int iVar13;
  ulonglong uVar12;
  uint unaff_r29;
  int unaff_r30;
  int iVar14;
  int unaff_r31;
  undefined8 uVar15;
  
  iVar8 = 0x171c590;
  puVar2 = *(undefined4 **)(unaff_r30 + -0x7e7c);
  func_0x0013e848(*puVar2,0x15,4,0);
  if (((unaff_r29 & *(uint *)(**(int **)(unaff_r30 + -0x7f48) + 0x1ea0)) == 0) &&
     ((unaff_r28 & 0x200) == 0)) {
    uVar11 = *(uint *)(**(int **)(unaff_r30 + -0x7f48) + 0x1ea4);
    if (((unaff_r29 & uVar11) == 0) && ((unaff_r28 & uVar11) == 0)) {
      uVar4 = func_0x0054cbf0(unaff_r27,*(undefined4 *)(unaff_r31 + 0x188),
                              *(undefined4 *)(unaff_r31 + 0x18c));
      iVar5 = func_0x0013fd34(*puVar2,uVar4,*(undefined4 *)(unaff_r31 + 0x18c),0,4,0);
      if (*(int *)(unaff_r31 + 0x188) != iVar5) {
        *(int *)(unaff_r31 + 0x188) = iVar5;
        func_0x0054bff8(unaff_r27);
      }
    }
    else {
      func_0x0013e454(*puVar2,4,0,1);
      func_0x0054c038(unaff_r27);
      *(undefined1 *)(unaff_r31 + 0x17) = 2;
      *(undefined4 *)(unaff_r31 + 0x174) = 0;
    }
  }
  else {
    func_0x0013e454(*puVar2,4,0,1);
    if ((*(int *)(unaff_r31 + 400) >> (*(uint *)(unaff_r31 + 0x188) & 0x3f) & 1U) == 0) {
      func_0x0054bf78(unaff_r27);
    }
    else {
      func_0x0054c178(unaff_r27);
      uVar4 = func_0x000bbe20(**(undefined4 **)(unaff_r30 + -0x7e4c));
      func_0x00010c74(uVar4,1);
      if (*(uint *)(unaff_r31 + 0x188) < 5) {
                    /* WARNING: Could not recover jumptable at 0x006005c0. Too many branches */
                    /* WARNING: Treating indirect jump as call */
        (*(code *)(*(int *)(*(uint *)(unaff_r31 + 0x188) * 4 + *(int *)(unaff_r30 + -0x7e48)) +
                  *(int *)(unaff_r30 + -0x7e48)))();
        return;
      }
      func_0x001795bc(**(undefined4 **)(unaff_r30 + -0x7e50));
      func_0x006337fc(*(undefined4 *)(unaff_r31 + 0x120),1);
      *(undefined4 *)(unaff_r31 + 0x40) = *(undefined4 *)(unaff_r30 + -0x7e78);
      *(undefined1 *)(unaff_r31 + 0x39) = 1;
      *(char *)(unaff_r31 + 0x17) = *(char *)(unaff_r31 + 0x17) + '\x01';
    }
  }
  if ((*(uint *)(*unaff_r25 + 0x182dc) & 1) != 0) {
    iVar8 = *(int *)(iVar8 + -0x797c);
    func_0x0054bd6c(unaff_r26);
    if (*(int *)(unaff_r26 + 0x17c) < 1) {
      iVar8 = *(int *)(iVar8 + -0x7fe8);
    }
    else {
      iVar8 = *(int *)(iVar8 + -0x7fe8);
      uVar12 = 0;
      iVar5 = 300;
      puVar9 = (undefined2 *)(iVar8 + 0x62);
      do {
        uVar3 = uVar12 ^ *(uint *)(unaff_r26 + 0x44);
        uVar7 = (ulonglong)((int)uVar3 >> 0x1f);
        func_0x005bd968(&stack0x00000040,unaff_r26,((uVar7 ^ uVar3) - uVar7) - 1 >> 0x1f & 1,0xff,0)
        ;
        uVar3 = uVar12 ^ *(uint *)(unaff_r26 + 0x44);
        uVar7 = (ulonglong)((int)uVar3 >> 0x1f);
        uVar15 = func_0x005bb950(unaff_r26,((uVar7 ^ uVar3) - uVar7) - 1 >> 0x1f & 1);
        iVar13 = (int)uVar12;
        uVar10 = *puVar9;
        if ((*(int *)(unaff_r26 + 0x44) == iVar13) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
          func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
        }
        func_0x005bc9d0(uVar15,unaff_r26,uVar10,0x280,iVar5,&stack0x00000044);
        uVar3 = uVar12 ^ *(uint *)(unaff_r26 + 0x44);
        uVar7 = (ulonglong)((int)uVar3 >> 0x1f);
        uVar12 = uVar12 + 1;
        func_0x005bdbd8(unaff_r26,iVar13 + 4,uVar10,((uVar7 ^ uVar3) - uVar7) - 1 >> 0x1f & 1,
                        0xffffffffffffffff);
        iVar5 = iVar5 + 0x32;
        puVar9 = puVar9 + 1;
      } while ((int)uVar12 < *(int *)(unaff_r26 + 0x17c));
    }
    func_0x005bd8d0(unaff_r26,*(undefined2 *)(*(int *)(unaff_r26 + 0x44) * 2 + iVar8 + 0x68),0x23a);
    func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
    return;
  }
  if (*(int *)(unaff_r31 + 0x174) != 0) {
    iVar8 = *(int *)(iVar8 + -0x797c);
    func_0x0054bd6c(unaff_r26);
    if (0 < *(int *)(unaff_r26 + 0x18c)) {
      uVar12 = 0;
      puVar9 = (undefined2 *)(*(int *)(iVar8 + -0x7fe8) + 0x6e);
      iVar5 = 0xfa;
      do {
        uVar3 = uVar12 ^ *(uint *)(unaff_r26 + 0x188);
        uVar7 = (ulonglong)((int)uVar3 >> 0x1f);
        func_0x005bd968(&stack0x00000050,unaff_r26,((uVar7 ^ uVar3) - uVar7) - 1 >> 0x1f & 1,0xff,0)
        ;
        uVar3 = uVar12 ^ *(uint *)(unaff_r26 + 0x188);
        uVar7 = (ulonglong)((int)uVar3 >> 0x1f);
        uVar15 = func_0x005bb950(unaff_r26,((uVar7 ^ uVar3) - uVar7) - 1 >> 0x1f & 1);
        uVar11 = (uint)uVar12;
        uVar10 = *puVar9;
        if ((*(uint *)(unaff_r26 + 0x188) == uVar11) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
          func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
        }
        if ((*(int *)(unaff_r26 + 400) >> (uVar11 & 0x3f) & 1U) == 0) {
          cVar6 = func_0x000dbff4(**(undefined4 **)(iVar8 + -0x7fa4));
          if ((cVar6 != '\0') && (0 < (int)uVar11)) {
            uVar10 = 0x331;
          }
        }
        puVar9 = puVar9 + 1;
        func_0x005bc9d0(uVar15,unaff_r26,uVar10,0x280,iVar5,&stack0x00000054);
        uVar3 = uVar12 ^ *(uint *)(unaff_r26 + 0x188);
        uVar7 = (ulonglong)((int)uVar3 >> 0x1f);
        uVar12 = uVar12 + 1;
        func_0x005bdbd8(unaff_r26,uVar11 + 3,uVar10,((uVar7 ^ uVar3) - uVar7) - 1 >> 0x1f & 1,
                        0xffffffffffffffff);
        iVar5 = iVar5 + 0x32;
      } while ((int)uVar12 < *(int *)(unaff_r26 + 0x18c));
    }
    uVar11 = *(uint *)(unaff_r26 + 0x188);
    if ((*(int *)(unaff_r26 + 400) >> (uVar11 & 0x3f) & 1U) == 0) {
      cVar6 = func_0x000dbff4(**(undefined4 **)(iVar8 + -0x7fa4));
      if (cVar6 == '\0') {
        uVar11 = *(uint *)(unaff_r26 + 0x188);
      }
      else {
        uVar11 = 0;
        if (*(int *)(unaff_r26 + 0x188) != 0) goto LAB_005fa9cc;
      }
    }
    func_0x005bd8d0(unaff_r26,*(undefined2 *)(uVar11 * 2 + *(int *)(iVar8 + -0x7fe8) + 0x78),0x23a);
LAB_005fa9cc:
    func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
    return;
  }
  iVar8 = *(int *)(iVar8 + -0x797c);
  func_0x0054bd6c(unaff_r26);
  if (0 < *(int *)(unaff_r26 + 0x17c)) {
    iVar5 = *(int *)(iVar8 + -0x7fe8);
    puVar9 = (undefined2 *)(iVar5 + 0x82);
    uVar12 = 0;
    iVar13 = 0x96;
    do {
      uVar3 = uVar12 ^ *(uint *)(unaff_r26 + 0x44);
      uVar7 = (ulonglong)((int)uVar3 >> 0x1f);
      func_0x005bd968(&stack0x00000040,unaff_r26,((uVar7 ^ uVar3) - uVar7) - 1 >> 0x1f & 1,0xff,0);
      uVar3 = uVar12 ^ *(uint *)(unaff_r26 + 0x44);
      uVar7 = (ulonglong)((int)uVar3 >> 0x1f);
      uVar15 = func_0x005bb950(unaff_r26,((uVar7 ^ uVar3) - uVar7) - 1 >> 0x1f & 1);
      uVar11 = (uint)uVar12;
      if (uVar11 == 0) {
        if (*(int *)(unaff_r26 + 0x178) == 0) goto LAB_005fabf8;
        uVar10 = *(undefined2 *)(*(int *)(unaff_r26 + 0x178) * 2 + iVar5 + 0x90);
LAB_005faad0:
        uVar1 = *(uint *)(unaff_r26 + 0x44);
      }
      else {
        if ((uVar11 == 7) && (uVar10 = 0x325, *(char *)(unaff_r26 + 0x184) != '\0'))
        goto LAB_005faad0;
LAB_005fabf8:
        uVar1 = *(uint *)(unaff_r26 + 0x44);
        uVar10 = *puVar9;
      }
      if ((uVar1 == uVar11) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
        func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
      }
      if (((1 << (uVar11 & 0x3f) & *(uint *)(unaff_r26 + 0x180)) == 0) && (uVar11 == 6)) {
        uVar10 = 0x331;
      }
      puVar9 = puVar9 + 1;
      func_0x005bc9d0(uVar15,unaff_r26,uVar10,0x280,iVar13,&stack0x00000044);
      uVar3 = uVar12 ^ *(uint *)(unaff_r26 + 0x44);
      uVar7 = (ulonglong)((int)uVar3 >> 0x1f);
      iVar14 = (int)(uVar12 + 1);
      func_0x005bdbd8(unaff_r26,iVar14,uVar10,((uVar7 ^ uVar3) - uVar7) - 1 >> 0x1f & 1,
                      0xffffffffffffffff);
      uVar12 = uVar12 + 1;
      iVar13 = iVar13 + 0x32;
    } while (iVar14 < *(int *)(unaff_r26 + 0x17c));
  }
  iVar5 = *(int *)(unaff_r26 + 0x44);
  if (iVar5 == 6) {
    if ((*(uint *)(unaff_r26 + 0x180) & 0x40) == 0) goto LAB_005facc4;
LAB_005fac9c:
    uVar10 = *(undefined2 *)(iVar5 * 2 + *(int *)(iVar8 + -0x7fe8) + 0x98);
  }
  else {
    if (iVar5 != 0) {
      if (iVar5 == 7) {
        uVar10 = 0x32f;
        if (*(char *)(unaff_r26 + 0x184) != '\0') goto LAB_005facb0;
      }
      else if (7 < iVar5) goto LAB_005facc4;
      goto LAB_005fac9c;
    }
    if (*(int *)(unaff_r26 + 0x178) == 0) goto LAB_005fac9c;
    uVar10 = *(undefined2 *)(*(int *)(unaff_r26 + 0x178) * 2 + *(int *)(iVar8 + -0x7fe8) + 0xa6);
  }
LAB_005facb0:
  func_0x005bd8d0(unaff_r26,uVar10,0x23a);
LAB_005facc4:
  func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
  return;
}


