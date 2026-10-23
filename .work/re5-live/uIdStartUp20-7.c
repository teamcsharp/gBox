
void FUN_00613940(int param_1)

{
  byte bVar1;
  float fVar2;
  int *piVar3;
  undefined4 *puVar4;
  uint uVar5;
  float fVar6;
  uint uVar7;
  uint uVar8;
  char cVar11;
  int iVar9;
  undefined4 uVar10;
  ulonglong uVar12;
  ulonglong uVar13;
  int iVar14;
  undefined1 *puVar15;
  undefined1 auStack_80 [4];
  undefined1 auStack_7c [4];
  undefined1 auStack_78 [8];
  undefined1 auStack_70 [32];
  
  iVar9 = iRam01714c1c;
  iVar14 = 0x171c590;
  uVar7 = FUN_0054bad0(param_1);
  uVar8 = FUN_0054c2cc(param_1);
  piVar3 = *(int **)(iVar9 + -0x7fec);
  *(undefined4 *)(param_1 + 0x184) = 0;
  if ((*(uint *)(*piVar3 + *(int *)(*piVar3 + 0x24) * 0x7eb8 + 0xa4) & 4) != 0) {
    *(undefined4 *)(param_1 + 0x184) = 1;
  }
  cVar11 = func_0x00ef73e4(**(undefined4 **)(iVar9 + -0x7e58));
  if (cVar11 != '\0') {
    *(uint *)(param_1 + 0x184) = *(uint *)(param_1 + 0x184) | 2;
  }
  puVar4 = *(undefined4 **)(iVar9 + -0x7ff4);
  *(undefined4 *)(param_1 + 0x188) = 5;
  cVar11 = func_0x001060e0(*puVar4);
  if (cVar11 == '\0') {
    *(uint *)(param_1 + 0x188) = *(uint *)(param_1 + 0x188) | 2;
  }
  bVar1 = *(byte *)(param_1 + 0x17);
  if (bVar1 == 10) {
    puVar4 = *(undefined4 **)(iVar9 + -0x7fd0);
    func_0x0013e848(*puVar4,0x36,4,0);
    if (((uVar7 & *(uint *)(**(int **)(iVar9 + -0x7fd4) + 0x1ea0)) == 0) && ((uVar8 & 0x200) == 0))
    {
      uVar5 = *(uint *)(**(int **)(iVar9 + -0x7fd4) + 0x1ea4);
      if (((uVar7 & uVar5) == 0) && ((uVar8 & uVar5) == 0)) {
        uVar10 = func_0x0054cbf0(param_1,*(undefined4 *)(param_1 + 0x178),3);
        iVar9 = func_0x0013fd34(*puVar4,uVar10,3,0,4,0);
        if (*(int *)(param_1 + 0x178) != iVar9) {
          *(int *)(param_1 + 0x178) = iVar9;
          func_0x0054bff8(param_1);
        }
      }
      else {
        func_0x0013e454(*puVar4,4,0,1);
        func_0x0054c038(param_1);
        *(undefined4 *)(param_1 + 0x174) = 0;
        *(undefined1 *)(param_1 + 0x17) = 2;
      }
      goto LAB_0060f8c0;
    }
    if ((1 << (*(uint *)(param_1 + 0x178) & 0x3f) & *(uint *)(param_1 + 0x188)) == 0) {
LAB_00613cbc:
      func_0x0054bf78(param_1);
      goto LAB_0060f8c0;
    }
    func_0x0013e454(*puVar4,4,0,1);
    *(undefined4 *)(*(int *)(**(int **)(iVar9 + -0x7ff8) + 0x182d4) + 0x340) =
         *(undefined4 *)(param_1 + 0x178);
    func_0x0054c178(param_1);
LAB_00613bf0:
    *(undefined4 *)(param_1 + 0x40) = *(undefined4 *)(iVar9 + -0x7f44);
    *(undefined1 *)(param_1 + 0x39) = 1;
    *(char *)(param_1 + 0x17) = *(char *)(param_1 + 0x17) + '\x01';
  }
  else {
    if (bVar1 < 0xb) {
      if (bVar1 != 1) {
        if (bVar1 == 0) {
          func_0x005bcaa8(param_1,0);
          *(char *)(param_1 + 0x17) = *(char *)(param_1 + 0x17) + '\x01';
          goto LAB_0060f8c0;
        }
        if (bVar1 != 2) {
          if ((bVar1 != 3) ||
             (fVar2 = *(float *)(iVar9 + -0x7f38),
             fVar6 = *(float *)(param_1 + 0x40) - *(float *)(**(int **)(iVar9 + -0x7f3c) + 0x2c),
             *(float *)(param_1 + 0x40) = fVar6, fVar2 < fVar6)) goto LAB_0060f8c0;
          *(undefined1 *)(param_1 + 0x39) = 0;
          if (*(int *)(param_1 + 0x44) == 0) {
            *(undefined4 *)(param_1 + 0x174) = 1;
            *(undefined1 *)(param_1 + 0x17) = 10;
            *(undefined4 *)(param_1 + 0x178) = 0;
            goto LAB_0060f8c0;
          }
          puVar4 = *(undefined4 **)(iVar9 + -0x7e80);
          goto LAB_00613e30;
        }
        puVar4 = *(undefined4 **)(iVar9 + -0x7fd0);
        func_0x0013e848(*puVar4,0x1b,4,0);
        if (((uVar7 & *(uint *)(**(int **)(iVar9 + -0x7fd4) + 0x1ea0)) == 0) &&
           ((uVar8 & 0x200) == 0)) {
          uVar5 = *(uint *)(**(int **)(iVar9 + -0x7fd4) + 0x1ea4);
          if (((uVar7 & uVar5) == 0) && ((uVar8 & uVar5) == 0)) {
            uVar8 = func_0x0013fd34(*puVar4,*(undefined4 *)(param_1 + 0x44),2,0,4,0);
            if (((uVar7 & 0x40040) != 0) && (uVar8 = uVar8 + 1, 1 < (int)uVar8)) {
              uVar8 = 1;
            }
            if ((uVar7 & 0x10010) != 0) {
              uVar8 = uVar8 - 1 & (int)~(uVar8 - 1) >> 0x1f;
            }
            if (*(uint *)(param_1 + 0x44) != uVar8) {
              *(uint *)(param_1 + 0x44) = uVar8;
              func_0x0054bff8(param_1);
            }
          }
          else {
            func_0x0013e454(*puVar4,4,0,1);
            func_0x0054c138(param_1);
            *(undefined1 *)(param_1 + 0x3a) = 1;
            func_0x005bc8fc(param_1,0x62,1);
            *(undefined1 *)(param_1 + 0x17) = 0x5a;
          }
          goto LAB_0060f8c0;
        }
        if ((1 << (*(uint *)(param_1 + 0x44) & 0x3f) & *(uint *)(param_1 + 0x184)) == 0)
        goto LAB_00613cbc;
        func_0x0013e454(*puVar4,4,0,1);
        *(undefined4 *)(*(int *)(**(int **)(iVar9 + -0x7ff8) + 0x182d4) + 0x33c) =
             *(undefined4 *)(param_1 + 0x44);
        func_0x0054c0b8(param_1);
        goto LAB_00613bf0;
      }
      cVar11 = func_0x005bdb2c(param_1,0);
      if (cVar11 == '\0') goto LAB_0060f8c0;
      if (*(int *)(param_1 + 0x174) != 0) {
        *(undefined1 *)(param_1 + 0x17) = 10;
        goto LAB_0060f8c0;
      }
    }
    else {
      if (bVar1 == 0x5a) {
        func_0x005bca34(param_1,0);
        *(char *)(param_1 + 0x17) = *(char *)(param_1 + 0x17) + '\x01';
        goto LAB_0060f8c0;
      }
      if (bVar1 < 0x5b) {
        if ((bVar1 != 0xb) ||
           (fVar2 = *(float *)(iVar9 + -0x7f38),
           fVar6 = *(float *)(param_1 + 0x40) - *(float *)(**(int **)(iVar9 + -0x7f3c) + 0x2c),
           *(float *)(param_1 + 0x40) = fVar6, fVar2 < fVar6)) goto LAB_0060f8c0;
        puVar4 = *(undefined4 **)(iVar9 + -0x7e80);
        *(undefined1 *)(param_1 + 0x39) = 0;
LAB_00613e30:
        uVar10 = func_0x000bbe20(*puVar4);
        func_0x0001112c(uVar10);
        *(undefined1 *)(param_1 + 0x17) = 0x5a;
        goto LAB_0060f8c0;
      }
      if (bVar1 != 0x5b) {
        if (bVar1 == 0x5c) {
          *(undefined1 *)(param_1 + 0x38) = 1;
          return;
        }
        goto LAB_0060f8c0;
      }
      cVar11 = func_0x005bd19c(param_1,0);
      if (cVar11 == '\0') goto LAB_0060f8c0;
    }
    *(char *)(param_1 + 0x17) = *(char *)(param_1 + 0x17) + '\x01';
  }
LAB_0060f8c0:
  iVar9 = *(int *)(iVar14 + -0x7974);
  func_0x0054bd6c();
  cVar11 = func_0x005bb910(param_1,0,0xff,0);
  if (cVar11 == '\0') {
    return;
  }
  func_0x0054d468(param_1,cVar11);
  func_0x0054d264(param_1,*(undefined4 *)(iVar9 + -0x7f10));
  if (*(int *)(param_1 + 0x174) != 0) {
    iVar9 = *(int *)(iVar14 + -0x7974);
    func_0x00550098(param_1,*(undefined4 *)(iVar9 + -0x7fe8),auStack_78);
    iVar14 = *(int *)(param_1 + 0x17c);
    if (0 < iVar14) {
      uVar7 = 0;
      puVar15 = *(undefined1 **)(iVar9 + -0x7f2c);
      do {
        while( true ) {
          uVar8 = uVar7 & 0x3f;
          uVar7 = uVar7 + 1;
          if ((1 << uVar8 & *(uint *)(param_1 + 0x180)) == 0) break;
          func_0x00fe6bbc(auStack_70,*(undefined4 *)(iVar9 + -0x7f28),*puVar15);
          func_0x00550098(param_1,auStack_70,auStack_78);
          iVar14 = *(int *)(param_1 + 0x17c);
          puVar15 = puVar15 + 0x40;
          if (iVar14 <= (int)uVar7) goto LAB_0060f030;
        }
        puVar15 = puVar15 + 0x40;
      } while ((int)uVar7 < iVar14);
    }
LAB_0060f030:
    func_0x0054d3f0(param_1,*(undefined4 *)(iVar9 + -0x7f24),6);
    uVar12 = (ulonglong)((int)*(uint *)(param_1 + 0x178) >> 0x1f);
    uVar12 = ((uVar12 ^ *(uint *)(param_1 + 0x178)) - uVar12) - 1;
    func_0x005bd968(auStack_7c,param_1,uVar12 >> 0x1f & 1,0xff,0);
    if ((*(int *)(param_1 + 0x178) == 0) && (*(char *)(param_1 + 0x39) != '\0')) {
      func_0x0054ba04((double)*(float *)(param_1 + 0x40),param_1);
    }
    func_0x0054d9e0(param_1,((int)uVar12 >> 0x1f & 6U) + 0x1e,0x280,0x160,auStack_78,0x6f1,0x60,
                    0xffffffffffffffff);
    uVar12 = (ulonglong)((int)*(uint *)(param_1 + 0x178) >> 0x1f);
    func_0x005bdbd8(param_1,3,0x6f1,((uVar12 ^ *(uint *)(param_1 + 0x178)) - uVar12) - 1 >> 0x1f & 1
                    ,0xffffffffffffffff);
    uVar12 = (ulonglong)*(uint *)(param_1 + 0x178) ^ 1;
    uVar13 = (ulonglong)((int)uVar12 >> 0x1f);
    uVar12 = ((uVar13 ^ uVar12) - uVar13) - 1;
    func_0x005bd968(auStack_7c,param_1,uVar12 >> 0x1f & 1,0xff,0);
    if ((*(int *)(param_1 + 0x178) == 1) && (*(char *)(param_1 + 0x39) != '\0')) {
      func_0x0054ba04((double)*(float *)(param_1 + 0x40),param_1);
    }
    func_0x0054d9e0(param_1,((int)uVar12 >> 0x1f & 6U) + 0x1e,0x280,0x188,auStack_78,0x6f2,0x60,
                    0xffffffffffffffff);
    uVar12 = (ulonglong)*(uint *)(param_1 + 0x178) ^ 1;
    uVar13 = (ulonglong)((int)uVar12 >> 0x1f);
    func_0x005bdbd8(param_1,4,0x6f2,((uVar13 ^ uVar12) - uVar13) - 1 >> 0x1f & 1,0xffffffffffffffff)
    ;
    uVar12 = (ulonglong)*(uint *)(param_1 + 0x178) ^ 2;
    uVar13 = (ulonglong)((int)uVar12 >> 0x1f);
    uVar12 = ((uVar13 ^ uVar12) - uVar13) - 1;
    func_0x005bd968(auStack_7c,param_1,uVar12 >> 0x1f & 1,0xff,0);
    if ((*(int *)(param_1 + 0x178) == 2) && (*(char *)(param_1 + 0x39) != '\0')) {
      func_0x0054ba04((double)*(float *)(param_1 + 0x40),param_1);
    }
    func_0x0054d9e0(param_1,((int)uVar12 >> 0x1f & 6U) + 0x1e,0x280,0x1b0,auStack_78,0x739,0x60,
                    0xffffffffffffffff);
    uVar12 = (ulonglong)*(uint *)(param_1 + 0x178) ^ 2;
    uVar13 = (ulonglong)((int)uVar12 >> 0x1f);
    func_0x005bdbd8(param_1,5,0x739,((uVar13 ^ uVar12) - uVar13) - 1 >> 0x1f & 1,0xffffffffffffffff)
    ;
    func_0x005bb910(param_1,0,0xff,0);
    func_0x0054d9e0(param_1,0x2d,0x280,0x60,auStack_78,0x6f0,0x60,0xffffffffffffffff);
    func_0x005bd8d0(param_1,*(undefined2 *)
                             (*(int *)(param_1 + 0x178) * 2 + *(int *)(iVar9 + -0x7ffc) + 0xfc),
                    0x20f);
    func_0x005bd24c(param_1,0,0xffffffffffffffff);
    return;
  }
  iVar9 = *(int *)(iVar14 + -0x7974);
  iVar14 = *(int *)(**(int **)(iVar9 + -0x7fec) +
                    *(int *)(**(int **)(iVar9 + -0x7fec) + 0x24) * 0x7eb8 + 0x7c);
  func_0x00550098(param_1,*(undefined4 *)(iVar9 + -0x7fe8),auStack_7c);
  uVar10 = *(undefined4 *)(iVar9 + -0x7f28);
  iVar14 = iVar14 + *(int *)(iVar9 + -0x7ffc);
  func_0x00fe6bbc(auStack_78,uVar10,*(undefined1 *)(iVar14 + 0x108));
  func_0x0054d264(param_1,auStack_78);
  func_0x00fe6bbc(auStack_78,uVar10,*(undefined1 *)(iVar14 + 0x110));
  func_0x0054d264(param_1,auStack_78);
  func_0x0054d264(param_1,*(undefined4 *)(iVar9 + -0x7f20));
  func_0x0054d264(param_1,*(undefined4 *)(iVar9 + -0x7f1c));
  func_0x0054d264(param_1,*(undefined4 *)(iVar9 + -0x7f18));
  iVar14 = *(int *)(param_1 + 0x17c);
  if (0 < iVar14) {
    uVar7 = 0;
    puVar15 = *(undefined1 **)(iVar9 + -0x7f2c);
    do {
      while( true ) {
        uVar8 = uVar7 & 0x3f;
        uVar7 = uVar7 + 1;
        if ((1 << uVar8 & *(uint *)(param_1 + 0x180)) == 0) break;
        func_0x00fe6bbc(auStack_78,uVar10,*puVar15);
        func_0x00550098(param_1,auStack_78,auStack_7c);
        iVar14 = *(int *)(param_1 + 0x17c);
        puVar15 = puVar15 + 0x40;
        if (iVar14 <= (int)uVar7) goto LAB_0060f638;
      }
      puVar15 = puVar15 + 0x40;
    } while ((int)uVar7 < iVar14);
  }
LAB_0060f638:
  uVar12 = (ulonglong)((int)*(uint *)(param_1 + 0x44) >> 0x1f);
  uVar12 = ((uVar12 ^ *(uint *)(param_1 + 0x44)) - uVar12) - 1;
  func_0x005bd968(auStack_80,param_1,uVar12 >> 0x1f & 1,0xff,0);
  if ((*(int *)(param_1 + 0x44) == 0) && (*(char *)(param_1 + 0x39) != '\0')) {
    func_0x0054ba04((double)*(float *)(param_1 + 0x40),param_1);
  }
  func_0x0054d9e0(param_1,((int)uVar12 >> 0x1f & 6U) + 0x1e,0x280,0x1e2,auStack_7c,0x6ec,0x60,
                  0xffffffffffffffff);
  uVar12 = (ulonglong)((int)*(uint *)(param_1 + 0x44) >> 0x1f);
  func_0x005bdbd8(param_1,1,0x6ec,((uVar12 ^ *(uint *)(param_1 + 0x44)) - uVar12) - 1 >> 0x1f & 1,
                  0xffffffffffffffff);
  uVar12 = (ulonglong)*(uint *)(param_1 + 0x44) ^ 1;
  uVar13 = (ulonglong)((int)uVar12 >> 0x1f);
  uVar12 = ((uVar13 ^ uVar12) - uVar13) - 1;
  func_0x005bd968(auStack_80,param_1,uVar12 >> 0x1f & 1,0xff,0);
  if ((*(int *)(param_1 + 0x44) == 1) && (*(char *)(param_1 + 0x39) != '\0')) {
    func_0x0054ba04((double)*(float *)(param_1 + 0x40),param_1);
  }
  func_0x0054d9e0(param_1,((int)uVar12 >> 0x1f & 6U) + 0x1e,0x280,0x224,auStack_7c,0x6ed,0x60,
                  0xffffffffffffffff);
  uVar12 = (ulonglong)*(uint *)(param_1 + 0x44) ^ 1;
  uVar13 = (ulonglong)((int)uVar12 >> 0x1f);
  func_0x005bdbd8(param_1,2,0x6ed,((uVar13 ^ uVar12) - uVar13) - 1 >> 0x1f & 1,0xffffffffffffffff);
  func_0x005bd24c(param_1,0,0xffffffffffffffff);
  return;
}


