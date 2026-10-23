
void FUN_006002f0(void)

{
  float fVar1;
  uint uVar2;
  float fVar3;
  ulonglong uVar4;
  char cVar5;
  ulonglong uVar6;
  char in_r10;
  int iVar7;
  undefined2 *puVar8;
  int *unaff_r25;
  int iVar9;
  int unaff_r26;
  undefined2 uVar10;
  uint uVar11;
  int iVar13;
  ulonglong uVar12;
  int unaff_r30;
  int iVar14;
  int unaff_r31;
  undefined8 uVar15;
  undefined8 uStack00000068;
  undefined8 in_stack_00000070;
  
  fVar1 = *(float *)(unaff_r30 + -0x7f50);
  fVar3 = *(float *)(unaff_r31 + 0x40) - *(float *)(**(int **)(unaff_r30 + -0x7e70) + 0x2c);
  *(float *)(unaff_r31 + 0x40) = fVar3;
  if (fVar3 <= fVar1) {
    *(undefined1 *)(unaff_r31 + 0x39) = 0;
    *(undefined4 *)(unaff_r31 + 0x174) = 1;
    *(char *)(unaff_r31 + 0x17) = in_r10 + '\x01';
  }
  iVar7 = iRam01714c14;
  if ((*(uint *)(*unaff_r25 + 0x182dc) & 1) != 0) {
    uStack00000068 = in_stack_00000070;
    func_0x0054bd6c(unaff_r26);
    if (*(int *)(unaff_r26 + 0x17c) < 1) {
      iVar7 = *(int *)(iVar7 + -0x7fe8);
    }
    else {
      iVar7 = *(int *)(iVar7 + -0x7fe8);
      uVar12 = 0;
      iVar9 = 300;
      puVar8 = (undefined2 *)(iVar7 + 0x62);
      do {
        uVar4 = uVar12 ^ *(uint *)(unaff_r26 + 0x44);
        uVar6 = (ulonglong)((int)uVar4 >> 0x1f);
        func_0x005bd968(&stack0x00000040,unaff_r26,((uVar6 ^ uVar4) - uVar6) - 1 >> 0x1f & 1,0xff,0)
        ;
        uVar4 = uVar12 ^ *(uint *)(unaff_r26 + 0x44);
        uVar6 = (ulonglong)((int)uVar4 >> 0x1f);
        uVar15 = func_0x005bb950(unaff_r26,((uVar6 ^ uVar4) - uVar6) - 1 >> 0x1f & 1);
        iVar13 = (int)uVar12;
        uVar10 = *puVar8;
        if ((*(int *)(unaff_r26 + 0x44) == iVar13) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
          func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
        }
        func_0x005bc9d0(uVar15,unaff_r26,uVar10,0x280,iVar9,&stack0x00000044);
        uVar4 = uVar12 ^ *(uint *)(unaff_r26 + 0x44);
        uVar6 = (ulonglong)((int)uVar4 >> 0x1f);
        uVar12 = uVar12 + 1;
        func_0x005bdbd8(unaff_r26,iVar13 + 4,uVar10,((uVar6 ^ uVar4) - uVar6) - 1 >> 0x1f & 1,
                        0xffffffffffffffff);
        iVar9 = iVar9 + 0x32;
        puVar8 = puVar8 + 1;
      } while ((int)uVar12 < *(int *)(unaff_r26 + 0x17c));
    }
    func_0x005bd8d0(unaff_r26,*(undefined2 *)(*(int *)(unaff_r26 + 0x44) * 2 + iVar7 + 0x68),0x23a);
    func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
    return;
  }
  if (*(int *)(unaff_r31 + 0x174) != 0) {
    uStack00000068 = in_stack_00000070;
    func_0x0054bd6c(unaff_r26);
    if (0 < *(int *)(unaff_r26 + 0x18c)) {
      uVar12 = 0;
      puVar8 = (undefined2 *)(*(int *)(iVar7 + -0x7fe8) + 0x6e);
      iVar9 = 0xfa;
      do {
        uVar4 = uVar12 ^ *(uint *)(unaff_r26 + 0x188);
        uVar6 = (ulonglong)((int)uVar4 >> 0x1f);
        func_0x005bd968(&stack0x00000050,unaff_r26,((uVar6 ^ uVar4) - uVar6) - 1 >> 0x1f & 1,0xff,0)
        ;
        uVar4 = uVar12 ^ *(uint *)(unaff_r26 + 0x188);
        uVar6 = (ulonglong)((int)uVar4 >> 0x1f);
        uVar15 = func_0x005bb950(unaff_r26,((uVar6 ^ uVar4) - uVar6) - 1 >> 0x1f & 1);
        uVar11 = (uint)uVar12;
        uVar10 = *puVar8;
        if ((*(uint *)(unaff_r26 + 0x188) == uVar11) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
          func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
        }
        if ((*(int *)(unaff_r26 + 400) >> (uVar11 & 0x3f) & 1U) == 0) {
          cVar5 = func_0x000dbff4(**(undefined4 **)(iVar7 + -0x7fa4));
          if ((cVar5 != '\0') && (0 < (int)uVar11)) {
            uVar10 = 0x331;
          }
        }
        puVar8 = puVar8 + 1;
        func_0x005bc9d0(uVar15,unaff_r26,uVar10,0x280,iVar9,&stack0x00000054);
        uVar4 = uVar12 ^ *(uint *)(unaff_r26 + 0x188);
        uVar6 = (ulonglong)((int)uVar4 >> 0x1f);
        uVar12 = uVar12 + 1;
        func_0x005bdbd8(unaff_r26,uVar11 + 3,uVar10,((uVar6 ^ uVar4) - uVar6) - 1 >> 0x1f & 1,
                        0xffffffffffffffff);
        iVar9 = iVar9 + 0x32;
      } while ((int)uVar12 < *(int *)(unaff_r26 + 0x18c));
    }
    uVar11 = *(uint *)(unaff_r26 + 0x188);
    if ((*(int *)(unaff_r26 + 400) >> (uVar11 & 0x3f) & 1U) == 0) {
      cVar5 = func_0x000dbff4(**(undefined4 **)(iVar7 + -0x7fa4));
      if (cVar5 == '\0') {
        uVar11 = *(uint *)(unaff_r26 + 0x188);
      }
      else {
        uVar11 = 0;
        if (*(int *)(unaff_r26 + 0x188) != 0) goto LAB_005fa9cc;
      }
    }
    func_0x005bd8d0(unaff_r26,*(undefined2 *)(uVar11 * 2 + *(int *)(iVar7 + -0x7fe8) + 0x78),0x23a);
LAB_005fa9cc:
    func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
    return;
  }
  uStack00000068 = in_stack_00000070;
  func_0x0054bd6c(unaff_r26);
  if (0 < *(int *)(unaff_r26 + 0x17c)) {
    iVar9 = *(int *)(iVar7 + -0x7fe8);
    puVar8 = (undefined2 *)(iVar9 + 0x82);
    uVar12 = 0;
    iVar13 = 0x96;
    do {
      uVar4 = uVar12 ^ *(uint *)(unaff_r26 + 0x44);
      uVar6 = (ulonglong)((int)uVar4 >> 0x1f);
      func_0x005bd968(&stack0x00000040,unaff_r26,((uVar6 ^ uVar4) - uVar6) - 1 >> 0x1f & 1,0xff,0);
      uVar4 = uVar12 ^ *(uint *)(unaff_r26 + 0x44);
      uVar6 = (ulonglong)((int)uVar4 >> 0x1f);
      uVar15 = func_0x005bb950(unaff_r26,((uVar6 ^ uVar4) - uVar6) - 1 >> 0x1f & 1);
      uVar11 = (uint)uVar12;
      if (uVar11 == 0) {
        if (*(int *)(unaff_r26 + 0x178) == 0) goto LAB_005fabf8;
        uVar10 = *(undefined2 *)(*(int *)(unaff_r26 + 0x178) * 2 + iVar9 + 0x90);
LAB_005faad0:
        uVar2 = *(uint *)(unaff_r26 + 0x44);
      }
      else {
        if ((uVar11 == 7) && (uVar10 = 0x325, *(char *)(unaff_r26 + 0x184) != '\0'))
        goto LAB_005faad0;
LAB_005fabf8:
        uVar2 = *(uint *)(unaff_r26 + 0x44);
        uVar10 = *puVar8;
      }
      if ((uVar2 == uVar11) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
        func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
      }
      if (((1 << (uVar11 & 0x3f) & *(uint *)(unaff_r26 + 0x180)) == 0) && (uVar11 == 6)) {
        uVar10 = 0x331;
      }
      puVar8 = puVar8 + 1;
      func_0x005bc9d0(uVar15,unaff_r26,uVar10,0x280,iVar13,&stack0x00000044);
      uVar4 = uVar12 ^ *(uint *)(unaff_r26 + 0x44);
      uVar6 = (ulonglong)((int)uVar4 >> 0x1f);
      iVar14 = (int)(uVar12 + 1);
      func_0x005bdbd8(unaff_r26,iVar14,uVar10,((uVar6 ^ uVar4) - uVar6) - 1 >> 0x1f & 1,
                      0xffffffffffffffff);
      uVar12 = uVar12 + 1;
      iVar13 = iVar13 + 0x32;
    } while (iVar14 < *(int *)(unaff_r26 + 0x17c));
  }
  iVar9 = *(int *)(unaff_r26 + 0x44);
  if (iVar9 == 6) {
    if ((*(uint *)(unaff_r26 + 0x180) & 0x40) == 0) goto LAB_005facc4;
LAB_005fac9c:
    uVar10 = *(undefined2 *)(iVar9 * 2 + *(int *)(iVar7 + -0x7fe8) + 0x98);
  }
  else {
    if (iVar9 != 0) {
      if (iVar9 == 7) {
        uVar10 = 0x32f;
        if (*(char *)(unaff_r26 + 0x184) != '\0') goto LAB_005facb0;
      }
      else if (7 < iVar9) goto LAB_005facc4;
      goto LAB_005fac9c;
    }
    if (*(int *)(unaff_r26 + 0x178) == 0) goto LAB_005fac9c;
    uVar10 = *(undefined2 *)(*(int *)(unaff_r26 + 0x178) * 2 + *(int *)(iVar7 + -0x7fe8) + 0xa6);
  }
LAB_005facb0:
  func_0x005bd8d0(unaff_r26,uVar10,0x23a);
LAB_005facc4:
  func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
  return;
}


