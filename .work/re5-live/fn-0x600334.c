
void FUN_00600334(void)

{
  undefined4 *puVar1;
  uint uVar2;
  ulonglong uVar3;
  char cVar4;
  int iVar5;
  ulonglong uVar6;
  int iVar7;
  undefined2 *puVar8;
  int *unaff_r25;
  int unaff_r26;
  undefined2 uVar9;
  uint uVar10;
  ulonglong uVar11;
  int iVar12;
  int unaff_r30;
  int iVar13;
  int unaff_r31;
  undefined8 uVar14;
  
  iVar7 = 0x171c590;
  cVar4 = func_0x00103640(**(undefined4 **)(unaff_r30 + -0x7f54));
  if (cVar4 != '\0') {
    *(undefined4 *)(unaff_r31 + 0x40) = 0;
  }
  puVar1 = *(undefined4 **)(unaff_r30 + -0x7e50);
  *(float *)(unaff_r31 + 0x40) =
       *(float *)(unaff_r31 + 0x40) - *(float *)(**(int **)(unaff_r30 + -0x7e70) + 0x2c);
  cVar4 = func_0x00176560(*puVar1);
  if ((cVar4 == '\0') && (*(float *)(unaff_r31 + 0x40) <= *(float *)(unaff_r30 + -0x7f50))) {
    uVar10 = *(uint *)(*unaff_r25 + 0x182dc) & 1;
    iVar12 = (-uVar10 & 0x1b) + 1;
    if (*(char *)(unaff_r31 + 0x39) == '\0') {
      func_0x005bc938(unaff_r26);
      func_0x005bc8fc(unaff_r26,iVar12,0);
    }
    else {
      uVar2 = *(uint *)(unaff_r31 + 0x44);
      iVar5 = (int)*(char *)(uVar2 + *(int *)(unaff_r30 + -0x7fe8) + 0x180);
      if ((uVar2 == 0) && (*(int *)(unaff_r31 + 0x178) != 0)) {
        iVar5 = 2;
      }
      if (uVar10 != 0) {
        uVar10 = (int)(uVar2 ^ 1) >> 0x1f;
        iVar5 = ((int)(uVar10 - (uVar10 ^ uVar2 ^ 1)) >> 0x1f & 0x45U) + 0x1d;
      }
      func_0x005bc8fc(unaff_r26,iVar12,iVar5);
      func_0x006337fc(*(undefined4 *)(unaff_r31 + 0x120),0);
    }
    *(undefined1 *)(unaff_r31 + 0x17) = 0x5a;
    *(undefined1 *)(unaff_r31 + 0x39) = 0;
  }
  if ((*(uint *)(*unaff_r25 + 0x182dc) & 1) != 0) {
    iVar7 = *(int *)(iVar7 + -0x797c);
    func_0x0054bd6c(unaff_r26);
    if (*(int *)(unaff_r26 + 0x17c) < 1) {
      iVar7 = *(int *)(iVar7 + -0x7fe8);
    }
    else {
      iVar7 = *(int *)(iVar7 + -0x7fe8);
      uVar11 = 0;
      iVar12 = 300;
      puVar8 = (undefined2 *)(iVar7 + 0x62);
      do {
        uVar3 = uVar11 ^ *(uint *)(unaff_r26 + 0x44);
        uVar6 = (ulonglong)((int)uVar3 >> 0x1f);
        func_0x005bd968(&stack0x00000040,unaff_r26,((uVar6 ^ uVar3) - uVar6) - 1 >> 0x1f & 1,0xff,0)
        ;
        uVar3 = uVar11 ^ *(uint *)(unaff_r26 + 0x44);
        uVar6 = (ulonglong)((int)uVar3 >> 0x1f);
        uVar14 = func_0x005bb950(unaff_r26,((uVar6 ^ uVar3) - uVar6) - 1 >> 0x1f & 1);
        iVar5 = (int)uVar11;
        uVar9 = *puVar8;
        if ((*(int *)(unaff_r26 + 0x44) == iVar5) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
          func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
        }
        func_0x005bc9d0(uVar14,unaff_r26,uVar9,0x280,iVar12,&stack0x00000044);
        uVar3 = uVar11 ^ *(uint *)(unaff_r26 + 0x44);
        uVar6 = (ulonglong)((int)uVar3 >> 0x1f);
        uVar11 = uVar11 + 1;
        func_0x005bdbd8(unaff_r26,iVar5 + 4,uVar9,((uVar6 ^ uVar3) - uVar6) - 1 >> 0x1f & 1,
                        0xffffffffffffffff);
        iVar12 = iVar12 + 0x32;
        puVar8 = puVar8 + 1;
      } while ((int)uVar11 < *(int *)(unaff_r26 + 0x17c));
    }
    func_0x005bd8d0(unaff_r26,*(undefined2 *)(*(int *)(unaff_r26 + 0x44) * 2 + iVar7 + 0x68),0x23a);
    func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
    return;
  }
  if (*(int *)(unaff_r31 + 0x174) != 0) {
    iVar7 = *(int *)(iVar7 + -0x797c);
    func_0x0054bd6c(unaff_r26);
    if (0 < *(int *)(unaff_r26 + 0x18c)) {
      uVar11 = 0;
      puVar8 = (undefined2 *)(*(int *)(iVar7 + -0x7fe8) + 0x6e);
      iVar12 = 0xfa;
      do {
        uVar3 = uVar11 ^ *(uint *)(unaff_r26 + 0x188);
        uVar6 = (ulonglong)((int)uVar3 >> 0x1f);
        func_0x005bd968(&stack0x00000050,unaff_r26,((uVar6 ^ uVar3) - uVar6) - 1 >> 0x1f & 1,0xff,0)
        ;
        uVar3 = uVar11 ^ *(uint *)(unaff_r26 + 0x188);
        uVar6 = (ulonglong)((int)uVar3 >> 0x1f);
        uVar14 = func_0x005bb950(unaff_r26,((uVar6 ^ uVar3) - uVar6) - 1 >> 0x1f & 1);
        uVar10 = (uint)uVar11;
        uVar9 = *puVar8;
        if ((*(uint *)(unaff_r26 + 0x188) == uVar10) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
          func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
        }
        if ((*(int *)(unaff_r26 + 400) >> (uVar10 & 0x3f) & 1U) == 0) {
          cVar4 = func_0x000dbff4(**(undefined4 **)(iVar7 + -0x7fa4));
          if ((cVar4 != '\0') && (0 < (int)uVar10)) {
            uVar9 = 0x331;
          }
        }
        puVar8 = puVar8 + 1;
        func_0x005bc9d0(uVar14,unaff_r26,uVar9,0x280,iVar12,&stack0x00000054);
        uVar3 = uVar11 ^ *(uint *)(unaff_r26 + 0x188);
        uVar6 = (ulonglong)((int)uVar3 >> 0x1f);
        uVar11 = uVar11 + 1;
        func_0x005bdbd8(unaff_r26,uVar10 + 3,uVar9,((uVar6 ^ uVar3) - uVar6) - 1 >> 0x1f & 1,
                        0xffffffffffffffff);
        iVar12 = iVar12 + 0x32;
      } while ((int)uVar11 < *(int *)(unaff_r26 + 0x18c));
    }
    uVar10 = *(uint *)(unaff_r26 + 0x188);
    if ((*(int *)(unaff_r26 + 400) >> (uVar10 & 0x3f) & 1U) == 0) {
      cVar4 = func_0x000dbff4(**(undefined4 **)(iVar7 + -0x7fa4));
      if (cVar4 == '\0') {
        uVar10 = *(uint *)(unaff_r26 + 0x188);
      }
      else {
        uVar10 = 0;
        if (*(int *)(unaff_r26 + 0x188) != 0) goto LAB_005fa9cc;
      }
    }
    func_0x005bd8d0(unaff_r26,*(undefined2 *)(uVar10 * 2 + *(int *)(iVar7 + -0x7fe8) + 0x78),0x23a);
LAB_005fa9cc:
    func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
    return;
  }
  iVar7 = *(int *)(iVar7 + -0x797c);
  func_0x0054bd6c(unaff_r26);
  if (0 < *(int *)(unaff_r26 + 0x17c)) {
    iVar12 = *(int *)(iVar7 + -0x7fe8);
    puVar8 = (undefined2 *)(iVar12 + 0x82);
    uVar11 = 0;
    iVar5 = 0x96;
    do {
      uVar3 = uVar11 ^ *(uint *)(unaff_r26 + 0x44);
      uVar6 = (ulonglong)((int)uVar3 >> 0x1f);
      func_0x005bd968(&stack0x00000040,unaff_r26,((uVar6 ^ uVar3) - uVar6) - 1 >> 0x1f & 1,0xff,0);
      uVar3 = uVar11 ^ *(uint *)(unaff_r26 + 0x44);
      uVar6 = (ulonglong)((int)uVar3 >> 0x1f);
      uVar14 = func_0x005bb950(unaff_r26,((uVar6 ^ uVar3) - uVar6) - 1 >> 0x1f & 1);
      uVar10 = (uint)uVar11;
      if (uVar10 == 0) {
        if (*(int *)(unaff_r26 + 0x178) == 0) goto LAB_005fabf8;
        uVar9 = *(undefined2 *)(*(int *)(unaff_r26 + 0x178) * 2 + iVar12 + 0x90);
LAB_005faad0:
        uVar2 = *(uint *)(unaff_r26 + 0x44);
      }
      else {
        if ((uVar10 == 7) && (uVar9 = 0x325, *(char *)(unaff_r26 + 0x184) != '\0'))
        goto LAB_005faad0;
LAB_005fabf8:
        uVar2 = *(uint *)(unaff_r26 + 0x44);
        uVar9 = *puVar8;
      }
      if ((uVar2 == uVar10) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
        func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
      }
      if (((1 << (uVar10 & 0x3f) & *(uint *)(unaff_r26 + 0x180)) == 0) && (uVar10 == 6)) {
        uVar9 = 0x331;
      }
      puVar8 = puVar8 + 1;
      func_0x005bc9d0(uVar14,unaff_r26,uVar9,0x280,iVar5,&stack0x00000044);
      uVar3 = uVar11 ^ *(uint *)(unaff_r26 + 0x44);
      uVar6 = (ulonglong)((int)uVar3 >> 0x1f);
      iVar13 = (int)(uVar11 + 1);
      func_0x005bdbd8(unaff_r26,iVar13,uVar9,((uVar6 ^ uVar3) - uVar6) - 1 >> 0x1f & 1,
                      0xffffffffffffffff);
      uVar11 = uVar11 + 1;
      iVar5 = iVar5 + 0x32;
    } while (iVar13 < *(int *)(unaff_r26 + 0x17c));
  }
  iVar12 = *(int *)(unaff_r26 + 0x44);
  if (iVar12 == 6) {
    if ((*(uint *)(unaff_r26 + 0x180) & 0x40) == 0) goto LAB_005facc4;
LAB_005fac9c:
    uVar9 = *(undefined2 *)(iVar12 * 2 + *(int *)(iVar7 + -0x7fe8) + 0x98);
  }
  else {
    if (iVar12 != 0) {
      if (iVar12 == 7) {
        uVar9 = 0x32f;
        if (*(char *)(unaff_r26 + 0x184) != '\0') goto LAB_005facb0;
      }
      else if (7 < iVar12) goto LAB_005facc4;
      goto LAB_005fac9c;
    }
    if (*(int *)(unaff_r26 + 0x178) == 0) goto LAB_005fac9c;
    uVar9 = *(undefined2 *)(*(int *)(unaff_r26 + 0x178) * 2 + *(int *)(iVar7 + -0x7fe8) + 0xa6);
  }
LAB_005facb0:
  func_0x005bd8d0(unaff_r26,uVar9,0x23a);
LAB_005facc4:
  func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
  return;
}


