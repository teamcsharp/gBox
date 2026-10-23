
void FUN_005d5018(void)

{
  undefined1 uVar1;
  undefined1 uVar2;
  undefined1 uVar3;
  undefined1 *puVar4;
  int *piVar5;
  undefined4 uVar6;
  int iVar7;
  int *piVar8;
  int iVar9;
  uint uVar10;
  uint uVar11;
  int *unaff_r25;
  undefined4 *puVar12;
  undefined4 *unaff_r26;
  int unaff_r27;
  undefined8 unaff_r28;
  int unaff_r30;
  int unaff_r31;
  longlong lVar13;
  
  puVar12 = *(undefined4 **)(unaff_r30 + -0x7f28);
  *(undefined4 *)(unaff_r27 + 0x74) = 0;
  iVar7 = func_0x000bbca0(*puVar12);
  if (((iVar7 != 0) && (iVar7 = func_0x000bbca0(*puVar12), *(char *)(iVar7 + 0x58) == '\0')) &&
     (*(char *)(unaff_r27 + 0x51) != '\0')) {
    iVar7 = **(int **)(unaff_r30 + -0x7f68);
    iVar9 = *(int *)(iVar7 + 0x24) * 0x7eb8;
    uVar11 = *(uint *)(iVar7 + iVar9 + 0x7c);
    uVar10 = *(uint *)(iVar7 + iVar9 + 0x6c);
    if (5 < uVar11) {
      uVar11 = 0;
    }
    if (3 < (int)uVar10) {
      uVar10 = 3;
    }
    uVar6 = func_0x00c5ff9c(*unaff_r26,*(undefined4 *)(unaff_r30 + -0x7f24),
                            *(undefined4 *)
                             (&stack0x00000208 +
                             (uVar10 * 8 + (uVar10 & 0x7fffffff) * -2 + uVar11) * 4),1);
    *(undefined4 *)(unaff_r27 + 0x74) = uVar6;
  }
  if (*(int *)(unaff_r27 + 0x74) == 0) {
    puVar12 = *(undefined4 **)(unaff_r30 + -0x7f20);
  }
  else {
    puVar12 = *(undefined4 **)(unaff_r30 + -0x7f20);
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0xf,0x10);
    *piVar8 = 1;
    piVar8[1] = 3;
    *(undefined1 *)((int)piVar8 + 0xb) = 0;
    *(undefined1 *)(piVar8 + 2) = 0x70;
    *(undefined1 *)((int)piVar8 + 9) = 0x69;
    *(undefined1 *)((int)piVar8 + 10) = 99;
    iVar7 = func_0x00ad6d18(unaff_r28,&stack0x000000f4);
    if ((piVar8 != (int *)0x0) && (iVar9 = *piVar8, *piVar8 = iVar9 + -1, iVar9 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    if (iVar7 != 0) {
      func_0x00ad6e84(iVar7,*(undefined4 *)(unaff_r27 + 0x74));
    }
    if (*(int *)(unaff_r27 + 0x74) != 0) {
      func_0x00b85d98(*(int *)(unaff_r27 + 0x74));
      *(undefined4 *)(unaff_r27 + 0x74) = 0;
    }
  }
  iVar7 = 0;
  lVar13 = 0x54;
  do {
    iVar9 = iVar7 + unaff_r31;
    iVar7 = iVar7 + 4;
    *(undefined4 *)(iVar9 + 0x7c) = 0;
    lVar13 = lVar13 + -1;
  } while (lVar13 != 0);
  if (((*(uint *)(*unaff_r25 + 0x182dc) & 2) == 0) && ((*(uint *)(*unaff_r25 + 0x182dc) & 1) == 0))
  {
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7f1c);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000120);
    *(undefined4 *)(unaff_r27 + 0x7c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x18,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7edc);
    *piVar8 = 1;
    piVar8[1] = 0xc;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000110);
    *(undefined4 *)(unaff_r27 + 0x80) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x18,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ed8);
    *piVar8 = 1;
    piVar8[1] = 0xc;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000114);
    *(undefined4 *)(unaff_r27 + 0x84) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x18,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ed4);
    *piVar8 = 1;
    piVar8[1] = 0xc;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000118);
    *(undefined4 *)(unaff_r27 + 0x88) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x18,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ed0);
    *piVar8 = 1;
    piVar8[1] = 0xc;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x0000011c);
    *(undefined4 *)(unaff_r27 + 0x8c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x18,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ecc);
    *piVar8 = 1;
    piVar8[1] = 0xc;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000d8);
    *(undefined4 *)(unaff_r27 + 0x90) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x16,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ec8);
    *piVar8 = 1;
    piVar8[1] = 10;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    uVar2 = puVar4[9];
    *(undefined1 *)((int)piVar8 + 0x12) = puVar4[10];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x11) = uVar2;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000d4);
    *(undefined4 *)(unaff_r27 + 0x94) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ec4);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000d0);
    *(undefined4 *)(unaff_r27 + 0x98) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x16,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ec0);
    *piVar8 = 1;
    piVar8[1] = 10;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    uVar2 = puVar4[9];
    *(undefined1 *)((int)piVar8 + 0x12) = puVar4[10];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x11) = uVar2;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x0000008c);
    *(undefined4 *)(unaff_r27 + 0x9c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ebc);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000090);
    *(undefined4 *)(unaff_r27 + 0xa0) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7eb8);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000094);
    *(undefined4 *)(unaff_r27 + 0xa4) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x16,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7eb4);
    *piVar8 = 1;
    piVar8[1] = 10;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    uVar2 = puVar4[9];
    *(undefined1 *)((int)piVar8 + 0x12) = puVar4[10];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x11) = uVar2;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000098);
    *(undefined4 *)(unaff_r27 + 0xa8) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7eb0);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000088);
    *(undefined4 *)(unaff_r27 + 0xac) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x16,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7eac);
    *piVar8 = 1;
    piVar8[1] = 10;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    uVar2 = puVar4[9];
    *(undefined1 *)((int)piVar8 + 0x12) = puVar4[10];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x11) = uVar2;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000084);
    *(undefined4 *)(unaff_r27 + 0xb0) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ea8);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000074);
    *(undefined4 *)(unaff_r27 + 0xb4) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ea4);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000078);
    *(undefined4 *)(unaff_r27 + 0xb8) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x16,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ea0);
    *piVar8 = 1;
    piVar8[1] = 10;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    uVar2 = puVar4[9];
    *(undefined1 *)((int)piVar8 + 0x12) = puVar4[10];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x11) = uVar2;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x0000007c);
    *(undefined4 *)(unaff_r27 + 0xbc) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e9c);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000080);
    *(undefined4 *)(unaff_r27 + 0xc0) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e98);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x0000009c);
    *(undefined4 *)(unaff_r27 + 0xc4) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x16,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e94);
    *piVar8 = 1;
    piVar8[1] = 10;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    uVar2 = puVar4[9];
    *(undefined1 *)((int)piVar8 + 0x12) = puVar4[10];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x11) = uVar2;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000a0);
    *(undefined4 *)(unaff_r27 + 200) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e90);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000a4);
    *(undefined4 *)(unaff_r27 + 0xcc) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e8c);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000c0);
    *(undefined4 *)(unaff_r27 + 0xd0) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x16,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e88);
    *piVar8 = 1;
    piVar8[1] = 10;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    uVar2 = puVar4[9];
    *(undefined1 *)((int)piVar8 + 0x12) = puVar4[10];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x11) = uVar2;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000c4);
    *(undefined4 *)(unaff_r27 + 0xd4) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e84);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000c8);
    *(undefined4 *)(unaff_r27 + 0xd8) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e80);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000cc);
    *(undefined4 *)(unaff_r27 + 0xdc) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x16,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e7c);
    *piVar8 = 1;
    piVar8[1] = 10;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    uVar2 = puVar4[9];
    *(undefined1 *)((int)piVar8 + 0x12) = puVar4[10];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x11) = uVar2;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000bc);
    *(undefined4 *)(unaff_r27 + 0xe0) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e78);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000b8);
    *(undefined4 *)(unaff_r27 + 0xe4) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x16,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e74);
    *piVar8 = 1;
    piVar8[1] = 10;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    uVar2 = puVar4[9];
    *(undefined1 *)((int)piVar8 + 0x12) = puVar4[10];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x11) = uVar2;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000a8);
    *(undefined4 *)(unaff_r27 + 0xe8) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e70);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000ac);
    *(undefined4 *)(unaff_r27 + 0xec) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e6c);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000b0);
    *(undefined4 *)(unaff_r27 + 0xf0) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x14,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e68);
    *piVar8 = 1;
    piVar8[1] = 8;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000b4);
    *(undefined4 *)(unaff_r27 + 0xf4) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x11,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e64);
    *piVar8 = 1;
    piVar8[1] = 5;
    uVar1 = puVar4[2];
    uVar2 = puVar4[3];
    uVar3 = puVar4[1];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar3;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar2;
    uVar1 = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = puVar4[5];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000138);
    *(undefined4 *)(unaff_r27 + 0xf8) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x18,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e60);
    *piVar8 = 1;
    piVar8[1] = 0xc;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x0000013c);
    *(undefined4 *)(unaff_r27 + 0xfc) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e5c);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000140);
    *(undefined4 *)(unaff_r27 + 0x100) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e58);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001c4);
    *(undefined4 *)(unaff_r27 + 0x104) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e54);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001c8);
    *(undefined4 *)(unaff_r27 + 0x108) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e50);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001cc);
    *(undefined4 *)(unaff_r27 + 0x10c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e4c);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001d0);
    *(undefined4 *)(unaff_r27 + 0x110) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e48);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001c0);
    *(undefined4 *)(unaff_r27 + 0x114) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e44);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001bc);
    *(undefined4 *)(unaff_r27 + 0x118) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e40);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001ac);
    *(undefined4 *)(unaff_r27 + 0x11c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e3c);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001b0);
    *(undefined4 *)(unaff_r27 + 0x120) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e38);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001b4);
    *(undefined4 *)(unaff_r27 + 0x124) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e34);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001b8);
    *(undefined4 *)(unaff_r27 + 0x128) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e30);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001d4);
    *(undefined4 *)(unaff_r27 + 300) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e2c);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001d8);
    *(undefined4 *)(unaff_r27 + 0x130) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e28);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001dc);
    *(undefined4 *)(unaff_r27 + 0x134) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e24);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001f8);
    *(undefined4 *)(unaff_r27 + 0x138) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e20);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001fc);
    *(undefined4 *)(unaff_r27 + 0x13c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e1c);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000200);
    *(undefined4 *)(unaff_r27 + 0x140) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e18);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000204);
    *(undefined4 *)(unaff_r27 + 0x144) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e14);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001f4);
    *(undefined4 *)(unaff_r27 + 0x148) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e10);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001f0);
    *(undefined4 *)(unaff_r27 + 0x14c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e0c);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001e0);
    *(undefined4 *)(unaff_r27 + 0x150) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e08);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001e4);
    *(undefined4 *)(unaff_r27 + 0x154) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e04);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001e8);
    *(undefined4 *)(unaff_r27 + 0x158) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x18,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7e00);
    *piVar8 = 1;
    piVar8[1] = 0xc;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001ec);
    *(undefined4 *)(unaff_r27 + 0x15c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7dfc);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001a8);
    *(undefined4 *)(unaff_r27 + 0x160) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7df8);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001a4);
    *(undefined4 *)(unaff_r27 + 0x164) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7df4);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000001a0);
    *(undefined4 *)(unaff_r27 + 0x168) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7df0);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x0000015c);
    *(undefined4 *)(unaff_r27 + 0x16c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7dec);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000160);
    *(undefined4 *)(unaff_r27 + 0x170) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7de8);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000164);
    *(undefined4 *)(unaff_r27 + 0x174) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7de4);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000168);
    *(undefined4 *)(unaff_r27 + 0x178) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7de0);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000158);
    *(undefined4 *)(unaff_r27 + 0x17c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ddc);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000154);
    *(undefined4 *)(unaff_r27 + 0x180) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x16,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7dd8);
    *piVar8 = 1;
    piVar8[1] = 10;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    uVar2 = puVar4[9];
    *(undefined1 *)((int)piVar8 + 0x12) = puVar4[10];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x11) = uVar2;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000144);
    *(undefined4 *)(unaff_r27 + 0x184) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7dd4);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000148);
    *(undefined4 *)(unaff_r27 + 0x188) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7dd0);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x0000014c);
    *(undefined4 *)(unaff_r27 + 0x18c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7dcc);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000150);
    *(undefined4 *)(unaff_r27 + 400) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7dc8);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x0000016c);
    *(undefined4 *)(unaff_r27 + 0x194) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7dc4);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000170);
    *(undefined4 *)(unaff_r27 + 0x198) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7dc0);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000174);
    *(undefined4 *)(unaff_r27 + 0x19c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7dbc);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000190);
    *(undefined4 *)(unaff_r27 + 0x1a0) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7db8);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000194);
    *(undefined4 *)(unaff_r27 + 0x1a4) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7db4);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000198);
    *(undefined4 *)(unaff_r27 + 0x1a8) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7db0);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x0000019c);
    *(undefined4 *)(unaff_r27 + 0x1ac) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7dac);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x0000018c);
    *(undefined4 *)(unaff_r27 + 0x1b0) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7da8);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000188);
    *(undefined4 *)(unaff_r27 + 0x1b4) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x1a,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7da4);
    *piVar8 = 1;
    piVar8[1] = 0xe;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    uVar1 = puVar4[0xe];
    uVar2 = puVar4[0xd];
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    *(undefined1 *)((int)piVar8 + 0x16) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x15) = uVar2;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000178);
    *(undefined4 *)(unaff_r27 + 0x1b8) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x1a,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7da0);
    *piVar8 = 1;
    piVar8[1] = 0xe;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    uVar1 = puVar4[0xe];
    uVar2 = puVar4[0xd];
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    *(undefined1 *)((int)piVar8 + 0x16) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x15) = uVar2;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x0000017c);
    *(undefined4 *)(unaff_r27 + 0x1bc) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x1a,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7d9c);
    *piVar8 = 1;
    piVar8[1] = 0xe;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    uVar1 = puVar4[0xe];
    uVar2 = puVar4[0xd];
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    *(undefined1 *)((int)piVar8 + 0x16) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x15) = uVar2;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000180);
    *(undefined4 *)(unaff_r27 + 0x1c0) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x15,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7d98);
    *piVar8 = 1;
    piVar8[1] = 9;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = puVar4[9];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000184);
    *(undefined4 *)(unaff_r27 + 0x1c4) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x15,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7d94);
    *piVar8 = 1;
    piVar8[1] = 9;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = puVar4[9];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000070);
    *(undefined4 *)(unaff_r27 + 0x1c8) = uVar6;
    if (piVar8 == (int *)0x0) {
      return;
    }
    iVar7 = *piVar8;
    *piVar8 = iVar7 + -1;
    if (iVar7 + -1 != 0) {
      return;
    }
    piVar5 = (int *)*puVar12;
  }
  else {
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x13,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7f1c);
    *piVar8 = 1;
    piVar8[1] = 7;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[4];
    uVar2 = puVar4[5];
    uVar3 = puVar4[6];
    *(undefined1 *)((int)piVar8 + 0xf) = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xd) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000f8);
    *(undefined4 *)(unaff_r27 + 0x7c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x17,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7f18);
    *piVar8 = 1;
    piVar8[1] = 0xb;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    uVar2 = puVar4[9];
    uVar3 = puVar4[10];
    *(undefined1 *)((int)piVar8 + 0x13) = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x11) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000fc);
    *(undefined4 *)(unaff_r27 + 0x7c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x17,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7f14);
    *piVar8 = 1;
    piVar8[1] = 0xb;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    uVar2 = puVar4[9];
    uVar3 = puVar4[10];
    *(undefined1 *)((int)piVar8 + 0x13) = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x11) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000100);
    *(undefined4 *)(unaff_r27 + 0x80) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x17,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7f10);
    *piVar8 = 1;
    piVar8[1] = 0xb;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    uVar2 = puVar4[9];
    uVar3 = puVar4[10];
    *(undefined1 *)((int)piVar8 + 0x13) = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x11) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000f0);
    *(undefined4 *)(unaff_r27 + 0x84) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x17,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7f0c);
    *piVar8 = 1;
    piVar8[1] = 0xb;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[8];
    uVar2 = puVar4[9];
    uVar3 = puVar4[10];
    *(undefined1 *)((int)piVar8 + 0x13) = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x11) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar3;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000ec);
    *(undefined4 *)(unaff_r27 + 0x88) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x10,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7f08);
    *piVar8 = 1;
    piVar8[1] = 4;
    uVar1 = puVar4[2];
    uVar2 = puVar4[1];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar2;
    *(undefined1 *)((int)piVar8 + 10) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000dc);
    *(undefined4 *)(unaff_r27 + 0x8c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0xf,0x10);
    *piVar8 = 1;
    piVar8[1] = 3;
    *(undefined1 *)((int)piVar8 + 0xb) = 0;
    *(undefined1 *)(piVar8 + 2) = 0x70;
    *(undefined1 *)((int)piVar8 + 9) = 0x69;
    *(undefined1 *)((int)piVar8 + 10) = 99;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000e0);
    *(undefined4 *)(unaff_r27 + 0x90) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x19,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7f04);
    *piVar8 = 1;
    piVar8[1] = 0xd;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    uVar1 = puVar4[0xd];
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    *(undefined1 *)((int)piVar8 + 0x15) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000e4);
    *(undefined4 *)(unaff_r27 + 0x94) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x19,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7f00);
    *piVar8 = 1;
    piVar8[1] = 0xd;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    uVar1 = puVar4[0xd];
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    *(undefined1 *)((int)piVar8 + 0x15) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x000000e8);
    *(undefined4 *)(unaff_r27 + 0x98) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x19,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7efc);
    *piVar8 = 1;
    piVar8[1] = 0xd;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    uVar1 = puVar4[0xd];
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    *(undefined1 *)((int)piVar8 + 0x15) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000104);
    *(undefined4 *)(unaff_r27 + 0x9c) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x19,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ef8);
    *piVar8 = 1;
    piVar8[1] = 0xd;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    uVar1 = puVar4[0xd];
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    *(undefined1 *)((int)piVar8 + 0x15) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000108);
    *(undefined4 *)(unaff_r27 + 0xa0) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x19,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ef4);
    *piVar8 = 1;
    piVar8[1] = 0xd;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    uVar1 = puVar4[0xd];
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    *(undefined1 *)((int)piVar8 + 0x15) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x0000010c);
    *(undefined4 *)(unaff_r27 + 0xa4) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x19,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ef0);
    *piVar8 = 1;
    piVar8[1] = 0xd;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    uVar1 = puVar4[0xd];
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    *(undefined1 *)((int)piVar8 + 0x15) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000128);
    *(undefined4 *)(unaff_r27 + 0xa8) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x19,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7eec);
    *piVar8 = 1;
    piVar8[1] = 0xd;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    uVar1 = puVar4[0xd];
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    *(undefined1 *)((int)piVar8 + 0x15) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x0000012c);
    *(undefined4 *)(unaff_r27 + 0xac) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x19,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ee8);
    *piVar8 = 1;
    piVar8[1] = 0xd;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    uVar1 = puVar4[0xd];
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    *(undefined1 *)((int)piVar8 + 0x15) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000130);
    *(undefined4 *)(unaff_r27 + 0xb0) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x19,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ee4);
    *piVar8 = 1;
    piVar8[1] = 0xd;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    uVar1 = puVar4[0xd];
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    *(undefined1 *)((int)piVar8 + 0x15) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000134);
    *(undefined4 *)(unaff_r27 + 0xb4) = uVar6;
    if ((piVar8 != (int *)0x0) && (iVar7 = *piVar8, *piVar8 = iVar7 + -1, iVar7 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x1c))((int *)*puVar12,piVar8);
    }
    piVar8 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x19,0x10)
    ;
    puVar4 = *(undefined1 **)(unaff_r30 + -0x7ee0);
    *piVar8 = 1;
    piVar8[1] = 0xd;
    uVar1 = puVar4[1];
    uVar2 = puVar4[2];
    uVar3 = puVar4[3];
    *(undefined1 *)(piVar8 + 2) = *puVar4;
    *(undefined1 *)((int)piVar8 + 9) = uVar1;
    *(undefined1 *)((int)piVar8 + 10) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xb) = uVar3;
    uVar1 = puVar4[5];
    uVar2 = puVar4[6];
    uVar3 = puVar4[7];
    *(undefined1 *)(piVar8 + 3) = puVar4[4];
    *(undefined1 *)((int)piVar8 + 0xd) = uVar1;
    *(undefined1 *)((int)piVar8 + 0xe) = uVar2;
    *(undefined1 *)((int)piVar8 + 0xf) = uVar3;
    uVar1 = puVar4[9];
    uVar2 = puVar4[10];
    uVar3 = puVar4[0xb];
    *(undefined1 *)(piVar8 + 4) = puVar4[8];
    *(undefined1 *)((int)piVar8 + 0x11) = uVar1;
    *(undefined1 *)((int)piVar8 + 0x12) = uVar2;
    *(undefined1 *)((int)piVar8 + 0x13) = uVar3;
    uVar1 = puVar4[0xd];
    *(undefined1 *)(piVar8 + 5) = puVar4[0xc];
    *(undefined1 *)((int)piVar8 + 0x15) = uVar1;
    uVar6 = func_0x00ad6d18(unaff_r28,&stack0x00000124);
    *(undefined4 *)(unaff_r27 + 0xb8) = uVar6;
    if (piVar8 == (int *)0x0) {
      return;
    }
    iVar7 = *piVar8;
    *piVar8 = iVar7 + -1;
    if (iVar7 + -1 != 0) {
      return;
    }
    piVar5 = (int *)*puVar12;
  }
  (*(code *)**(undefined4 **)(*piVar5 + 0x1c))(piVar5,piVar8);
  return;
}


