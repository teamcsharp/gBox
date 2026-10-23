
/* WARNING: Possible PIC construction at 0x005551c0: Changing call to branch */
/* WARNING: Removing unreachable block (ram,0x005551c4) */
/* WARNING: Heritage AFTER dead removal. Example location: s0xffffff38 : 0x00555318 */
/* WARNING: Restarted to delay deadcode elimination for space: stack */

void FUN_00554e9c(int param_1)

{
  bool bVar1;
  bool bVar2;
  float fVar3;
  int *piVar4;
  undefined4 *puVar5;
  undefined4 uVar6;
  int *piVar7;
  int *piVar8;
  ulonglong uVar9;
  uint uVar10;
  undefined8 uVar11;
  int iVar12;
  undefined1 uVar17;
  uint uVar13;
  byte bVar18;
  char *pcVar14;
  char cVar19;
  undefined4 uVar15;
  char *pcVar16;
  ulonglong uVar20;
  int iVar21;
  uint uVar22;
  int iVar23;
  int iVar24;
  undefined4 uStack_160;
  undefined4 uStack_15c;
  undefined4 uStack_158;
  undefined4 uStack_154;
  undefined4 uStack_150;
  undefined1 auStack_d0 [12];
  int iStack_c4;
  
  iVar21 = iRam01714bbc;
  uVar11 = 0x171c590;
  piVar4 = *(int **)(iRam01714bbc + -0x7ffc);
  iVar12 = *(int *)(*(int *)(*piVar4 + 0x182d4) + 0x58);
  if (iVar12 == 0) {
    func_0x0054cecc(param_1,0x28,
                    *(undefined4 *)
                     (*(int *)(iRam01714bbc + -0x7e94) + *(int *)(param_1 + 0x178) * 4),0xe0);
  }
  else {
    if (iVar12 != 3) {
      func_0x0054cecc(param_1,0x28,*(undefined4 *)(iRam01714bbc + -0x7e8c),0xe0);
      cVar19 = func_0x0054aef4(param_1);
      goto joined_r0x00555168;
    }
    func_0x0054cecc(param_1,0x28,*(undefined4 *)(iRam01714bbc + -0x7e90),0xe0);
  }
  cVar19 = func_0x0054aef4(param_1);
joined_r0x00555168:
  if (cVar19 != '\0') {
    func_0x00159fc0(**(undefined4 **)(iVar21 + -0x7f88),1,*(undefined4 *)(param_1 + 0x18));
  }
  func_0x0054bd6c(param_1);
  puVar5 = *(undefined4 **)(iVar21 + -0x7e88);
  uVar15 = *(undefined4 *)(iVar21 + -0x7e84);
  uVar6 = *(undefined4 *)(iVar21 + -0x7e80);
  *(undefined1 *)(param_1 + 0x2f8) = 0;
  uVar15 = func_0x00c5ff9c(*puVar5,uVar15,uVar6,1);
  piVar7 = *(int **)(iVar21 + -0x7ebc);
  *(undefined4 *)(param_1 + 0x314) = uVar15;
  uVar15 = *(undefined4 *)(*piVar7 + *(int *)(*piVar7 + 0x24) * 0x5940 + 0x23cd8);
  *(undefined4 *)(param_1 + 0x17c) = 0;
  *(undefined4 *)(param_1 + 0x180) = uVar15;
  if (*(int *)(*(int *)(*piVar4 + 0x182d4) + 0x58) == 0) {
    pcVar16 = (char *)func_0x00142884(*piVar7,*(undefined4 *)(param_1 + 0x178));
    *(int *)(param_1 + 0x17c) = (int)*pcVar16;
  }
  piVar8 = *(int **)(iVar21 + -0x7f14);
  puVar5 = *(undefined4 **)(iVar21 + -0x7ea8);
  *(undefined4 *)(param_1 + 0x308) = 0;
  cVar19 = func_0x00201950(*puVar5,*(undefined4 *)(*piVar8 + 0x1f98));
  iVar12 = (int)uVar11;
  if (cVar19 != '\0') {
    uVar22 = 0;
    piVar8 = *(int **)(iVar21 + -0x7ffc);
    iVar23 = 0x200;
    do {
      if (((*(int *)(*(int *)(*piVar4 + 0x182d4) + 0x1e8) >> (uVar22 & 0x3f) & 1U) != 0) &&
         (uVar10 = *(uint *)(*(int *)(*piVar4 + 0x182d4) + iVar23), -1 < (int)uVar10)) {
        cVar19 = func_0x00201950(*puVar5,uVar10);
        if (cVar19 == '\0') {
          uVar13 = *(uint *)(param_1 + 0x308);
        }
        else {
          uVar13 = *(uint *)(param_1 + 0x308) | 1 << (uVar10 & 0x3f);
          *(uint *)(param_1 + 0x308) = uVar13;
        }
        if ((((int)uVar13 >> (uVar10 & 0x3f) & 1U) != 0) &&
           (*(int *)(*(int *)(*piVar8 + 0x182d4) + 0x58) == 0)) {
          iVar12 = 0;
          FUN_001426ec(*piVar7,uVar10);
          do {
            pcVar16 = (char *)func_0x00142884(*piVar7,iVar12);
            if (((int)*pcVar16 == *(int *)(param_1 + 0x17c)) &&
               (pcVar16 = (char *)func_0x00aeceb4(*piVar7 + *(int *)(*piVar7 + 0x24) * 0x7eb8 + 0x40
                                                  ,*(undefined4 *)(param_1 + 0x180),iVar12),
               *pcVar16 == '\0')) {
              *(uint *)(param_1 + 0x308) = *(uint *)(param_1 + 0x308) & ~(1 << (uVar10 & 0x3f));
              break;
            }
            bVar2 = iVar12 != 0xf;
            iVar12 = iVar12 + 1;
          } while (bVar2);
          FUN_001426f0(*piVar7);
        }
      }
      iVar12 = (int)uVar11;
      bVar2 = uVar22 != 1;
      iVar23 = iVar23 + 4;
      uVar22 = uVar22 + 1;
    } while (bVar2);
  }
  *(undefined1 *)(param_1 + 0x184) = 0;
  iVar23 = *(int *)(*piVar4 + 0x182d4);
  if (*(int *)(iVar23 + 0x58) == 0) {
    iVar12 = *(int *)(iVar12 + -0x79d4);
    piVar4 = *(int **)(iVar12 + -0x7ffc);
    if ((*(uint *)(*(int *)(*piVar4 + 0x182d4) + 0x1e8) & 1) != 0) {
      cVar19 = func_0x009c09a0(*(int *)(*piVar4 + 0x182d4),0);
      if (cVar19 == '\0') {
        iVar21 = *(int *)(*piVar4 + 0x182d4);
        func_0x00fe6bfc(param_1 + 0x18a,**(undefined4 **)(iVar12 + -0x7ee0));
        *(undefined1 *)(param_1 + 0x188) = *(undefined1 *)(iVar21 + 0x304);
        *(undefined4 *)(param_1 + 0x1ac) = *(undefined4 *)(iVar21 + 0x308);
        *(undefined4 *)(param_1 + 0x1b0) = *(undefined4 *)(iVar21 + 0x30c);
        *(undefined4 *)(param_1 + 0x1b4) = *(undefined4 *)(iVar21 + 0x310);
        fVar3 = *(float *)(iVar21 + 0x314);
        *(int *)(param_1 + 0x1b8) = (int)(longlong)fVar3;
        if (359999 < ((longlong)fVar3 & 0xffffffffU)) {
          *(undefined4 *)(param_1 + 0x1b8) = 359999;
        }
        uVar17 = func_0x009c1928(*(undefined4 *)(*piVar4 + 0x182d4),0);
        *(undefined1 *)(param_1 + 0x189) = uVar17;
        func_0x009c0d3c((double)*(float *)(param_1 + 0x1ac),*(undefined4 *)(*piVar4 + 0x182d4),
                        &uStack_160,*(undefined4 *)(param_1 + 0x178));
        *(undefined4 *)(param_1 + 0x1e0) = uStack_160;
        *(undefined4 *)(param_1 + 0x1e4) = uStack_15c;
        *(undefined4 *)(param_1 + 0x1e8) = uStack_158;
        *(undefined4 *)(param_1 + 0x1ec) = uStack_154;
        *(undefined4 *)(param_1 + 0x1f0) = uStack_150;
        uVar15 = func_0x009c0f90(*(undefined4 *)(*piVar4 + 0x182d4),*(undefined4 *)(param_1 + 0x180)
                                 ,uStack_150);
        *(undefined4 *)(param_1 + 0x1bc) = uVar15;
        *(byte *)(param_1 + 0x184) = *(byte *)(param_1 + 0x184) | 1;
        return;
      }
    }
    return;
  }
  if (((*(uint *)(iVar23 + 0x1e8) & 1) != 0) && (cVar19 = func_0x009c09a0(iVar23,0), cVar19 == '\0')
     ) {
    iVar12 = *(int *)(*piVar4 + 0x182d4);
    uVar10 = *(uint *)(iVar12 + 0x58) ^ 3;
    uVar22 = (int)uVar10 >> 0x1f;
    func_0x00fe6bfc(param_1 + 0x18a,
                    *(undefined4 *)
                     (*(int *)(iVar21 + -0x7ee4) +
                     (uint)(-1 < (int)(((uVar22 ^ uVar10) - uVar22) + -1)) * 8));
    *(undefined1 *)(param_1 + 0x188) = *(undefined1 *)(iVar12 + 0x304);
    *(undefined4 *)(param_1 + 0x1ac) = *(undefined4 *)(iVar12 + 0x308);
    *(undefined4 *)(param_1 + 0x1b0) = *(undefined4 *)(iVar12 + 0x30c);
    *(undefined4 *)(param_1 + 0x1c0) = *(undefined4 *)(iVar12 + 0x310);
    *(undefined4 *)(param_1 + 0x1c4) = *(undefined4 *)(iVar12 + 0x318);
    fVar3 = *(float *)(iVar12 + 0x314);
    *(int *)(param_1 + 0x1b8) = (int)(longlong)fVar3;
    if (359999 < ((longlong)fVar3 & 0xffffffffU)) {
      *(undefined4 *)(param_1 + 0x1b8) = 359999;
    }
    func_0x00fe6c3c(param_1 + 0x268,(undefined1 *)(param_1 + 0x188),0x70);
    *(byte *)(param_1 + 0x184) = *(byte *)(param_1 + 0x184) | 1;
    iVar12 = iStack_c4;
  }
  if (((*(uint *)(*(int *)(*piVar4 + 0x182d4) + 0x1e8) & 2) != 0) &&
     (cVar19 = func_0x009c09a0(*(int *)(*piVar4 + 0x182d4),1), cVar19 == '\0')) {
    iVar12 = *(int *)(*piVar4 + 0x182d4);
    uVar10 = *(uint *)(iVar12 + 0x58) ^ 3;
    uVar22 = (int)uVar10 >> 0x1f;
    func_0x00fe6bfc(param_1 + 0x1fa,
                    *(undefined4 *)
                     (*(int *)(iVar21 + -0x7ee4) +
                     (uint)(-1 < (int)(((uVar22 ^ uVar10) - uVar22) + -1)) * 8 + 4));
    *(undefined1 *)(param_1 + 0x1f8) = *(undefined1 *)(iVar12 + 0x31c);
    *(undefined4 *)(param_1 + 0x21c) = *(undefined4 *)(iVar12 + 800);
    *(undefined4 *)(param_1 + 0x220) = *(undefined4 *)(iVar12 + 0x324);
    *(undefined4 *)(param_1 + 0x230) = *(undefined4 *)(iVar12 + 0x328);
    *(undefined4 *)(param_1 + 0x234) = *(undefined4 *)(iVar12 + 0x330);
    fVar3 = *(float *)(iVar12 + 0x32c);
    *(int *)(param_1 + 0x228) = (int)(longlong)fVar3;
    if (359999 < ((longlong)fVar3 & 0xffffffffU)) {
      *(undefined4 *)(param_1 + 0x228) = 359999;
    }
    func_0x00fe6c3c(param_1 + 0x268,(undefined1 *)(param_1 + 0x1f8),0x70);
    *(byte *)(param_1 + 0x184) = *(byte *)(param_1 + 0x184) | 2;
    iVar12 = iStack_c4;
  }
  iVar12 = *(int *)(iVar12 + -0x79d4);
  piVar4 = *(int **)(iVar12 + -0x7ffc);
  uVar9 = (ulonglong)*(uint *)(*(int *)(*piVar4 + 0x182d4) + 0x58) ^ 3;
  uVar20 = (ulonglong)((int)uVar9 >> 0x1f);
  uVar9 = (((uVar20 ^ uVar9) - uVar20) - 1 & 0xffffffff) >> 0x1f;
  iVar21 = (int)uVar9;
  bVar2 = iVar21 == 0;
  if (*(char *)(param_1 + 0x184) == '\x03') {
    *(float *)(param_1 + 0x28c) =
         (*(float *)(param_1 + 0x1ac) + *(float *)(param_1 + 0x21c)) * *(float *)(iVar12 + -0x7ecc);
    if (iVar21 == 0) {
      *(int *)(param_1 + 0x290) = *(int *)(param_1 + 0x1b0) + *(int *)(param_1 + 0x220);
    }
    *(int *)(param_1 + 0x2a0) = *(int *)(param_1 + 0x1c0) + *(int *)(param_1 + 0x230);
  }
  func_0x009c1d78(*(undefined4 *)(*piVar4 + 0x182d4),auStack_d0,param_1 + 0x2c0,param_1 + 0x2a8);
  fVar3 = *(float *)(iVar12 + -0x7ec4);
  iVar21 = **(int **)(iVar12 + -0x7ff0);
  *(undefined4 *)(iVar21 + 0x26920) = *(undefined4 *)(param_1 + 700);
  *(int *)(iVar21 + 0x26924) = (int)(longlong)(*(float *)(param_1 + 0x28c) * fVar3);
  *(undefined4 *)(iVar21 + 0x26928) = *(undefined4 *)(param_1 + 0x290);
  *(undefined4 *)(iVar21 + 0x2692c) = *(undefined4 *)(param_1 + 0x2a0);
  *(undefined4 *)(iVar21 + 0x26930) = *(undefined4 *)(param_1 + 0x2a4);
  *(undefined4 *)(iVar21 + 0x26934) = *(undefined4 *)(param_1 + 0x298);
  if (*(int *)(*(int *)(*piVar4 + 0x182d4) + 0x2c) == 0xd) {
    *(undefined4 *)(param_1 + 0x308) = 0;
  }
  pcVar16 = *(char **)(iVar12 + -0x7eb8);
  cVar19 = bVar2 * '\x03';
  uVar22 = 0;
  iVar21 = 0x200;
  do {
    func_0x009c0ce0(*(undefined4 *)(*piVar4 + 0x182d4),uVar22);
    if (((*(int *)(*(int *)(*piVar4 + 0x182d4) + 0x1e8) >> (uVar22 & 0x3f) & 1U) != 0) &&
       (uVar10 = *(uint *)(*(int *)(*piVar4 + 0x182d4) + iVar21), -1 < (int)uVar10)) {
      piVar7 = *(int **)(iVar12 + -0x7ebc);
      FUN_001426ec(*piVar7,uVar10);
      uVar13 = func_0x00aecc88(*piVar7 + *(int *)(*piVar7 + 0x24) * 0x7eb8 + 0x40,bVar2);
      if (uVar13 == 0) {
        func_0x009c0d08(*(undefined4 *)(*piVar4 + 0x182d4),uVar22,cVar19 + '\x0f');
        func_0x009c0d08(*(undefined4 *)(*piVar4 + 0x182d4),uVar22,cVar19 + '\x10');
        iVar23 = *(int *)(param_1 + 0x180);
        if (1 < iVar23) goto LAB_00554220;
LAB_0055422c:
        iVar24 = *piVar7;
        if (*(char *)(iVar24 + 0x20) != '\0') goto LAB_0055424c;
LAB_00554240:
        if (*pcVar16 != '\0') goto LAB_0055424c;
      }
      else {
        iVar23 = *(int *)(param_1 + 0x180);
        if (iVar23 < 2) goto LAB_0055422c;
LAB_00554220:
        if ((uVar13 & 0xc) != 0) goto LAB_0055422c;
        func_0x009c0d08(*(undefined4 *)(**(int **)(iVar12 + -0x7ffc) + 0x182d4),uVar22,
                        cVar19 + '\x11');
        iVar24 = *piVar7;
        iVar23 = *(int *)(param_1 + 0x180);
        if (*(char *)(iVar24 + 0x20) == '\0') goto LAB_00554240;
LAB_0055424c:
        func_0x01399428(iVar24 + 8,0);
      }
      func_0x00aeccc0(iVar24 + *(int *)(iVar24 + 0x24) * 0x7eb8 + 0x40,bVar2,iVar23);
      if ((*(char *)(iVar24 + 0x20) != '\0') || (*pcVar16 != '\0')) {
        func_0x01399448(iVar24 + 8);
      }
      iVar23 = *piVar7;
      if ((*(char *)(iVar23 + 0x20) != '\0') || (*pcVar16 != '\0')) {
        func_0x01399428(iVar23 + 8,0);
      }
      iVar24 = iVar23 + *(int *)(iVar23 + 0x24) * 0x7eb8 + 0x40;
      *(uint *)(iVar24 + 0x3f34) = *(uint *)(iVar24 + 0x3f34) | 1 << bVar2 + 6;
      if ((*(char *)(iVar23 + 0x20) != '\0') || (*pcVar16 != '\0')) {
        func_0x01399448(iVar23 + 8);
      }
      if (uVar9 == 0) {
        func_0x0014723c(*piVar7,0x41);
        if (*(int *)(param_1 + 0x2d4) == 0) {
          func_0x0014723c(*piVar7,0x42);
        }
        if (*(int *)(param_1 + 0x180) == 3) {
          func_0x0014723c(*piVar7,0x43);
        }
      }
      else {
        func_0x0014723c(*piVar7,0x3c);
        if (*(int *)(param_1 + 0x2d4) == 0) {
          func_0x0014723c(*piVar7,0x3d);
        }
        if (*(int *)(param_1 + 0x180) == 3) {
          func_0x0014723c(*piVar7,0x3e);
        }
      }
      if ((*(int *)(param_1 + 0x308) >> (uVar10 & 0x3f) & 1U) != 0) {
        bVar18 = func_0x009c199c(*(undefined4 *)(*piVar4 + 0x182d4));
        pcVar14 = (char *)func_0x00aecff0(*piVar7 + *(int *)(*piVar7 + 0x24) * 0x7eb8 + 0x40,bVar2,
                                          bVar18 ^ 1,*(undefined4 *)(param_1 + 0x180));
        if ((*pcVar14 == '\0') || (*(uint *)(pcVar14 + 4) < *(uint *)(param_1 + 700))) {
          *pcVar14 = '\x01';
          *(undefined4 *)(pcVar14 + 4) = *(undefined4 *)(param_1 + 700);
        }
      }
      FUN_001426f0(*piVar7);
    }
    bVar1 = uVar22 == 1;
    iVar21 = iVar21 + 4;
    uVar22 = uVar22 + 1;
    if (bVar1) {
      return;
    }
  } while( true );
}


