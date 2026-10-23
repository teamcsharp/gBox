
void FUN_006001e8(void)

{
  uint uVar1;
  ulonglong uVar2;
  char cVar3;
  ulonglong uVar4;
  int iVar5;
  undefined2 *puVar6;
  int *unaff_r25;
  int iVar7;
  int unaff_r26;
  undefined2 uVar8;
  uint uVar9;
  int iVar11;
  ulonglong uVar10;
  int iVar12;
  int unaff_r31;
  undefined8 uVar13;
  
  iVar5 = 0x171c590;
  func_0x005bcaa8(unaff_r26,0);
  *(char *)(unaff_r31 + 0x17) = *(char *)(unaff_r31 + 0x17) + '\x01';
  if ((*(uint *)(*unaff_r25 + 0x182dc) & 1) != 0) {
    iVar5 = *(int *)(iVar5 + -0x797c);
    func_0x0054bd6c(unaff_r26);
    if (*(int *)(unaff_r26 + 0x17c) < 1) {
      iVar5 = *(int *)(iVar5 + -0x7fe8);
    }
    else {
      iVar5 = *(int *)(iVar5 + -0x7fe8);
      uVar10 = 0;
      iVar7 = 300;
      puVar6 = (undefined2 *)(iVar5 + 0x62);
      do {
        uVar2 = uVar10 ^ *(uint *)(unaff_r26 + 0x44);
        uVar4 = (ulonglong)((int)uVar2 >> 0x1f);
        func_0x005bd968(&stack0x00000040,unaff_r26,((uVar4 ^ uVar2) - uVar4) - 1 >> 0x1f & 1,0xff,0)
        ;
        uVar2 = uVar10 ^ *(uint *)(unaff_r26 + 0x44);
        uVar4 = (ulonglong)((int)uVar2 >> 0x1f);
        uVar13 = func_0x005bb950(unaff_r26,((uVar4 ^ uVar2) - uVar4) - 1 >> 0x1f & 1);
        iVar11 = (int)uVar10;
        uVar8 = *puVar6;
        if ((*(int *)(unaff_r26 + 0x44) == iVar11) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
          func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
        }
        func_0x005bc9d0(uVar13,unaff_r26,uVar8,0x280,iVar7,&stack0x00000044);
        uVar2 = uVar10 ^ *(uint *)(unaff_r26 + 0x44);
        uVar4 = (ulonglong)((int)uVar2 >> 0x1f);
        uVar10 = uVar10 + 1;
        func_0x005bdbd8(unaff_r26,iVar11 + 4,uVar8,((uVar4 ^ uVar2) - uVar4) - 1 >> 0x1f & 1,
                        0xffffffffffffffff);
        iVar7 = iVar7 + 0x32;
        puVar6 = puVar6 + 1;
      } while ((int)uVar10 < *(int *)(unaff_r26 + 0x17c));
    }
    func_0x005bd8d0(unaff_r26,*(undefined2 *)(*(int *)(unaff_r26 + 0x44) * 2 + iVar5 + 0x68),0x23a);
    func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
    return;
  }
  if (*(int *)(unaff_r31 + 0x174) != 0) {
    iVar5 = *(int *)(iVar5 + -0x797c);
    func_0x0054bd6c(unaff_r26);
    if (0 < *(int *)(unaff_r26 + 0x18c)) {
      uVar10 = 0;
      puVar6 = (undefined2 *)(*(int *)(iVar5 + -0x7fe8) + 0x6e);
      iVar7 = 0xfa;
      do {
        uVar2 = uVar10 ^ *(uint *)(unaff_r26 + 0x188);
        uVar4 = (ulonglong)((int)uVar2 >> 0x1f);
        func_0x005bd968(&stack0x00000050,unaff_r26,((uVar4 ^ uVar2) - uVar4) - 1 >> 0x1f & 1,0xff,0)
        ;
        uVar2 = uVar10 ^ *(uint *)(unaff_r26 + 0x188);
        uVar4 = (ulonglong)((int)uVar2 >> 0x1f);
        uVar13 = func_0x005bb950(unaff_r26,((uVar4 ^ uVar2) - uVar4) - 1 >> 0x1f & 1);
        uVar9 = (uint)uVar10;
        uVar8 = *puVar6;
        if ((*(uint *)(unaff_r26 + 0x188) == uVar9) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
          func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
        }
        if ((*(int *)(unaff_r26 + 400) >> (uVar9 & 0x3f) & 1U) == 0) {
          cVar3 = func_0x000dbff4(**(undefined4 **)(iVar5 + -0x7fa4));
          if ((cVar3 != '\0') && (0 < (int)uVar9)) {
            uVar8 = 0x331;
          }
        }
        puVar6 = puVar6 + 1;
        func_0x005bc9d0(uVar13,unaff_r26,uVar8,0x280,iVar7,&stack0x00000054);
        uVar2 = uVar10 ^ *(uint *)(unaff_r26 + 0x188);
        uVar4 = (ulonglong)((int)uVar2 >> 0x1f);
        uVar10 = uVar10 + 1;
        func_0x005bdbd8(unaff_r26,uVar9 + 3,uVar8,((uVar4 ^ uVar2) - uVar4) - 1 >> 0x1f & 1,
                        0xffffffffffffffff);
        iVar7 = iVar7 + 0x32;
      } while ((int)uVar10 < *(int *)(unaff_r26 + 0x18c));
    }
    uVar9 = *(uint *)(unaff_r26 + 0x188);
    if ((*(int *)(unaff_r26 + 400) >> (uVar9 & 0x3f) & 1U) == 0) {
      cVar3 = func_0x000dbff4(**(undefined4 **)(iVar5 + -0x7fa4));
      if (cVar3 == '\0') {
        uVar9 = *(uint *)(unaff_r26 + 0x188);
      }
      else {
        uVar9 = 0;
        if (*(int *)(unaff_r26 + 0x188) != 0) goto LAB_005fa9cc;
      }
    }
    func_0x005bd8d0(unaff_r26,*(undefined2 *)(uVar9 * 2 + *(int *)(iVar5 + -0x7fe8) + 0x78),0x23a);
LAB_005fa9cc:
    func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
    return;
  }
  iVar5 = *(int *)(iVar5 + -0x797c);
  func_0x0054bd6c(unaff_r26);
  if (0 < *(int *)(unaff_r26 + 0x17c)) {
    iVar7 = *(int *)(iVar5 + -0x7fe8);
    puVar6 = (undefined2 *)(iVar7 + 0x82);
    uVar10 = 0;
    iVar11 = 0x96;
    do {
      uVar2 = uVar10 ^ *(uint *)(unaff_r26 + 0x44);
      uVar4 = (ulonglong)((int)uVar2 >> 0x1f);
      func_0x005bd968(&stack0x00000040,unaff_r26,((uVar4 ^ uVar2) - uVar4) - 1 >> 0x1f & 1,0xff,0);
      uVar2 = uVar10 ^ *(uint *)(unaff_r26 + 0x44);
      uVar4 = (ulonglong)((int)uVar2 >> 0x1f);
      uVar13 = func_0x005bb950(unaff_r26,((uVar4 ^ uVar2) - uVar4) - 1 >> 0x1f & 1);
      uVar9 = (uint)uVar10;
      if (uVar9 == 0) {
        if (*(int *)(unaff_r26 + 0x178) == 0) goto LAB_005fabf8;
        uVar8 = *(undefined2 *)(*(int *)(unaff_r26 + 0x178) * 2 + iVar7 + 0x90);
LAB_005faad0:
        uVar1 = *(uint *)(unaff_r26 + 0x44);
      }
      else {
        if ((uVar9 == 7) && (uVar8 = 0x325, *(char *)(unaff_r26 + 0x184) != '\0'))
        goto LAB_005faad0;
LAB_005fabf8:
        uVar1 = *(uint *)(unaff_r26 + 0x44);
        uVar8 = *puVar6;
      }
      if ((uVar1 == uVar9) && (*(char *)(unaff_r26 + 0x39) != '\0')) {
        func_0x0054ba04((double)*(float *)(unaff_r26 + 0x40),unaff_r26);
      }
      if (((1 << (uVar9 & 0x3f) & *(uint *)(unaff_r26 + 0x180)) == 0) && (uVar9 == 6)) {
        uVar8 = 0x331;
      }
      puVar6 = puVar6 + 1;
      func_0x005bc9d0(uVar13,unaff_r26,uVar8,0x280,iVar11,&stack0x00000044);
      uVar2 = uVar10 ^ *(uint *)(unaff_r26 + 0x44);
      uVar4 = (ulonglong)((int)uVar2 >> 0x1f);
      iVar12 = (int)(uVar10 + 1);
      func_0x005bdbd8(unaff_r26,iVar12,uVar8,((uVar4 ^ uVar2) - uVar4) - 1 >> 0x1f & 1,
                      0xffffffffffffffff);
      uVar10 = uVar10 + 1;
      iVar11 = iVar11 + 0x32;
    } while (iVar12 < *(int *)(unaff_r26 + 0x17c));
  }
  iVar7 = *(int *)(unaff_r26 + 0x44);
  if (iVar7 == 6) {
    if ((*(uint *)(unaff_r26 + 0x180) & 0x40) == 0) goto LAB_005facc4;
LAB_005fac9c:
    uVar8 = *(undefined2 *)(iVar7 * 2 + *(int *)(iVar5 + -0x7fe8) + 0x98);
  }
  else {
    if (iVar7 != 0) {
      if (iVar7 == 7) {
        uVar8 = 0x32f;
        if (*(char *)(unaff_r26 + 0x184) != '\0') goto LAB_005facb0;
      }
      else if (7 < iVar7) goto LAB_005facc4;
      goto LAB_005fac9c;
    }
    if (*(int *)(unaff_r26 + 0x178) == 0) goto LAB_005fac9c;
    uVar8 = *(undefined2 *)(*(int *)(unaff_r26 + 0x178) * 2 + *(int *)(iVar5 + -0x7fe8) + 0xa6);
  }
LAB_005facb0:
  func_0x005bd8d0(unaff_r26,uVar8,0x23a);
LAB_005facc4:
  func_0x005bd24c(unaff_r26,0,0xffffffffffffffff);
  return;
}


