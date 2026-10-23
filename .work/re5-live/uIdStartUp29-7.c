
void FUN_00614090(int param_1)

{
  byte bVar1;
  float fVar2;
  undefined4 *puVar3;
  uint uVar4;
  float fVar5;
  int iVar6;
  uint uVar7;
  uint uVar8;
  char cVar11;
  int iVar9;
  undefined4 uVar10;
  undefined1 auStack_50 [16];
  
  iVar9 = iRam01714c1c;
  iVar6 = 0x171c590;
  uVar7 = FUN_0054bad0(param_1);
  uVar8 = FUN_0054c2cc(param_1);
  puVar3 = *(undefined4 **)(iVar9 + -0x7e58);
  *(undefined4 *)(param_1 + 0x184) = 1;
  cVar11 = func_0x00ef73e4(*puVar3);
  if (cVar11 != '\0') {
    *(uint *)(param_1 + 0x184) = *(uint *)(param_1 + 0x184) | 2;
  }
  puVar3 = *(undefined4 **)(iVar9 + -0x7ff4);
  *(undefined4 *)(param_1 + 0x188) = 5;
  cVar11 = func_0x001060e0(*puVar3);
  if (cVar11 == '\0') {
    *(uint *)(param_1 + 0x188) = *(uint *)(param_1 + 0x188) | 2;
  }
  bVar1 = *(byte *)(param_1 + 0x17);
  if (bVar1 == 10) {
    puVar3 = *(undefined4 **)(iVar9 + -0x7fd0);
    func_0x0013e848(*puVar3,0x36,4,0);
    if (((uVar7 & *(uint *)(**(int **)(iVar9 + -0x7fd4) + 0x1ea0)) == 0) && ((uVar8 & 0x200) == 0))
    {
      uVar4 = *(uint *)(**(int **)(iVar9 + -0x7fd4) + 0x1ea4);
      if (((uVar7 & uVar4) == 0) && ((uVar8 & uVar4) == 0)) {
        uVar10 = func_0x0054cbf0(param_1,*(undefined4 *)(param_1 + 0x178),3);
        iVar9 = func_0x0013fd34(*puVar3,uVar10,3,0,4,0);
        if (*(int *)(param_1 + 0x178) != iVar9) {
          *(int *)(param_1 + 0x178) = iVar9;
          func_0x0054bff8(param_1);
        }
      }
      else {
        func_0x0013e454(*puVar3,4,0,1);
        func_0x0054c038(param_1);
        *(undefined4 *)(param_1 + 0x174) = 0;
        *(undefined1 *)(param_1 + 0x17) = 2;
      }
      goto LAB_00609c80;
    }
    if ((1 << (*(uint *)(param_1 + 0x178) & 0x3f) & *(uint *)(param_1 + 0x188)) == 0) {
LAB_006143ec:
      func_0x0054bf78(param_1);
      goto LAB_00609c80;
    }
    func_0x0013e454(*puVar3,4,0,1);
    *(undefined4 *)(*(int *)(**(int **)(iVar9 + -0x7ff8) + 0x182d4) + 0x340) =
         *(undefined4 *)(param_1 + 0x178);
    func_0x0054c178(param_1);
LAB_0061430c:
    *(undefined4 *)(param_1 + 0x40) = *(undefined4 *)(iVar9 + -0x7f44);
    *(undefined1 *)(param_1 + 0x39) = 1;
    *(char *)(param_1 + 0x17) = *(char *)(param_1 + 0x17) + '\x01';
  }
  else {
    if (bVar1 < 0xb) {
      if (bVar1 != 1) {
        if (bVar1 == 0) {
          func_0x00609dd0(param_1);
          *(undefined4 *)(param_1 + 0x40) = *(undefined4 *)(iVar9 + -0x7e50);
          *(undefined4 *)(param_1 + 0x70) = 9;
          *(char *)(param_1 + 0x17) = *(char *)(param_1 + 0x17) + '\x01';
          goto LAB_00609c80;
        }
        if (bVar1 != 2) {
          if ((bVar1 != 3) ||
             (fVar2 = *(float *)(iVar9 + -0x7f38),
             fVar5 = *(float *)(param_1 + 0x40) - *(float *)(**(int **)(iVar9 + -0x7f3c) + 0x2c),
             *(float *)(param_1 + 0x40) = fVar5, fVar2 < fVar5)) goto LAB_00609c80;
          *(undefined1 *)(param_1 + 0x39) = 0;
          if (*(int *)(param_1 + 0x44) == 0) {
            *(undefined4 *)(param_1 + 0x174) = 1;
            *(undefined1 *)(param_1 + 0x17) = 10;
            *(undefined4 *)(param_1 + 0x178) = 0;
            goto LAB_00609c80;
          }
          puVar3 = *(undefined4 **)(iVar9 + -0x7e80);
          goto LAB_0061467c;
        }
        puVar3 = *(undefined4 **)(iVar9 + -0x7fd0);
        func_0x0013e848(*puVar3,0x1b,4,0);
        if (((uVar7 & *(uint *)(**(int **)(iVar9 + -0x7fd4) + 0x1ea0)) == 0) &&
           ((uVar8 & 0x200) == 0)) {
          uVar4 = *(uint *)(**(int **)(iVar9 + -0x7fd4) + 0x1ea4);
          if (((uVar7 & uVar4) == 0) && ((uVar8 & uVar4) == 0)) {
            uVar8 = func_0x0013fd34(*puVar3,*(undefined4 *)(param_1 + 0x44),2,0,4,0);
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
            func_0x0013e454(*puVar3,4,0,1);
            func_0x0054c138(param_1);
            *(undefined1 *)(param_1 + 0x3a) = 1;
            func_0x005bc8fc(param_1,0x62,0x19);
            *(undefined1 *)(param_1 + 0x17) = 0x5a;
          }
          goto LAB_00609c80;
        }
        if ((1 << (*(uint *)(param_1 + 0x44) & 0x3f) & *(uint *)(param_1 + 0x184)) == 0)
        goto LAB_006143ec;
        func_0x0013e454(*puVar3,4,0,1);
        *(undefined4 *)(*(int *)(**(int **)(iVar9 + -0x7ff8) + 0x182d4) + 0x33c) =
             *(undefined4 *)(param_1 + 0x44);
        func_0x0054c0b8(param_1);
        goto LAB_0061430c;
      }
      fVar2 = *(float *)(iVar9 + -0x7f38);
      fVar5 = *(float *)(param_1 + 0x40) - *(float *)(**(int **)(iVar9 + -0x7f3c) + 0x2c);
      *(float *)(param_1 + 0x40) = fVar5;
      if (fVar2 < fVar5) goto LAB_00609c80;
      iVar9 = *(int *)(param_1 + 400);
      if (iVar9 != 0) {
        *(uint *)(iVar9 + 4) = *(uint *)(iVar9 + 4) & 0xfff7ffff;
        (*(code *)**(undefined4 **)(**(int **)(param_1 + 400) + 0x34))(*(int **)(param_1 + 400));
        *(undefined4 *)(param_1 + 400) = 0;
      }
      if (*(int *)(param_1 + 0x174) != 0) {
        *(undefined1 *)(param_1 + 0x17) = 10;
        goto LAB_00609c80;
      }
    }
    else {
      if (bVar1 == 0x5a) {
        func_0x005bca34(param_1,0);
        *(char *)(param_1 + 0x17) = *(char *)(param_1 + 0x17) + '\x01';
        goto LAB_00609c80;
      }
      if (bVar1 < 0x5b) {
        if ((bVar1 != 0xb) ||
           (fVar2 = *(float *)(iVar9 + -0x7f38),
           fVar5 = *(float *)(param_1 + 0x40) - *(float *)(**(int **)(iVar9 + -0x7f3c) + 0x2c),
           *(float *)(param_1 + 0x40) = fVar5, fVar2 < fVar5)) goto LAB_00609c80;
        puVar3 = *(undefined4 **)(iVar9 + -0x7e80);
        *(undefined1 *)(param_1 + 0x39) = 0;
LAB_0061467c:
        uVar10 = func_0x000bbe20(*puVar3);
        func_0x0001112c(uVar10);
        *(undefined1 *)(param_1 + 0x17) = 0x5a;
        goto LAB_00609c80;
      }
      if (bVar1 != 0x5b) {
        if (bVar1 == 0x5c) {
          *(undefined1 *)(param_1 + 0x38) = 1;
          return;
        }
        goto LAB_00609c80;
      }
      cVar11 = func_0x005bd19c(param_1,0);
      if (cVar11 == '\0') goto LAB_00609c80;
    }
    *(char *)(param_1 + 0x17) = *(char *)(param_1 + 0x17) + '\x01';
  }
LAB_00609c80:
  iVar9 = *(int *)(iVar6 + -0x7974);
  iVar6 = *(int *)(**(int **)(iVar9 + -0x7fec) +
                   *(int *)(**(int **)(iVar9 + -0x7fec) + 0x24) * 0x7eb8 + 0x7c);
  func_0x0054bd6c();
  cVar11 = func_0x005bb910(param_1,0,0xff,0);
  if (cVar11 != '\0') {
    func_0x0054d468(param_1,cVar11);
    uVar7 = (int)*(uint *)(param_1 + 0x174) >> 0x1f;
    uVar7 = ((int)(((uVar7 ^ *(uint *)(param_1 + 0x174)) - uVar7) + -1) >> 0x1f | 0xffffffb2U) &
            0xff;
    func_0x00550c9c(param_1,*(undefined4 *)(iVar9 + -0x7fe8),uVar7);
    func_0x00fe6bbc(auStack_50,*(undefined4 *)(iVar9 + -0x7fe4),
                    *(undefined4 *)(*(int *)(iVar9 + -0x7fe0) + iVar6 * 4));
    func_0x00550c9c(param_1,auStack_50,uVar7);
    if (*(int *)(param_1 + 400) == 0) {
      if (*(int *)(param_1 + 0x174) == 0) {
        func_0x006099cc(param_1);
      }
      else {
        func_0x00609594(param_1);
      }
    }
  }
  return;
}


