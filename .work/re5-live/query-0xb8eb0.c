
void FUN_000b8eb0(undefined4 *param_1)

{
  bool bVar1;
  int *piVar2;
  undefined4 uVar3;
  undefined4 uVar4;
  undefined4 uVar5;
  undefined8 uVar6;
  int iVar7;
  int iVar8;
  uint uVar9;
  int iVar10;
  int *piVar11;
  undefined4 *puVar12;
  uint uVar13;
  int iVar14;
  int iVar15;
  undefined4 *puVar16;
  ulonglong uVar17;
  
  iVar14 = iRam017147c4;
  uVar6 = 0x171c590;
  func_0x00b86b10(param_1);
  uVar3 = *(undefined4 *)(iVar14 + -0x7a70);
  uVar4 = *(undefined4 *)(iVar14 + -0x7ad0);
  *param_1 = *(undefined4 *)(iVar14 + -0x7ad4);
  param_1[9] = uVar3;
  param_1[10] = 0;
  param_1[0xc] = uVar4;
  uVar3 = *(undefined4 *)(iVar14 + -0x7f20);
  iVar15 = *(int *)(iVar14 + -0x8000);
  uVar4 = *(undefined4 *)(iVar14 + -0x7ffc);
  uVar5 = *(undefined4 *)(iVar14 + -0x7ff8);
  param_1[0x10] = 0;
  param_1[0xd] = 0;
  param_1[0xe] = 0;
  *(undefined1 *)(param_1 + 0xf) = 0;
  puVar12 = param_1 + 0x12;
  do {
    *puVar12 = uVar3;
    func_0x00a0465c(puVar12 + 4);
    iVar7 = (int)uVar6;
    iVar10 = *(int *)(iVar15 + 0x6c);
    uVar13 = iVar10 + 1U & 7;
    puVar12[0x94] = uVar4;
    puVar12[0x9e] = uVar5;
    puVar12[0x96] = iVar10 + 2;
    *(undefined1 *)(puVar12 + 0x95) = 0;
    puVar12[0x97] = 0;
    *(undefined1 *)((int)puVar12 + 0x255) = 0;
    puVar12[0x98] = 0;
    puVar12[0x99] = 0;
    puVar12[0x9a] = 0;
    puVar12[0x9b] = 0;
    puVar12[0x9c] = 0;
    puVar12[0x9d] = 0;
    puVar12[0xa1] = 0;
    puVar12[0xa2] = 0xff;
    puVar12[0xa3] = 0;
    puVar12[0x9f] = 0;
    puVar12[0xa0] = 0;
    puVar12[0xa4] = 0;
    puVar12[0xa5] = uVar4;
    puVar12[0xaf] = uVar5;
    puVar12[0xa7] = uVar13 + 2;
    *(undefined1 *)(puVar12 + 0xa6) = 0;
    puVar12[0xa8] = 0;
    *(undefined1 *)((int)puVar12 + 0x299) = 0;
    puVar12[0xa9] = 0;
    puVar12[0xaa] = 0;
    puVar12[0xab] = 0;
    puVar12[0xac] = 0;
    puVar12[0xad] = 0;
    puVar12[0xae] = 0;
    puVar12[0xb2] = 0;
    puVar12[0xb3] = 0xff;
    puVar12[0xb4] = 0;
    puVar12[0xb0] = 0;
    puVar12[0xb1] = 0;
    puVar12[0xb5] = 0;
    *(uint *)(iVar15 + 0x6c) = uVar13 + 1 & 7;
    *(undefined1 *)(puVar12 + 1) = 0;
    puVar12[2] = 0;
    puVar16 = puVar12 + 0xba;
    *(undefined1 *)(puVar12 + 5) = 0;
    puVar12[0xb9] = 0;
    puVar12[0xb6] = 0;
    puVar12[0xb7] = 0;
    puVar12[0xb8] = 0;
    puVar12 = puVar16;
  } while (param_1 + 0x2fa != puVar16);
  *(undefined4 **)(iVar15 + 0x74) = param_1;
  *(undefined1 *)(param_1 + 0xb) = 0;
  *(undefined1 *)((int)param_1 + 0x2d) = 0;
  *(undefined1 *)(param_1 + 0x33e) = 0;
  *(undefined4 *)(iVar15 + 0x70) = 0;
  func_0x0113d224(param_1 + 9,0);
  iVar15 = 0;
  puVar16 = param_1 + 0x10;
  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar14 + -0x7f24) + 0x1c))
            ((int *)**(undefined4 **)(iVar14 + -0x7f24),param_1[0x10]);
  uVar3 = *(undefined4 *)(iVar14 + -0x7a6c);
  puVar12 = *(undefined4 **)(iVar14 + -0x7f48);
  param_1[0xe] = 0;
  param_1[0x10] = 0;
  param_1[0xd] = 0;
  param_1[0x342] = uVar3;
  param_1[0x33f] = uVar3;
  param_1[0x340] = uVar3;
  param_1[0x341] = uVar3;
  do {
    uVar17 = 0;
    *(undefined1 *)(puVar16 + 3) = 0;
    puVar16[4] = iVar15;
    func_0x00a04844(puVar16 + 6,0xff);
    *(undefined1 *)(puVar16 + 7) = 0;
    puVar16[8] = 0;
    do {
      iVar14 = (int)((uVar17 & 0xffffffff) << 2) + (int)((uVar17 & 0xffffffff) << 6);
      if (*(char *)((int)puVar16 + iVar14 + 0x25c) != '\0') {
        iVar10 = func_0x00159c6c(*puVar12,*(undefined4 *)((int)puVar16 + iVar14 + 0x260));
        uVar13 = 0;
        if (iVar10 != 0) {
          while( true ) {
            uVar9 = func_0x00ad6d04(iVar10);
            if (uVar9 <= uVar13) break;
            iVar8 = func_0x00ad6cd4(iVar10,uVar13);
            *(undefined1 *)(iVar8 + 8) = 0;
            uVar13 = uVar13 + 1;
          }
          func_0x00159f7c(*puVar12,1,*(undefined4 *)((int)puVar16 + iVar14 + 0x260));
        }
      }
      uVar17 = uVar17 + 1;
      *(undefined1 *)((int)puVar16 + iVar14 + 0x25d) = 0;
      *(undefined1 *)((int)puVar16 + iVar14 + 0x25c) = 0;
      *(undefined4 *)((int)puVar16 + iVar14 + 0x264) = 0;
    } while (uVar17 != 2);
    bVar1 = iVar15 != 3;
    puVar16[0xbb] = 0;
    puVar16[0xba] = 0;
    puVar16 = puVar16 + 0xba;
    iVar15 = iVar15 + 1;
  } while (bVar1);
  func_0x00fe6bcc(param_1 + 0x2fa,0,0x100);
  iVar15 = *(int *)(iVar7 + -0x7dcc);
  puVar12 = *(undefined4 **)(iVar15 + -0x7f48);
  iVar14 = 0;
  puVar16 = param_1 + 0x10;
  do {
    uVar17 = 0;
    *(undefined1 *)(puVar16 + 3) = 0;
    puVar16[4] = iVar14;
    func_0x00a04844(puVar16 + 6,0xff);
    *(undefined1 *)(puVar16 + 7) = 0;
    puVar16[8] = 0;
    do {
      iVar10 = (int)((uVar17 & 0xffffffff) << 2) + (int)((uVar17 & 0xffffffff) << 6);
      if (*(char *)((int)puVar16 + iVar10 + 0x25c) != '\0') {
        iVar7 = func_0x00159c6c(*puVar12,*(undefined4 *)((int)puVar16 + iVar10 + 0x260));
        uVar13 = 0;
        if (iVar7 != 0) {
          while( true ) {
            uVar9 = func_0x00ad6d04(iVar7);
            if (uVar9 <= uVar13) break;
            iVar8 = func_0x00ad6cd4(iVar7,uVar13);
            *(undefined1 *)(iVar8 + 8) = 0;
            uVar13 = uVar13 + 1;
          }
          func_0x00159f7c(*puVar12,1,*(undefined4 *)((int)puVar16 + iVar10 + 0x260));
        }
      }
      uVar17 = uVar17 + 1;
      *(undefined1 *)((int)puVar16 + iVar10 + 0x25d) = 0;
      *(undefined1 *)((int)puVar16 + iVar10 + 0x25c) = 0;
      *(undefined4 *)((int)puVar16 + iVar10 + 0x264) = 0;
    } while (uVar17 != 2);
    bVar1 = iVar14 != 3;
    puVar16[0xbb] = 0;
    puVar16[0xba] = 0;
    puVar16 = puVar16 + 0xba;
    iVar14 = iVar14 + 1;
  } while (bVar1);
  if (param_1[0xd] == 0) {
    piVar11 = (int *)param_1[0x10];
  }
  else {
    piVar11 = (int *)param_1[0x10];
    do {
      if ((*(char *)(param_1 + 0xf) != '\0') && (piVar2 = (int *)*piVar11, piVar2 != (int *)0x0)) {
        (*(code *)**(undefined4 **)(*piVar2 + 4))(piVar2);
        piVar11 = (int *)param_1[0x10];
      }
      uVar13 = param_1[0xd];
      uVar9 = 1;
      iVar14 = 4;
      if (1 < uVar13) {
        while( true ) {
          puVar12 = (undefined4 *)(iVar14 + (int)piVar11);
          uVar9 = uVar9 + 1;
          iVar14 = iVar14 + 4;
          puVar12[-1] = *puVar12;
          uVar13 = param_1[0xd];
          if (uVar13 <= uVar9) break;
          piVar11 = (int *)param_1[0x10];
        }
        piVar11 = (int *)param_1[0x10];
      }
      param_1[0xd] = uVar13 - 1;
    } while (uVar13 - 1 != 0);
  }
  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar15 + -0x7f24) + 0x1c))
            ((int *)**(undefined4 **)(iVar15 + -0x7f24),piVar11);
  iVar15 = *(int *)(iVar15 + -0x8000);
  param_1[0xe] = 0;
  param_1[0x10] = 0;
  param_1[0xd] = 0;
  *(undefined1 *)(param_1 + 0x343) = 0;
  *(undefined4 *)(iVar15 + 0x70) = 0;
  return;
}


