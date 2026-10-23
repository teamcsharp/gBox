
void FUN_00553fec(int param_1)

{
  bool bVar1;
  float fVar2;
  int *piVar3;
  char *pcVar4;
  int *piVar5;
  uint uVar6;
  bool bVar7;
  char cVar8;
  int iVar9;
  ulonglong uVar10;
  uint uVar11;
  byte bVar13;
  char *pcVar12;
  ulonglong uVar14;
  int iVar15;
  uint uVar16;
  int iVar17;
  int iVar18;
  undefined1 auStack_d0 [64];
  
  iVar9 = iRam01714bbc;
  piVar3 = *(int **)(iRam01714bbc + -0x7ffc);
  uVar10 = (ulonglong)*(uint *)(*(int *)(*piVar3 + 0x182d4) + 0x58) ^ 3;
  uVar14 = (ulonglong)((int)uVar10 >> 0x1f);
  uVar10 = (((uVar14 ^ uVar10) - uVar14) - 1 & 0xffffffff) >> 0x1f;
  iVar15 = (int)uVar10;
  bVar7 = iVar15 == 0;
  if (*(char *)(param_1 + 0x184) == '\x03') {
    *(float *)(param_1 + 0x28c) =
         (*(float *)(param_1 + 0x1ac) + *(float *)(param_1 + 0x21c)) *
         *(float *)(iRam01714bbc + -0x7ecc);
    if (iVar15 == 0) {
      *(int *)(param_1 + 0x290) = *(int *)(param_1 + 0x1b0) + *(int *)(param_1 + 0x220);
    }
    *(int *)(param_1 + 0x2a0) = *(int *)(param_1 + 0x1c0) + *(int *)(param_1 + 0x230);
  }
  func_0x009c1d78(*(undefined4 *)(*piVar3 + 0x182d4),auStack_d0,param_1 + 0x2c0,param_1 + 0x2a8);
  fVar2 = *(float *)(iVar9 + -0x7ec4);
  iVar15 = **(int **)(iVar9 + -0x7ff0);
  *(undefined4 *)(iVar15 + 0x26920) = *(undefined4 *)(param_1 + 700);
  *(int *)(iVar15 + 0x26924) = (int)(longlong)(*(float *)(param_1 + 0x28c) * fVar2);
  *(undefined4 *)(iVar15 + 0x26928) = *(undefined4 *)(param_1 + 0x290);
  *(undefined4 *)(iVar15 + 0x2692c) = *(undefined4 *)(param_1 + 0x2a0);
  *(undefined4 *)(iVar15 + 0x26930) = *(undefined4 *)(param_1 + 0x2a4);
  *(undefined4 *)(iVar15 + 0x26934) = *(undefined4 *)(param_1 + 0x298);
  if (*(int *)(*(int *)(*piVar3 + 0x182d4) + 0x2c) == 0xd) {
    *(undefined4 *)(param_1 + 0x308) = 0;
  }
  pcVar4 = *(char **)(iVar9 + -0x7eb8);
  cVar8 = bVar7 * '\x03';
  uVar16 = 0;
  iVar15 = 0x200;
  do {
    func_0x009c0ce0(*(undefined4 *)(*piVar3 + 0x182d4),uVar16);
    if (((*(int *)(*(int *)(*piVar3 + 0x182d4) + 0x1e8) >> (uVar16 & 0x3f) & 1U) != 0) &&
       (uVar6 = *(uint *)(*(int *)(*piVar3 + 0x182d4) + iVar15), -1 < (int)uVar6)) {
      piVar5 = *(int **)(iVar9 + -0x7ebc);
      FUN_001426ec(*piVar5,uVar6);
      uVar11 = func_0x00aecc88(*piVar5 + *(int *)(*piVar5 + 0x24) * 0x7eb8 + 0x40,bVar7);
      if (uVar11 == 0) {
        func_0x009c0d08(*(undefined4 *)(*piVar3 + 0x182d4),uVar16,cVar8 + '\x0f');
        func_0x009c0d08(*(undefined4 *)(*piVar3 + 0x182d4),uVar16,cVar8 + '\x10');
        iVar18 = *(int *)(param_1 + 0x180);
        if (1 < iVar18) goto LAB_00554220;
LAB_0055422c:
        iVar17 = *piVar5;
        if (*(char *)(iVar17 + 0x20) != '\0') goto LAB_0055424c;
LAB_00554240:
        if (*pcVar4 != '\0') goto LAB_0055424c;
      }
      else {
        iVar18 = *(int *)(param_1 + 0x180);
        if (iVar18 < 2) goto LAB_0055422c;
LAB_00554220:
        if ((uVar11 & 0xc) != 0) goto LAB_0055422c;
        func_0x009c0d08(*(undefined4 *)(**(int **)(iVar9 + -0x7ffc) + 0x182d4),uVar16,cVar8 + '\x11'
                       );
        iVar17 = *piVar5;
        iVar18 = *(int *)(param_1 + 0x180);
        if (*(char *)(iVar17 + 0x20) == '\0') goto LAB_00554240;
LAB_0055424c:
        func_0x01399428(iVar17 + 8,0);
      }
      func_0x00aeccc0(iVar17 + *(int *)(iVar17 + 0x24) * 0x7eb8 + 0x40,bVar7,iVar18);
      if ((*(char *)(iVar17 + 0x20) != '\0') || (*pcVar4 != '\0')) {
        func_0x01399448(iVar17 + 8);
      }
      iVar18 = *piVar5;
      if ((*(char *)(iVar18 + 0x20) != '\0') || (*pcVar4 != '\0')) {
        func_0x01399428(iVar18 + 8,0);
      }
      iVar17 = iVar18 + *(int *)(iVar18 + 0x24) * 0x7eb8 + 0x40;
      *(uint *)(iVar17 + 0x3f34) = *(uint *)(iVar17 + 0x3f34) | 1 << bVar7 + 6;
      if ((*(char *)(iVar18 + 0x20) != '\0') || (*pcVar4 != '\0')) {
        func_0x01399448(iVar18 + 8);
      }
      if (uVar10 == 0) {
        func_0x0014723c(*piVar5,0x41);
        if (*(int *)(param_1 + 0x2d4) == 0) {
          func_0x0014723c(*piVar5,0x42);
        }
        if (*(int *)(param_1 + 0x180) == 3) {
          func_0x0014723c(*piVar5,0x43);
        }
      }
      else {
        func_0x0014723c(*piVar5,0x3c);
        if (*(int *)(param_1 + 0x2d4) == 0) {
          func_0x0014723c(*piVar5,0x3d);
        }
        if (*(int *)(param_1 + 0x180) == 3) {
          func_0x0014723c(*piVar5,0x3e);
        }
      }
      if ((*(int *)(param_1 + 0x308) >> (uVar6 & 0x3f) & 1U) != 0) {
        bVar13 = func_0x009c199c(*(undefined4 *)(*piVar3 + 0x182d4));
        pcVar12 = (char *)func_0x00aecff0(*piVar5 + *(int *)(*piVar5 + 0x24) * 0x7eb8 + 0x40,bVar7,
                                          bVar13 ^ 1,*(undefined4 *)(param_1 + 0x180));
        if ((*pcVar12 == '\0') || (*(uint *)(pcVar12 + 4) < *(uint *)(param_1 + 700))) {
          *pcVar12 = '\x01';
          *(undefined4 *)(pcVar12 + 4) = *(undefined4 *)(param_1 + 700);
        }
      }
      FUN_001426f0(*piVar5);
    }
    bVar1 = uVar16 == 1;
    iVar15 = iVar15 + 4;
    uVar16 = uVar16 + 1;
    if (bVar1) {
      return;
    }
  } while( true );
}


