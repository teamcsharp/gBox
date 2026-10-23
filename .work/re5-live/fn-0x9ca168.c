
/* WARNING: Control flow encountered bad instruction data */

void FUN_009ca168(undefined8 param_1,int *param_2,int *param_3,undefined4 param_4)

{
  float fVar1;
  code *pcVar2;
  int iVar3;
  uint uVar4;
  undefined1 auVar5 [32];
  undefined1 auVar6 [32];
  ulonglong *puVar7;
  undefined4 *puVar8;
  undefined4 *puVar9;
  undefined4 *puVar10;
  int in_r0;
  ulonglong uVar11;
  ulonglong uVar12;
  int iVar13;
  int iVar14;
  int iVar15;
  int iVar16;
  int iVar17;
  char cVar18;
  longlong lVar19;
  longlong lVar20;
  ulonglong uVar21;
  int *piVar22;
  undefined4 uVar23;
  ulonglong unaff_r21;
  ulonglong unaff_r22;
  ulonglong unaff_r23;
  ulonglong unaff_r24;
  ulonglong unaff_r25;
  ulonglong unaff_r26;
  ulonglong unaff_r27;
  ulonglong unaff_r28;
  ulonglong unaff_r29;
  ulonglong unaff_r30;
  ulonglong unaff_r31;
  ulonglong in_LR;
  ulonglong in_f30;
  double dVar24;
  ulonglong in_f31;
  double dVar25;
  undefined4 uVar27;
  undefined4 uVar28;
  undefined4 uVar29;
  undefined4 uVar30;
  undefined4 uVar31;
  undefined1 auVar26 [16];
  undefined4 uVar32;
  undefined4 uVar33;
  undefined1 auVar34 [16];
  undefined1 auVar35 [16];
  undefined1 auVar36 [16];
  undefined1 auVar37 [16];
  undefined1 auVar38 [16];
  undefined4 in_vr30_32_0;
  undefined4 in_vr30_32_1;
  undefined4 in_vr30_32_2;
  undefined4 in_vr30_32_3;
  undefined4 in_vr31_32_0;
  undefined4 in_vr31_32_1;
  undefined4 in_vr31_32_2;
  undefined4 in_vr31_32_3;
  undefined1 auVar39 [16];
  
  uVar11 = ZEXT48(&stack0x00000000);
  puVar7 = (ulonglong *)(uVar11 - 0x390);
  *puVar7 = uVar11;
  puVar8 = (undefined4 *)((int)puVar7 + in_r0 & 0xfffffff0);
  *puVar8 = in_vr30_32_0;
  puVar8[1] = in_vr30_32_1;
  puVar8[2] = in_vr30_32_2;
  puVar8[3] = in_vr30_32_3;
  *(undefined4 *)(puVar7 + 0x62) = in_vr31_32_0;
  *(undefined4 *)((int)puVar7 + 0x314) = in_vr31_32_1;
  *(undefined4 *)(puVar7 + 99) = in_vr31_32_2;
  *(undefined4 *)((int)puVar7 + 0x31c) = in_vr31_32_3;
  puVar7[0x68] = unaff_r24;
  puVar7[0x6e] = unaff_r30;
  puVar7[0x6f] = unaff_r31;
  puVar7[0x70] = in_f30;
  puVar7[0x71] = in_f31;
  puVar7[0x65] = unaff_r21;
  puVar7[0x66] = unaff_r22;
  puVar7[0x67] = unaff_r23;
  puVar7[0x69] = unaff_r25;
  puVar7[0x6a] = unaff_r26;
  puVar7[0x6b] = unaff_r27;
  puVar7[0x6c] = unaff_r28;
  puVar7[0x6d] = unaff_r29;
  puVar7[0x74] = in_LR;
  iVar16 = iRam01714ecc;
  if (param_2 == (int *)0x0) {
    return;
  }
  if (param_3 == (int *)0x0) {
    return;
  }
  pcVar2 = (code *)**(undefined4 **)(*param_2 + 0x14);
  puVar7[5] = 0x171c590;
  iVar13 = (*pcVar2)(param_2);
  iVar17 = *(int *)(iVar16 + -0x7f14);
  iVar14 = *(int *)(iVar17 + 4);
  if (*(int *)(iVar13 + 4) != iVar14) {
    iVar13 = *(int *)(iVar13 + 0x10);
    if (iVar13 == 0) {
LAB_009ca254:
      param_2 = (int *)0x0;
    }
    else {
      iVar15 = *(int *)(iVar13 + 4);
      while (iVar15 != iVar14) {
        iVar13 = *(int *)(iVar13 + 0x10);
        if (iVar13 == 0) goto LAB_009ca254;
        iVar15 = *(int *)(iVar13 + 4);
      }
    }
  }
  pcVar2 = (code *)**(undefined4 **)(*param_3 + 0x14);
  puVar7[5] = puVar7[5];
  iVar14 = (*pcVar2)(param_3);
  uVar12 = puVar7[5];
  iVar17 = *(int *)(iVar17 + 4);
  if (*(int *)(iVar14 + 4) != iVar17) {
    iVar14 = *(int *)(iVar14 + 0x10);
    if (iVar14 == 0) {
LAB_009ca2dc:
      param_3 = (int *)0x0;
    }
    else {
      iVar13 = *(int *)(iVar14 + 4);
      while (iVar13 != iVar17) {
        iVar14 = *(int *)(iVar14 + 0x10);
        if (iVar14 == 0) goto LAB_009ca2dc;
        iVar13 = *(int *)(iVar14 + 4);
      }
    }
  }
  if (param_2 == (int *)0x0) {
    return;
  }
  if (param_3 == (int *)0x0) {
    return;
  }
  if (param_2[0x31] != 0) {
    return;
  }
  if (param_3[0x31] != 1) {
    return;
  }
  iVar17 = param_2[0x30];
  if (iVar17 == 0) {
    return;
  }
  if (((param_2[0x26] & 0x20U) == 0) && ((param_3[0x34] & param_2[0x33]) == 0)) {
    return;
  }
  iVar14 = *(int *)(param_3[0x39] + 0xc);
  if ((((iVar14 == 0) || ((param_2[0x28] & 0x10U) != 0)) || ((param_3[0x28] & 0x10U) != 0)) ||
     ((param_2[0x39] == 0 || (piVar22 = *(int **)(param_2[0x39] + 0x10), piVar22 == (int *)0x0)))) {
    uVar21 = 0xffffffffffffffff;
    iVar13 = 0;
  }
  else {
    pcVar2 = (code *)**(undefined4 **)(*piVar22 + 0x14);
    puVar7[5] = uVar12;
    iVar15 = (*pcVar2)(piVar22);
    uVar12 = puVar7[5];
    iVar13 = *(int *)(*(int *)(iVar16 + -0x7f10) + 4);
    if (*(int *)(iVar15 + 4) != iVar13) {
      iVar15 = *(int *)(iVar15 + 0x10);
      if (iVar15 == 0) {
LAB_009ca478:
        piVar22 = (int *)0x0;
      }
      else {
        iVar3 = *(int *)(iVar15 + 4);
        while (iVar3 != iVar13) {
          iVar15 = *(int *)(iVar15 + 0x10);
          if (iVar15 == 0) goto LAB_009ca478;
          iVar3 = *(int *)(iVar15 + 4);
        }
      }
    }
    iVar15 = piVar22[0x444];
    if (iVar15 == *(int *)(iVar14 + 200)) {
LAB_009ca4cc:
      uVar21 = 0xffffffffffffffff;
      iVar13 = 0;
    }
    else {
      uVar21 = 0;
      iVar13 = iVar15;
      if (*(int *)(iVar14 + 200) != 0) {
        if (iVar15 == *(int *)(iVar14 + 0xcc)) goto LAB_009ca4cc;
        uVar21 = 1;
        if (*(int *)(iVar14 + 0xcc) != 0) {
          if ((iVar15 == *(int *)(iVar14 + 0xd0)) || (*(int *)(iVar14 + 0xd0) != 0))
          goto LAB_009ca4cc;
          uVar21 = 2;
        }
      }
    }
    if (((*(int *)(iVar14 + 0xd4) == iVar15) || (*(int *)(iVar14 + 0xd8) == iVar15)) ||
       (*(int *)(iVar14 + 0xdc) == iVar15)) {
      *(int *)(iVar14 + (int)((uVar21 & 0xffffffff) << 2) + 200) = iVar15;
      return;
    }
  }
  func_0x00918d9c(uVar11 - 0x290,param_2,param_3,param_4);
  auVar39 = *(undefined1 (*) [16])(puVar7 + 0x20);
  auVar26 = vectorSubtractFloatingPoint
                      (auVar39,*(undefined1 (*) [16])(iVar17 + 0x370U & 0xfffffff0));
  auVar37 = vectorMultiplyAddFloatingPoint(auVar26,auVar26,(undefined1  [16])0x0);
  auVar5._0_16_ = auVar26;
  auVar5._16_16_ = auVar26;
  auVar6._0_16_ = auVar26;
  auVar6._16_16_ = auVar26;
  auVar26 = vectorMultiplyAddFloatingPoint(auVar5._4_16_,auVar5._4_16_,auVar37);
  auVar26 = vectorMultiplyAddFloatingPoint(auVar6._8_16_,auVar6._8_16_,auVar26);
  auVar38 = vectorReciprocalSquareRootEstimateFloatingPoint(auVar26);
  auVar35 = vectorCompareEqualToFloatingPoint(auVar26,(undefined1  [16])0x0);
  auVar36 = vectorMultiplyAddFloatingPoint(auVar38,auVar26,(undefined1  [16])0x0);
  auVar37 = vectorCompareEqualToFloatingPoint(auVar38,(undefined1  [16])0x0);
  auVar34 = vectorMultiplyAddFloatingPoint
                      (auVar36,*(undefined1 (*) [16])(*(uint *)(iVar16 + -0x7e88) & 0xfffffff0),
                       (undefined1  [16])0x0);
  auVar38 = vectorNegativeMultiplySubtractFloatingPoint
                      (auVar38,auVar36,
                       *(undefined1 (*) [16])(*(uint *)(iVar16 + -0x7e84) & 0xfffffff0));
  auVar34 = vectorMultiplyAddFloatingPoint(auVar38,auVar34,auVar36);
  auVar26 = vectorConditionalSelect(auVar34,auVar26,auVar35 | auVar37);
  uVar28 = storeVectorElementWordIndexed(auVar26,uVar11 - 0x390,0x2f0);
  *(undefined4 *)(puVar7 + 0x5e) = uVar28;
  dVar24 = (double)*(float *)(puVar7 + 0x5e);
  if ((param_2[0x26] & 0x10U) == 0) {
    if ((double)*(float *)(iVar17 + 0x3d8) <= dVar24) {
      return;
    }
    iVar16 = func_0x009cb7dc(iVar17,0);
    iVar14 = func_0x009cb7dc(iVar17,1);
    if (*(int *)(iVar16 + 0x20) == 0) {
      *(undefined4 *)(iVar17 + 0x3ec) = 0;
      goto LAB_009ca870;
    }
    if (*(int *)(iVar14 + 0x20) != 0) {
      if ((*(int **)(iVar16 + 0x24) == param_3) && ((double)*(float *)(iVar16 + 0x28) == dVar24)) {
        return;
      }
      if ((*(int **)(iVar14 + 0x24) == param_3) && ((double)*(float *)(iVar14 + 0x28) == dVar24)) {
        return;
      }
      if ((param_3[0x27] & 0x10000U) == 0) {
        if (dVar24 < (double)*(float *)(iVar16 + 0x28)) goto LAB_009ca870;
      }
      else if (dVar24 < (double)*(float *)(iVar16 + 0x28)) {
        *(undefined4 *)(iVar17 + 1000) = 2;
        uVar30 = *(undefined4 *)(iVar16 + 0x20);
        puVar8 = (undefined4 *)(iVar16 + 0x10U & 0xfffffff0);
        uVar27 = puVar8[1];
        uVar29 = puVar8[2];
        uVar32 = puVar8[3];
        uVar28 = *(undefined4 *)(iVar16 + 0x28);
        uVar23 = *(undefined4 *)(iVar16 + 0x24);
        puVar9 = (undefined4 *)(iVar14 + 0x10U & 0xfffffff0);
        *puVar9 = *puVar8;
        puVar9[1] = uVar27;
        puVar9[2] = uVar29;
        puVar9[3] = uVar32;
        *(undefined4 *)(iVar14 + 0x28) = uVar28;
        *(undefined1 (*) [16])(iVar16 + 0x10U & 0xfffffff0) = auVar39;
        *(undefined4 *)(iVar14 + 0x20) = uVar30;
        goto LAB_009ca66c;
      }
      if (dVar24 < (double)*(float *)(iVar14 + 0x28)) {
        *(undefined4 *)(iVar17 + 1000) = 2;
        *(undefined1 (*) [16])(iVar14 + 0x10U & 0xfffffff0) = auVar39;
        iVar16 = param_3[0x24];
        *(float *)(iVar14 + 0x28) = (float)dVar24;
        *(int *)(iVar14 + 0x20) = iVar16;
        *(int **)(iVar14 + 0x24) = param_3;
      }
      goto LAB_009ca680;
    }
    if ((param_3 == *(int **)(iVar16 + 0x24)) && ((double)*(float *)(iVar16 + 0x28) == dVar24)) {
      return;
    }
    if (((*(int **)(iVar16 + 0x24))[0x27] & 0x10000U) == 0) {
      if ((param_3[0x27] & 0x10000U) == 0) {
        if ((double)*(float *)(iVar16 + 0x28) <= dVar24) goto LAB_009ca680;
        goto LAB_009ca870;
      }
      if ((double)*(float *)(iVar16 + 0x28) <= dVar24) goto LAB_009ca680;
      *(undefined4 *)(iVar17 + 1000) = 2;
      uVar30 = *(undefined4 *)(iVar16 + 0x20);
      puVar8 = (undefined4 *)(iVar16 + 0x10U & 0xfffffff0);
      uVar27 = puVar8[1];
      uVar29 = puVar8[2];
      uVar32 = puVar8[3];
      uVar23 = *(undefined4 *)(iVar16 + 0x24);
      uVar28 = *(undefined4 *)(iVar16 + 0x28);
      puVar9 = (undefined4 *)(iVar14 + 0x10U & 0xfffffff0);
      *puVar9 = *puVar8;
      puVar9[1] = uVar27;
      puVar9[2] = uVar29;
      puVar9[3] = uVar32;
      *(undefined4 *)(iVar14 + 0x28) = uVar28;
      *(undefined1 (*) [16])(iVar16 + 0x10U & 0xfffffff0) = auVar39;
      *(undefined4 *)(iVar14 + 0x20) = uVar30;
    }
    else {
      if ((param_3[0x27] & 0x10000U) == 0) {
        if ((double)*(float *)(iVar16 + 0x28) <= dVar24) {
          *(undefined4 *)(iVar17 + 1000) = 2;
          *(undefined1 (*) [16])(iVar14 + 0x10U & 0xfffffff0) = auVar39;
          iVar16 = param_3[0x24];
          *(float *)(iVar14 + 0x28) = (float)dVar24;
          *(int *)(iVar14 + 0x20) = iVar16;
          *(int **)(iVar14 + 0x24) = param_3;
          goto LAB_009ca680;
        }
LAB_009ca870:
        *(undefined4 *)(iVar17 + 1000) = 1;
        *(undefined1 (*) [16])(iVar16 + 0x10U & 0xfffffff0) = auVar39;
        iVar17 = param_3[0x24];
        *(float *)(iVar16 + 0x28) = (float)dVar24;
        *(int *)(iVar16 + 0x20) = iVar17;
        *(int **)(iVar16 + 0x24) = param_3;
        goto LAB_009ca680;
      }
      *(undefined4 *)(iVar17 + 1000) = 2;
      if ((double)*(float *)(iVar16 + 0x28) <= dVar24) {
        *(undefined1 (*) [16])(iVar14 + 0x10U & 0xfffffff0) = auVar39;
        iVar16 = param_3[0x24];
        *(float *)(iVar14 + 0x28) = (float)dVar24;
        *(int *)(iVar14 + 0x20) = iVar16;
        *(int **)(iVar14 + 0x24) = param_3;
        goto LAB_009ca680;
      }
      uVar28 = *(undefined4 *)(iVar16 + 0x20);
      uVar23 = *(undefined4 *)(iVar16 + 0x24);
      *(float *)(iVar14 + 0x28) = *(float *)(iVar16 + 0x28);
      *(undefined4 *)(iVar14 + 0x20) = uVar28;
      puVar8 = (undefined4 *)(iVar16 + 0x10U & 0xfffffff0);
      uVar28 = puVar8[1];
      uVar30 = puVar8[2];
      uVar27 = puVar8[3];
      puVar9 = (undefined4 *)(iVar14 + 0x10U & 0xfffffff0);
      *puVar9 = *puVar8;
      puVar9[1] = uVar28;
      puVar9[2] = uVar30;
      puVar9[3] = uVar27;
      *(undefined1 (*) [16])(iVar16 + 0x10U & 0xfffffff0) = auVar39;
    }
LAB_009ca66c:
    *(undefined4 *)(iVar14 + 0x24) = uVar23;
    iVar17 = param_3[0x24];
    *(float *)(iVar16 + 0x28) = (float)dVar24;
    *(int *)(iVar16 + 0x20) = iVar17;
    *(int **)(iVar16 + 0x24) = param_3;
    goto LAB_009ca680;
  }
  iVar14 = func_0x009cba44(iVar17,param_3[0x24]);
  iVar17 = *(int *)(iVar14 + 0x24);
  dVar25 = (double)*(float *)(iVar14 + 0x28);
  if (iVar17 != 0) {
    piVar22 = *(int **)(iVar17 + 0x90);
    if (piVar22 != (int *)0x0) {
      pcVar2 = (code *)**(undefined4 **)(*piVar22 + 0x14);
      puVar7[5] = uVar12;
      iVar15 = (*pcVar2)(piVar22);
      uVar12 = puVar7[5];
      if (*(char *)(iVar15 + 0x20) == '\x03') goto LAB_009ca734;
    }
    if ((*(uint *)(iVar17 + 0x9c) & 0x40000) != 0) goto LAB_009ca680;
  }
LAB_009ca734:
  if (dVar25 <= dVar24) goto LAB_009ca680;
  if (((param_2[0x27] & 0x20000U) != 0) || ((param_3[0x27] & 0x20000U) != 0)) goto LAB_009ca814;
  if ((param_3[0x39] != 0) && (piVar22 = *(int **)(param_3[0x39] + 0x10), piVar22 != (int *)0x0)) {
    pcVar2 = (code *)**(undefined4 **)(*piVar22 + 0x14);
    puVar7[5] = uVar12;
    iVar17 = (*pcVar2)(piVar22);
    uVar12 = puVar7[5];
    if (*(char *)(iVar17 + 0x20) == '\x01') {
      puVar8 = *(undefined4 **)(iVar16 + -0x7ed8);
      puVar9 = *(undefined4 **)(iVar16 + -0x7ee4);
      puVar10 = (undefined4 *)((uint)(piVar22 + 0x34) & 0xfffffff0);
      uVar23 = puVar10[1];
      uVar30 = puVar10[2];
      uVar27 = puVar10[3];
      uVar28 = *(undefined4 *)(*(int *)(iVar16 + -0x7ee8) + 0x28);
      *(undefined4 *)(puVar7 + 0x22) = *puVar10;
      *(undefined4 *)((int)puVar7 + 0x114) = uVar23;
      *(undefined4 *)(puVar7 + 0x23) = uVar30;
      *(undefined4 *)((int)puVar7 + 0x11c) = uVar27;
      *(undefined4 *)((int)puVar7 + 0x114) = *(undefined4 *)((int)puVar7 + 0x104);
      uVar30 = *puVar8;
      *(undefined4 *)(puVar7 + 0x48) = *(undefined4 *)(puVar7 + 0x22);
      *(undefined4 *)((int)puVar7 + 0x244) = *(undefined4 *)((int)puVar7 + 0x114);
      *(undefined4 *)(puVar7 + 0x49) = *(undefined4 *)(puVar7 + 0x23);
      *(undefined4 *)((int)puVar7 + 0x24c) = *(undefined4 *)((int)puVar7 + 0x11c);
      uVar23 = *puVar9;
      *(undefined4 *)(puVar7 + 0x59) = 10;
      *(undefined1 (*) [16])(puVar7 + 0x4a) = auVar39;
      *(undefined4 *)((int)puVar7 + 0x2d4) = uVar28;
      *(undefined4 *)(puVar7 + 0x5b) = 0;
      *(undefined4 *)((int)puVar7 + 0x2dc) = 0xf;
      *(undefined4 *)((int)puVar7 + 0x2e4) = uVar23;
      *(undefined4 *)(puVar7 + 0x5a) = uVar28;
      *(undefined4 *)(puVar7 + 0x5d) = 3;
      *(undefined4 *)(puVar7 + 0x53) = 2;
      *(undefined1 *)((int)puVar7 + 0x2cc) = 1;
      *(undefined1 *)((int)puVar7 + 0x2cd) = 1;
      *(undefined1 *)(puVar7 + 0x58) = 1;
      *(undefined4 *)(puVar7 + 0x56) = 0;
      *(undefined4 *)(puVar7 + 0x57) = 0;
      *(undefined4 *)((int)puVar7 + 0x2b4) = 0;
      *(undefined4 *)((int)puVar7 + 700) = 0;
      *(undefined4 *)((int)puVar7 + 0x2c4) = 0;
      *(undefined1 *)(puVar7 + 0x5c) = 0;
      *(undefined1 *)((int)puVar7 + 0x2ce) = 0;
      *(undefined1 *)((int)puVar7 + 0x2e1) = 0;
      *(undefined1 *)((int)puVar7 + 0x2ec) = 0;
      *(undefined4 *)((int)puVar7 + 0x29c) = uVar30;
      puVar8 = *(undefined4 **)(iVar16 + -0x7ff8);
      *(undefined1 *)(puVar7 + 0x55) = 1;
      puVar7[0x54] = 0xffffffffffffffff;
      *(undefined4 *)((int)puVar7 + 0x2ac) = 0;
      cVar18 = func_0x00bf6d18(*puVar8,uVar11 - 0x150,uVar11 - 0xf8);
      if (cVar18 != '\0') {
        return;
      }
    }
  }
  uVar4 = param_2[0x26];
  if ((uVar4 & 0x100000) == 0) {
    if ((uVar4 & 0x80000) != 0) {
      iVar17 = func_0x00beac80(param_2,0);
      if (iVar17 != 0) {
        iVar15 = *(int *)(iVar17 + 4);
        if (iVar15 == 6) {
          puVar8 = (undefined4 *)(iVar17 + 0x10U & 0xfffffff0);
          uVar28 = puVar8[1];
          uVar23 = puVar8[2];
          uVar30 = puVar8[3];
          *(undefined4 *)(puVar7 + 0x1e) = *puVar8;
          *(undefined4 *)((int)puVar7 + 0xf4) = uVar28;
          *(undefined4 *)(puVar7 + 0x1f) = uVar23;
          *(undefined4 *)((int)puVar7 + 0xfc) = uVar30;
        }
        else if (iVar15 < 7) {
          if (iVar15 == 5) {
            *(undefined4 *)(puVar7 + 0x1e) = *(undefined4 *)(iVar17 + 0x10);
            *(undefined4 *)((int)puVar7 + 0xf4) = *(undefined4 *)(iVar17 + 0x14);
            *(undefined4 *)(puVar7 + 0x1f) = *(undefined4 *)(iVar17 + 0x18);
          }
        }
        else {
          if (iVar15 == 7) {
                    /* WARNING: Bad instruction - Truncating control flow here */
            halt_baddata();
          }
          if (iVar15 == 8) {
            puVar8 = (undefined4 *)(iVar17 + 0x40U & 0xfffffff0);
            uVar28 = puVar8[1];
            uVar23 = puVar8[2];
            uVar30 = puVar8[3];
            *(undefined4 *)(puVar7 + 0x1e) = *puVar8;
            *(undefined4 *)((int)puVar7 + 0xf4) = uVar28;
            *(undefined4 *)(puVar7 + 0x1f) = uVar23;
            *(undefined4 *)((int)puVar7 + 0xfc) = uVar30;
          }
        }
      }
      piVar22 = (int *)param_2[0x35];
      if ((piVar22 != (int *)0x0) &&
         (((piVar22[1] & 0xe0000000U) == 0x40000000 || ((piVar22[1] & 0xe0000000U) == 0x20000000))))
      {
        pcVar2 = (code *)**(undefined4 **)(*piVar22 + 0x14);
        puVar7[5] = uVar12;
        iVar15 = (*pcVar2)(piVar22);
        iVar17 = *(int *)(*(int *)(iVar16 + -0x7f08) + 4);
        if (*(int *)(iVar15 + 4) != iVar17) {
          iVar15 = *(int *)(iVar15 + 0x10);
          if (iVar15 == 0) goto LAB_009caeec;
          iVar3 = *(int *)(iVar15 + 4);
          while (iVar3 != iVar17) {
            iVar15 = *(int *)(iVar15 + 0x10);
            if (iVar15 == 0) goto LAB_009caeec;
            iVar3 = *(int *)(iVar15 + 4);
          }
        }
        puVar8 = (undefined4 *)((uint)(piVar22 + 0x544) & 0xfffffff0);
        uVar28 = puVar8[1];
        uVar23 = puVar8[2];
        uVar30 = puVar8[3];
        *(undefined4 *)(puVar7 + 0x1e) = *puVar8;
        *(undefined4 *)((int)puVar7 + 0xf4) = uVar28;
        *(undefined4 *)(puVar7 + 0x1f) = uVar23;
        *(undefined4 *)((int)puVar7 + 0xfc) = uVar30;
      }
LAB_009caeec:
      lVar19 = uVar11 - 0x1b0;
      lVar20 = uVar11 - 0xf8;
      uVar28 = *(undefined4 *)(*(int *)(iVar16 + -0x7ee8) + 0x28);
      uVar23 = **(undefined4 **)(iVar16 + -0x7ee4);
      uVar30 = **(undefined4 **)(iVar16 + -0x7ed8);
      uVar27 = **(undefined4 **)(iVar16 + -0x7ff8);
      *(undefined4 *)(puVar7 + 0x3c) = *(undefined4 *)(puVar7 + 0x1e);
      *(undefined4 *)((int)puVar7 + 0x1e4) = *(undefined4 *)((int)puVar7 + 0xf4);
      *(undefined4 *)(puVar7 + 0x3d) = *(undefined4 *)(puVar7 + 0x1f);
      *(undefined4 *)((int)puVar7 + 0x1ec) = *(undefined4 *)((int)puVar7 + 0xfc);
      *(undefined1 (*) [16])(puVar7 + 0x3e) = auVar39;
      *(undefined4 *)(puVar7 + 0x59) = 10;
      *(undefined4 *)((int)puVar7 + 0x2d4) = uVar28;
      *(undefined4 *)((int)puVar7 + 0x2dc) = 0xf;
      *(undefined4 *)(puVar7 + 0x5b) = 0;
      *(undefined4 *)((int)puVar7 + 0x2e4) = uVar23;
      *(undefined4 *)(puVar7 + 0x5a) = uVar28;
      *(undefined4 *)(puVar7 + 0x5d) = 3;
      *(undefined4 *)(puVar7 + 0x53) = 2;
      *(undefined4 *)((int)puVar7 + 0x29c) = uVar30;
      puVar7[0x54] = 0xffffffffffffffff;
      *(undefined1 *)(puVar7 + 0x55) = 1;
      *(undefined4 *)((int)puVar7 + 0x2ac) = 0;
      *(undefined4 *)(puVar7 + 0x56) = 0;
      *(undefined4 *)(puVar7 + 0x57) = 0;
      *(undefined4 *)((int)puVar7 + 0x2b4) = 0;
      *(undefined4 *)((int)puVar7 + 700) = 0;
      *(undefined4 *)((int)puVar7 + 0x2c4) = 0;
      *(undefined1 *)((int)puVar7 + 0x2cc) = 1;
      *(undefined1 *)((int)puVar7 + 0x2cd) = 1;
      *(undefined1 *)(puVar7 + 0x5c) = 0;
      *(undefined1 *)((int)puVar7 + 0x2ce) = 0;
      *(undefined1 *)((int)puVar7 + 0x2e1) = 0;
      *(undefined1 *)((int)puVar7 + 0x2ec) = 0;
      *(undefined1 *)(puVar7 + 0x58) = 1;
      goto LAB_009caad8;
    }
    if ((uVar4 & 0x200000) != 0) {
      iVar17 = func_0x00beac80(param_2,0);
      if (iVar17 == 0) {
        puVar8 = (undefined4 *)(*(uint *)(iVar16 + -0x7fd4) & 0xfffffff0);
        uVar28 = puVar8[1];
        uVar23 = puVar8[2];
        uVar30 = puVar8[3];
        *(undefined4 *)(puVar7 + 0x26) = *puVar8;
        *(undefined4 *)((int)puVar7 + 0x134) = uVar28;
        *(undefined4 *)(puVar7 + 0x27) = uVar23;
        *(undefined4 *)((int)puVar7 + 0x13c) = uVar30;
      }
      else {
        iVar15 = *(int *)(iVar17 + 4);
        if (iVar15 == 6) {
LAB_009cb140:
          puVar8 = (undefined4 *)(iVar17 + 0x10U & 0xfffffff0);
          uVar28 = puVar8[1];
          uVar23 = puVar8[2];
          uVar30 = puVar8[3];
          *(undefined4 *)(puVar7 + 0x18) = *puVar8;
          *(undefined4 *)((int)puVar7 + 0xc4) = uVar28;
          *(undefined4 *)(puVar7 + 0x19) = uVar23;
          *(undefined4 *)((int)puVar7 + 0xcc) = uVar30;
                    /* WARNING: Bad instruction - Truncating control flow here */
          halt_baddata();
        }
        if (iVar15 < 7) {
          if (iVar15 == 5) {
            *(undefined4 *)(puVar7 + 0x16) = *(undefined4 *)(iVar17 + 0x10);
            *(undefined4 *)((int)puVar7 + 0xb4) = *(undefined4 *)(iVar17 + 0x14);
            *(undefined4 *)(puVar7 + 0x17) = *(undefined4 *)(iVar17 + 0x18);
          }
          else {
LAB_009cacd0:
            puVar8 = (undefined4 *)(*(uint *)(iVar16 + -0x7fd4) & 0xfffffff0);
            uVar28 = puVar8[1];
            uVar23 = puVar8[2];
            uVar30 = puVar8[3];
            *(undefined4 *)(puVar7 + 0x16) = *puVar8;
            *(undefined4 *)((int)puVar7 + 0xb4) = uVar28;
            *(undefined4 *)(puVar7 + 0x17) = uVar23;
            *(undefined4 *)((int)puVar7 + 0xbc) = uVar30;
          }
        }
        else {
          if (iVar15 == 7) goto LAB_009cb140;
          if (iVar15 != 8) goto LAB_009cacd0;
          puVar8 = (undefined4 *)(iVar17 + 0x40U & 0xfffffff0);
          uVar28 = puVar8[1];
          uVar23 = puVar8[2];
          uVar30 = puVar8[3];
          *(undefined4 *)(puVar7 + 0x16) = *puVar8;
          *(undefined4 *)((int)puVar7 + 0xb4) = uVar28;
          *(undefined4 *)(puVar7 + 0x17) = uVar23;
          *(undefined4 *)((int)puVar7 + 0xbc) = uVar30;
        }
        *(undefined4 *)(puVar7 + 0x26) = *(undefined4 *)(puVar7 + 0x16);
        *(undefined4 *)((int)puVar7 + 0x134) = *(undefined4 *)((int)puVar7 + 0xb4);
        *(undefined4 *)(puVar7 + 0x27) = *(undefined4 *)(puVar7 + 0x17);
        *(undefined4 *)((int)puVar7 + 0x13c) = *(undefined4 *)((int)puVar7 + 0xbc);
      }
      uVar28 = *(undefined4 *)(puVar7 + 0x26);
      uVar23 = *(undefined4 *)((int)puVar7 + 0x134);
      uVar30 = *(undefined4 *)(puVar7 + 0x27);
      uVar27 = *(undefined4 *)((int)puVar7 + 0x13c);
      iVar17 = func_0x00beac80(param_3,0);
      if (iVar17 != 0) {
        iVar15 = *(int *)(iVar17 + 4);
        if (iVar15 == 6) {
          puVar8 = (undefined4 *)(iVar17 + 0x10U & 0xfffffff0);
          uVar29 = puVar8[1];
          uVar32 = puVar8[2];
          uVar31 = puVar8[3];
          *(undefined4 *)(puVar7 + 0x12) = *puVar8;
          *(undefined4 *)((int)puVar7 + 0x94) = uVar29;
          *(undefined4 *)(puVar7 + 0x13) = uVar32;
          *(undefined4 *)((int)puVar7 + 0x9c) = uVar31;
          puVar8 = (undefined4 *)(iVar17 + 0x20U & 0xfffffff0);
          uVar29 = puVar8[1];
          uVar32 = puVar8[2];
          uVar31 = puVar8[3];
          *(undefined4 *)(puVar7 + 0x14) = *puVar8;
          *(undefined4 *)((int)puVar7 + 0xa4) = uVar29;
          *(undefined4 *)(puVar7 + 0x15) = uVar32;
          *(undefined4 *)((int)puVar7 + 0xac) = uVar31;
        }
        else if (iVar15 < 7) {
          if (iVar15 == 5) {
            uVar29 = *(undefined4 *)(iVar17 + 0x10);
            *(undefined4 *)(puVar7 + 0x12) = uVar29;
            uVar32 = *(undefined4 *)(iVar17 + 0x14);
            *(undefined4 *)((int)puVar7 + 0x94) = uVar32;
            uVar31 = *(undefined4 *)(iVar17 + 0x18);
            *(undefined4 *)(puVar7 + 0x15) = uVar31;
            *(undefined4 *)(puVar7 + 0x14) = uVar29;
            *(undefined4 *)((int)puVar7 + 0xa4) = uVar32;
            *(undefined4 *)(puVar7 + 0x13) = uVar31;
          }
        }
        else {
          if (iVar15 == 7) {
                    /* WARNING: Bad instruction - Truncating control flow here */
            halt_baddata();
          }
          if (iVar15 == 8) {
            puVar8 = (undefined4 *)(iVar17 + 0x40U & 0xfffffff0);
            uVar29 = *puVar8;
            uVar32 = puVar8[1];
            uVar31 = puVar8[2];
            uVar33 = puVar8[3];
            *(undefined4 *)(puVar7 + 0x1c) = uVar29;
            *(undefined4 *)((int)puVar7 + 0xe4) = uVar32;
            *(undefined4 *)(puVar7 + 0x1d) = uVar31;
            *(undefined4 *)((int)puVar7 + 0xec) = uVar33;
            *(undefined4 *)(puVar7 + 0x14) = uVar29;
            *(undefined4 *)((int)puVar7 + 0xa4) = uVar32;
            *(undefined4 *)(puVar7 + 0x15) = uVar31;
            *(undefined4 *)((int)puVar7 + 0xac) = uVar33;
            *(undefined4 *)(puVar7 + 0x12) = uVar29;
            *(undefined4 *)((int)puVar7 + 0x94) = uVar32;
            *(undefined4 *)(puVar7 + 0x13) = uVar31;
            *(undefined4 *)((int)puVar7 + 0x9c) = uVar33;
          }
        }
      }
      puVar8 = *(undefined4 **)(iVar16 + -0x7ee4);
      puVar9 = *(undefined4 **)(iVar16 + -0x7ed8);
      uVar29 = *(undefined4 *)(*(int *)(iVar16 + -0x7ee8) + 0x28);
      *(undefined4 *)(puVar7 + 0x4e) = 10;
      uVar32 = *puVar8;
      *(undefined4 *)((int)puVar7 + 0x284) = 0xf;
      *(undefined4 *)(puVar7 + 0x50) = 0;
      uVar31 = *puVar9;
      *(undefined4 *)((int)puVar7 + 0x27c) = uVar29;
      *(undefined4 *)(puVar7 + 0x52) = 3;
      *(undefined4 *)((int)puVar7 + 0x28c) = uVar32;
      *(undefined4 *)(puVar7 + 0x48) = 2;
      puVar7[0x49] = 0xffffffffffffffff;
      *(undefined4 *)(puVar7 + 0x4f) = uVar29;
      *(undefined4 *)((int)puVar7 + 0x244) = uVar31;
      *(undefined4 *)(puVar7 + 0x10) = uVar28;
      *(undefined4 *)((int)puVar7 + 0x84) = uVar23;
      *(undefined4 *)(puVar7 + 0x11) = uVar30;
      *(undefined4 *)((int)puVar7 + 0x8c) = uVar27;
      *(undefined1 *)(puVar7 + 0x4a) = 1;
      *(undefined4 *)((int)puVar7 + 0x254) = 0;
      *(undefined4 *)(puVar7 + 0x28) = uVar28;
      *(undefined4 *)((int)puVar7 + 0x144) = uVar23;
      *(undefined4 *)(puVar7 + 0x29) = uVar30;
      *(undefined4 *)((int)puVar7 + 0x14c) = uVar27;
      *(undefined4 *)(puVar7 + 0x4b) = 0;
      *(undefined4 *)(puVar7 + 0x4c) = 0;
      *(undefined4 *)((int)puVar7 + 0x25c) = 0;
      *(undefined4 *)((int)puVar7 + 0x264) = 0;
      *(undefined4 *)((int)puVar7 + 0x26c) = 0;
      *(undefined1 *)((int)puVar7 + 0x274) = 1;
      *(undefined1 *)((int)puVar7 + 0x275) = 1;
      *(undefined1 *)(puVar7 + 0x51) = 0;
      *(undefined1 *)((int)puVar7 + 0x276) = 0;
      *(undefined1 *)((int)puVar7 + 0x289) = 0;
      *(undefined1 *)((int)puVar7 + 0x294) = 0;
      *(undefined1 *)(puVar7 + 0x4d) = 1;
      *(undefined4 *)(puVar7 + 0x2a) = *(undefined4 *)(puVar7 + 0x12);
      *(undefined4 *)((int)puVar7 + 0x154) = *(undefined4 *)((int)puVar7 + 0x94);
      *(undefined4 *)(puVar7 + 0x2b) = *(undefined4 *)(puVar7 + 0x13);
      *(undefined4 *)((int)puVar7 + 0x15c) = *(undefined4 *)((int)puVar7 + 0x9c);
      puVar8 = *(undefined4 **)(iVar16 + -0x7ff8);
      uVar12 = uVar11 - 0x150 & 0xffffffff;
      cVar18 = func_0x00bf6d18(*puVar8,uVar11 - 0x250,uVar12);
      if (cVar18 == '\0') goto LAB_009ca814;
      uVar29 = *puVar8;
      *(undefined4 *)(puVar7 + 0x32) = *(undefined4 *)(puVar7 + 0x14);
      *(undefined4 *)((int)puVar7 + 0x194) = *(undefined4 *)((int)puVar7 + 0xa4);
      *(undefined4 *)(puVar7 + 0x33) = *(undefined4 *)(puVar7 + 0x15);
      *(undefined4 *)((int)puVar7 + 0x19c) = *(undefined4 *)((int)puVar7 + 0xac);
      *(undefined4 *)(puVar7 + 0x30) = uVar28;
      *(undefined4 *)((int)puVar7 + 0x184) = uVar23;
      *(undefined4 *)(puVar7 + 0x31) = uVar30;
      *(undefined4 *)((int)puVar7 + 0x18c) = uVar27;
      cVar18 = func_0x00bf6d18(uVar29,uVar11 - 0x210,uVar12);
      goto joined_r0x009cae68;
    }
    if ((uVar4 & 0xc00000) == 0) {
      piVar22 = (int *)param_2[0x35];
      if ((piVar22 != (int *)0x0) &&
         (((piVar22[1] & 0xe0000000U) == 0x40000000 || ((piVar22[1] & 0xe0000000U) == 0x20000000))))
      {
        pcVar2 = (code *)**(undefined4 **)(*piVar22 + 0x14);
        puVar7[5] = uVar12;
        iVar15 = (*pcVar2)(piVar22);
        iVar17 = *(int *)(*(int *)(iVar16 + -0x7f18) + 4);
        if (*(int *)(iVar15 + 4) != iVar17) {
          iVar15 = *(int *)(iVar15 + 0x10);
          if (iVar15 == 0) goto LAB_009ca814;
          iVar3 = *(int *)(iVar15 + 4);
          while (iVar3 != iVar17) {
            iVar15 = *(int *)(iVar15 + 0x10);
            if (iVar15 == 0) goto LAB_009ca814;
            iVar3 = *(int *)(iVar15 + 4);
          }
        }
        fVar1 = *(float *)(iVar16 + -0x7e80);
        puVar8 = *(undefined4 **)(iVar16 + -0x7ee4);
        puVar9 = *(undefined4 **)(iVar16 + -0x7e78);
        puVar10 = (undefined4 *)((uint)(piVar22 + 0xc) & 0xfffffff0);
        uVar23 = puVar10[1];
        uVar30 = puVar10[2];
        uVar27 = puVar10[3];
        uVar28 = *(undefined4 *)(*(int *)(iVar16 + -0x7ee8) + 0x28);
        *(undefined4 *)(puVar7 + 0x38) = *puVar10;
        *(undefined4 *)((int)puVar7 + 0x1c4) = uVar23;
        *(undefined4 *)(puVar7 + 0x39) = uVar30;
        *(undefined4 *)((int)puVar7 + 0x1cc) = uVar27;
        uVar30 = *puVar9;
        uVar23 = *puVar8;
        *(undefined4 *)((int)puVar7 + 0x2dc) = 0xf;
        *(undefined1 (*) [16])(puVar7 + 0x3a) = auVar39;
        *(undefined4 *)((int)puVar7 + 0x2d4) = uVar28;
        *(undefined4 *)(puVar7 + 0x59) = 10;
        *(undefined4 *)((int)puVar7 + 0x2e4) = uVar23;
        *(undefined4 *)(puVar7 + 0x53) = 2;
        *(undefined4 *)(puVar7 + 0x5b) = 0;
        *(undefined4 *)(puVar7 + 0x5a) = uVar28;
        *(float *)((int)puVar7 + 0x1c4) = *(float *)((int)puVar7 + 0x1c4) + fVar1;
        *(undefined4 *)(puVar7 + 0x5d) = 3;
        *(undefined4 *)((int)puVar7 + 0x29c) = uVar30;
        *(undefined4 *)(puVar7 + 0x56) = 0;
        *(undefined4 *)(puVar7 + 0x57) = 0;
        *(undefined4 *)((int)puVar7 + 0x2b4) = 0;
        *(undefined4 *)((int)puVar7 + 700) = 0;
        *(undefined4 *)((int)puVar7 + 0x2c4) = 0;
        *(undefined1 *)((int)puVar7 + 0x2cc) = 1;
        *(undefined1 *)((int)puVar7 + 0x2cd) = 1;
        *(undefined1 *)(puVar7 + 0x5c) = 0;
        *(undefined1 *)((int)puVar7 + 0x2ce) = 0;
        *(undefined1 *)((int)puVar7 + 0x2e1) = 0;
        *(undefined1 *)((int)puVar7 + 0x2ec) = 0;
        *(undefined1 *)(puVar7 + 0x58) = 1;
        puVar7[0x54] = 0xffffffffffffffff;
        puVar8 = *(undefined4 **)(iVar16 + -0x7ff8);
        *(undefined1 *)(puVar7 + 0x55) = 1;
        *(undefined4 *)((int)puVar7 + 0x2ac) = 0;
        cVar18 = func_0x00bf6d18(*puVar8,uVar11 - 0x1d0,uVar11 - 0xf8);
        goto joined_r0x009cae68;
      }
    }
    else {
      piVar22 = (int *)param_2[0x35];
      if ((piVar22 != (int *)0x0) &&
         (((piVar22[1] & 0xe0000000U) == 0x40000000 || ((piVar22[1] & 0xe0000000U) == 0x20000000))))
      {
        pcVar2 = (code *)**(undefined4 **)(*piVar22 + 0x14);
        puVar7[5] = uVar12;
        iVar15 = (*pcVar2)(piVar22);
        iVar17 = *(int *)(*(int *)(iVar16 + -0x7f48) + 4);
        if (*(int *)(iVar15 + 4) != iVar17) {
          iVar15 = *(int *)(iVar15 + 0x10);
          if (iVar15 == 0) goto LAB_009ca814;
          iVar3 = *(int *)(iVar15 + 4);
          while (iVar3 != iVar17) {
            iVar15 = *(int *)(iVar15 + 0x10);
            if (iVar15 == 0) goto LAB_009ca814;
            iVar3 = *(int *)(iVar15 + 4);
          }
        }
        pcVar2 = (code *)**(undefined4 **)(*piVar22 + 0x44);
        puVar7[5] = puVar7[5];
        (*pcVar2)(uVar11 - 800,piVar22,0xffffffffffffffff);
        fVar1 = *(float *)(iVar16 + -0x7e80);
        puVar8 = *(undefined4 **)(iVar16 + -0x7ee4);
        puVar9 = *(undefined4 **)(iVar16 + -0x7e78);
        uVar28 = *(undefined4 *)(*(int *)(iVar16 + -0x7ee8) + 0x28);
        *(undefined4 *)((int)puVar7 + 0x21c) = uVar28;
        *(undefined4 *)(puVar7 + 0x2c) = *(undefined4 *)(puVar7 + 0xe);
        *(undefined4 *)((int)puVar7 + 0x164) = *(undefined4 *)((int)puVar7 + 0x74);
        *(undefined4 *)(puVar7 + 0x2d) = *(undefined4 *)(puVar7 + 0xf);
        *(undefined4 *)((int)puVar7 + 0x16c) = *(undefined4 *)((int)puVar7 + 0x7c);
        uVar23 = *puVar9;
        *(undefined4 *)((int)puVar7 + 0x22c) = *puVar8;
        *(undefined1 (*) [16])(puVar7 + 0x2e) = auVar39;
        *(undefined4 *)((int)puVar7 + 0x224) = 0xf;
        *(undefined4 *)(puVar7 + 0x42) = 10;
        *(undefined4 *)(puVar7 + 0x43) = uVar28;
        *(undefined4 *)(puVar7 + 0x44) = 0;
        *(float *)((int)puVar7 + 0x164) = *(float *)((int)puVar7 + 0x164) + fVar1;
        *(undefined4 *)(puVar7 + 0x46) = 3;
        *(undefined4 *)(puVar7 + 0x3c) = 2;
        *(undefined4 *)((int)puVar7 + 0x1e4) = uVar23;
        *(undefined4 *)(puVar7 + 0x3f) = 0;
        *(undefined4 *)(puVar7 + 0x40) = 0;
        *(undefined4 *)((int)puVar7 + 0x1fc) = 0;
        *(undefined4 *)((int)puVar7 + 0x204) = 0;
        *(undefined4 *)((int)puVar7 + 0x20c) = 0;
        *(undefined1 *)((int)puVar7 + 0x214) = 1;
        *(undefined1 *)((int)puVar7 + 0x215) = 1;
        *(undefined1 *)(puVar7 + 0x45) = 0;
        *(undefined1 *)((int)puVar7 + 0x216) = 0;
        *(undefined1 *)((int)puVar7 + 0x229) = 0;
        *(undefined1 *)((int)puVar7 + 0x234) = 0;
        *(undefined1 *)(puVar7 + 0x41) = 1;
        puVar7[0x3d] = 0xffffffffffffffff;
        puVar8 = *(undefined4 **)(iVar16 + -0x7ff8);
        *(undefined1 *)(puVar7 + 0x3e) = 1;
        *(undefined4 *)((int)puVar7 + 500) = 0;
        cVar18 = func_0x00bf6d18(*puVar8,uVar11 - 0x230,uVar11 - 0x1b0);
        goto joined_r0x009cae68;
      }
    }
  }
  else {
    iVar17 = func_0x00beac80(param_2,0);
    if (iVar17 != 0) {
      iVar15 = *(int *)(iVar17 + 4);
      if (iVar15 == 6) {
        puVar8 = (undefined4 *)(iVar17 + 0x10U & 0xfffffff0);
        uVar28 = puVar8[1];
        uVar23 = puVar8[2];
        uVar30 = puVar8[3];
        *(undefined4 *)(puVar7 + 0x24) = *puVar8;
        *(undefined4 *)((int)puVar7 + 0x124) = uVar28;
        *(undefined4 *)(puVar7 + 0x25) = uVar23;
        *(undefined4 *)((int)puVar7 + 300) = uVar30;
      }
      else if (iVar15 < 7) {
        if (iVar15 == 5) {
          *(undefined4 *)(puVar7 + 0x24) = *(undefined4 *)(iVar17 + 0x10);
          *(undefined4 *)((int)puVar7 + 0x124) = *(undefined4 *)(iVar17 + 0x14);
          *(undefined4 *)(puVar7 + 0x25) = *(undefined4 *)(iVar17 + 0x18);
        }
      }
      else {
        if (iVar15 == 7) {
                    /* WARNING: Bad instruction - Truncating control flow here */
          halt_baddata();
        }
        if (iVar15 == 8) {
          puVar8 = (undefined4 *)(iVar17 + 0x40U & 0xfffffff0);
          uVar28 = puVar8[1];
          uVar23 = puVar8[2];
          uVar30 = puVar8[3];
          *(undefined4 *)(puVar7 + 0x24) = *puVar8;
          *(undefined4 *)((int)puVar7 + 0x124) = uVar28;
          *(undefined4 *)(puVar7 + 0x25) = uVar23;
          *(undefined4 *)((int)puVar7 + 300) = uVar30;
        }
      }
    }
    lVar19 = uVar11 - 0x1f0;
    lVar20 = uVar11 - 0x150;
    uVar28 = *(undefined4 *)(*(int *)(iVar16 + -0x7ee8) + 0x28);
    uVar23 = **(undefined4 **)(iVar16 + -0x7ee4);
    uVar30 = **(undefined4 **)(iVar16 + -0x7ed8);
    uVar27 = **(undefined4 **)(iVar16 + -0x7ff8);
    *(undefined4 *)(puVar7 + 0x34) = *(undefined4 *)(puVar7 + 0x24);
    *(undefined4 *)((int)puVar7 + 0x1a4) = *(undefined4 *)((int)puVar7 + 0x124);
    *(undefined4 *)(puVar7 + 0x35) = *(undefined4 *)(puVar7 + 0x25);
    *(undefined4 *)((int)puVar7 + 0x1ac) = *(undefined4 *)((int)puVar7 + 300);
    *(undefined1 (*) [16])(puVar7 + 0x36) = auVar39;
    *(undefined4 *)(puVar7 + 0x4e) = 10;
    *(undefined4 *)((int)puVar7 + 0x27c) = uVar28;
    *(undefined4 *)((int)puVar7 + 0x284) = 0xf;
    *(undefined4 *)(puVar7 + 0x50) = 0;
    *(undefined4 *)((int)puVar7 + 0x28c) = uVar23;
    *(undefined4 *)(puVar7 + 0x4f) = uVar28;
    *(undefined4 *)(puVar7 + 0x52) = 3;
    *(undefined4 *)(puVar7 + 0x48) = 2;
    *(undefined4 *)((int)puVar7 + 0x244) = uVar30;
    puVar7[0x49] = 0xffffffffffffffff;
    *(undefined1 *)(puVar7 + 0x4a) = 1;
    *(undefined4 *)((int)puVar7 + 0x254) = 0;
    *(undefined4 *)(puVar7 + 0x4b) = 0;
    *(undefined4 *)(puVar7 + 0x4c) = 0;
    *(undefined4 *)((int)puVar7 + 0x25c) = 0;
    *(undefined4 *)((int)puVar7 + 0x264) = 0;
    *(undefined4 *)((int)puVar7 + 0x26c) = 0;
    *(undefined1 *)((int)puVar7 + 0x274) = 1;
    *(undefined1 *)((int)puVar7 + 0x275) = 1;
    *(undefined1 *)(puVar7 + 0x51) = 0;
    *(undefined1 *)((int)puVar7 + 0x276) = 0;
    *(undefined1 *)((int)puVar7 + 0x289) = 0;
    *(undefined1 *)((int)puVar7 + 0x294) = 0;
    *(undefined1 *)(puVar7 + 0x4d) = 1;
LAB_009caad8:
    cVar18 = func_0x00bf6d18(uVar27,lVar19,lVar20);
joined_r0x009cae68:
    if (cVar18 != '\0') {
      return;
    }
  }
LAB_009ca814:
  *(undefined1 (*) [16])(iVar14 + 0x10U & 0xfffffff0) = auVar39;
  iVar16 = param_3[0x24];
  *(float *)(iVar14 + 0x28) = (float)dVar24;
  *(int *)(iVar14 + 0x20) = iVar16;
  *(int **)(iVar14 + 0x24) = param_3;
LAB_009ca680:
  if (((int)uVar21 != -1) && (*(int *)(param_3[0x39] + 0xc) != 0)) {
    *(int *)(*(int *)(param_3[0x39] + 0xc) + (int)((uVar21 & 0xffffffff) << 2) + 200) = iVar13;
  }
  return;
}


