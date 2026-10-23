
/* WARNING: Control flow encountered bad instruction data */

void FUN_000d9dd0(int param_1,int param_2,undefined4 param_3,undefined4 param_4,undefined4 param_5,
                 undefined4 param_6,uint param_7,byte param_8)

{
  longlong lVar1;
  byte bVar2;
  float fVar3;
  float fVar4;
  float fVar5;
  float fVar6;
  int *piVar7;
  int *piVar8;
  int iVar9;
  int iVar10;
  ulonglong uVar11;
  ulonglong *puVar12;
  undefined4 *puVar13;
  undefined4 *puVar14;
  bool bVar15;
  bool bVar16;
  int in_r0;
  undefined8 uVar17;
  ulonglong uVar18;
  ulonglong uVar19;
  char cVar25;
  int iVar20;
  int iVar21;
  uint uVar22;
  int iVar23;
  int iVar24;
  uint uVar26;
  undefined4 in_r12;
  ulonglong unaff_r14;
  uint *puVar27;
  ulonglong unaff_r15;
  ulonglong unaff_r16;
  ulonglong unaff_r17;
  ulonglong unaff_r18;
  uint uVar28;
  ulonglong unaff_r19;
  ulonglong unaff_r20;
  ulonglong unaff_r21;
  ulonglong unaff_r22;
  ulonglong unaff_r23;
  ulonglong unaff_r24;
  ulonglong unaff_r25;
  int *piVar29;
  ulonglong unaff_r26;
  ulonglong unaff_r27;
  ulonglong unaff_r28;
  ulonglong unaff_r29;
  uint *puVar30;
  ulonglong unaff_r30;
  ulonglong unaff_r31;
  byte bVar31;
  ulonglong in_LR;
  code *pcVar32;
  double dVar33;
  double extraout_f1;
  double extraout_f1_00;
  double dVar34;
  double extraout_f1_01;
  double extraout_f1_02;
  ulonglong in_f28;
  double dVar35;
  ulonglong in_f29;
  double dVar36;
  ulonglong in_f30;
  ulonglong in_f31;
  double dVar37;
  undefined4 uVar38;
  undefined4 uVar40;
  undefined4 uVar41;
  undefined4 uVar42;
  undefined4 uVar43;
  undefined1 auVar39 [16];
  undefined4 uVar44;
  undefined4 uVar45;
  undefined1 auVar46 [16];
  undefined1 auVar47 [16];
  undefined1 auVar48 [16];
  undefined1 auVar49 [16];
  undefined4 uVar51;
  undefined4 uVar52;
  undefined1 auVar50 [16];
  undefined4 uVar53;
  undefined4 uVar54;
  undefined4 uVar55;
  undefined4 uVar56;
  undefined1 auVar57 [16];
  undefined1 auVar58 [16];
  undefined1 auVar59 [16];
  undefined1 auVar60 [16];
  undefined1 auVar61 [16];
  undefined4 in_vr31_32_0;
  undefined4 in_vr31_32_1;
  undefined4 in_vr31_32_2;
  undefined4 in_vr31_32_3;
  int aiStack_710 [44];
  undefined4 auStack_660 [16];
  undefined4 auStack_620 [16];
  undefined4 auStack_5e0 [32];
  undefined4 auStack_560 [4];
  undefined1 auStack_550 [400];
  undefined1 auStack_3c0 [16];
  undefined1 auStack_3b0 [16];
  undefined1 auStack_3a0 [16];
  undefined1 auStack_390 [208];
  undefined4 auStack_2c0 [4];
  undefined4 auStack_2b0 [4];
  undefined1 auStack_2a0 [16];
  undefined1 auStack_290 [656];
  
  uVar18 = ZEXT48(&stack0x00000000);
  uVar19 = 0x171c590;
  lVar1 = uVar18 - 0x7c0;
  puVar12 = (ulonglong *)lVar1;
  *puVar12 = uVar18;
  puVar13 = (undefined4 *)((int)puVar12 + in_r0 & 0xfffffff0);
  *puVar13 = in_vr31_32_0;
  puVar13[1] = in_vr31_32_1;
  puVar13[2] = in_vr31_32_2;
  puVar13[3] = in_vr31_32_3;
  puVar12[0xf2] = unaff_r30;
  iVar9 = iRam017147e4;
  puVar12[0xf3] = unaff_r31;
  puVar12[0xf4] = in_f28;
  puVar12[0xe3] = unaff_r15;
  puVar12[0xe4] = unaff_r16;
  puVar13 = *(undefined4 **)(iVar9 + -0x7fc0);
  puVar12[0xe5] = unaff_r17;
  puVar12[0xe7] = unaff_r19;
  puVar12[0xe9] = unaff_r21;
  puVar12[0xea] = unaff_r22;
  puVar12[0xf5] = in_f29;
  puVar12[0xf6] = in_f30;
  puVar12[0xf7] = in_f31;
  puVar12[0xe2] = unaff_r14;
  puVar12[0xe6] = unaff_r18;
  puVar12[0xe8] = unaff_r20;
  puVar12[0xeb] = unaff_r23;
  puVar12[0xec] = unaff_r24;
  puVar12[0xed] = unaff_r25;
  puVar12[0xee] = unaff_r26;
  puVar12[0xef] = unaff_r27;
  puVar12[0xf0] = unaff_r28;
  puVar12[0xf1] = unaff_r29;
  *(undefined4 *)(puVar12 + 0xda) = param_3;
  piVar7 = *(int **)((int)puVar12 + 0x834);
  *(undefined4 *)(puVar12 + 0xf9) = in_r12;
  puVar12[0xfa] = in_LR;
  uVar38 = *(undefined4 *)(param_1 + 0x4060);
  uVar40 = *puVar13;
  *(undefined4 *)((int)puVar12 + 0x6d4) = param_4;
  *(undefined4 *)(puVar12 + 0xdb) = param_5;
  *(undefined4 *)((int)puVar12 + 0x6dc) = param_6;
  func_0x00b8824c(param_2,uVar40,uVar38);
  *(int *)((int)puVar12 + 0x6cc) = 1 << (*(uint *)(param_2 + 0x34) & 0x3f);
  uVar22 = *(uint *)(param_1 + 0x2034);
  if (uVar22 == 0) {
    puVar27 = *(uint **)(iVar9 + -0x7fb8);
  }
  else {
    puVar27 = *(uint **)(iVar9 + -0x7fb8);
    piVar29 = (int *)(param_1 + 0x1030);
    uVar28 = 0;
    do {
      while (((((piVar8 = (int *)*piVar29, piVar8 != (int *)0x0 &&
                ((*(ushort *)((int)piVar8 + 0x1a) & param_7) != 0)) &&
               ((piVar8[1] & 0xe0120000U) == 0x40120000)) &&
              ((uVar26 = (uint)piVar8[1] >> 0x16 & 0x7f, uVar26 == 0x3f ||
               ((*(uint *)(uVar26 * 0x20 + **(int **)(iVar9 + -0x7fbc) + 0x2c) & 0x20000000) != 0)))
              ) && (((uint)*(byte *)((int)piVar8 + 7) & *(uint *)((int)puVar12 + 0x6cc)) != 0))) {
        if (*(int *)(puVar12 + 0xda) == 1) {
          uVar38 = *(undefined4 *)(puVar12 + 0xdb);
          pcVar32 = (code *)**(undefined4 **)(*piVar8 + 0x3c);
LAB_000db688:
          puVar12[5] = uVar19;
          cVar25 = (*pcVar32)(piVar8,uVar38);
          uVar19 = puVar12[5];
          if (cVar25 != '\0') goto LAB_000d9fa8;
          uVar22 = *(uint *)(param_1 + 0x2034);
        }
        else {
          if (*(int *)(puVar12 + 0xda) == 2) {
            uVar38 = *(undefined4 *)((int)puVar12 + 0x6dc);
            pcVar32 = (code *)**(undefined4 **)(*piVar8 + 0x40);
            goto LAB_000db688;
          }
LAB_000d9fa8:
          uVar38 = *(undefined4 *)((int)puVar12 + 0x6d4);
          pcVar32 = (code *)**(undefined4 **)(*piVar8 + 0x38);
          puVar12[5] = uVar19;
          dVar33 = (double)(*pcVar32)(piVar8,uVar38);
          uVar19 = puVar12[5];
          uVar22 = *puVar27;
          *(float *)(puVar12 + 0xe) = (float)dVar33;
          if (*(char *)(uVar22 + 0x2c) == '\0') {
LAB_000db22c:
            if ((*(ushort *)((int)piVar8 + 0x1a) & 1) != 0) {
              fVar3 = *(float *)(puVar12 + 0x44);
              if (*(float *)(puVar12 + 0x44) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)(puVar12 + 0x44) = fVar3;
            }
            if ((*(ushort *)((int)piVar8 + 0x1a) & 2) != 0) {
              fVar3 = *(float *)((int)puVar12 + 0x224);
              if (*(float *)((int)puVar12 + 0x224) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)((int)puVar12 + 0x224) = fVar3;
            }
            if ((*(ushort *)((int)piVar8 + 0x1a) & 4) != 0) {
              fVar3 = *(float *)(puVar12 + 0x45);
              if (*(float *)(puVar12 + 0x45) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)(puVar12 + 0x45) = fVar3;
            }
            if ((*(ushort *)((int)piVar8 + 0x1a) & 8) != 0) {
              fVar3 = *(float *)((int)puVar12 + 0x22c);
              if (*(float *)((int)puVar12 + 0x22c) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)((int)puVar12 + 0x22c) = fVar3;
            }
            if ((*(ushort *)((int)piVar8 + 0x1a) & 0x10) != 0) {
              fVar3 = *(float *)(puVar12 + 0x46);
              if (*(float *)(puVar12 + 0x46) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)(puVar12 + 0x46) = fVar3;
            }
            if ((*(ushort *)((int)piVar8 + 0x1a) & 0x20) != 0) {
              fVar3 = *(float *)((int)puVar12 + 0x234);
              if (*(float *)((int)puVar12 + 0x234) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)((int)puVar12 + 0x234) = fVar3;
            }
            if ((*(ushort *)((int)piVar8 + 0x1a) & 0x40) != 0) {
              fVar3 = *(float *)(puVar12 + 0x47);
              if (*(float *)(puVar12 + 0x47) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)(puVar12 + 0x47) = fVar3;
            }
            if ((*(ushort *)((int)piVar8 + 0x1a) & 0x80) != 0) {
              fVar3 = *(float *)((int)puVar12 + 0x23c);
              if (*(float *)((int)puVar12 + 0x23c) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)((int)puVar12 + 0x23c) = fVar3;
            }
            if ((*(ushort *)((int)piVar8 + 0x1a) & 0x100) != 0) {
              fVar3 = *(float *)(puVar12 + 0x48);
              if (*(float *)(puVar12 + 0x48) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)(puVar12 + 0x48) = fVar3;
            }
            if ((*(ushort *)((int)piVar8 + 0x1a) & 0x200) != 0) {
              fVar3 = *(float *)((int)puVar12 + 0x244);
              if (*(float *)((int)puVar12 + 0x244) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)((int)puVar12 + 0x244) = fVar3;
            }
            if ((*(ushort *)((int)piVar8 + 0x1a) & 0x400) != 0) {
              fVar3 = *(float *)(puVar12 + 0x49);
              if (*(float *)(puVar12 + 0x49) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)(puVar12 + 0x49) = fVar3;
            }
            if ((*(ushort *)((int)piVar8 + 0x1a) & 0x800) != 0) {
              fVar3 = *(float *)((int)puVar12 + 0x24c);
              if (*(float *)((int)puVar12 + 0x24c) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)((int)puVar12 + 0x24c) = fVar3;
            }
            if ((*(ushort *)((int)piVar8 + 0x1a) & 0x1000) != 0) {
              fVar3 = *(float *)(puVar12 + 0x4a);
              if (*(float *)(puVar12 + 0x4a) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)(puVar12 + 0x4a) = fVar3;
            }
            if ((*(ushort *)((int)piVar8 + 0x1a) & 0x2000) != 0) {
              fVar3 = *(float *)((int)puVar12 + 0x254);
              if (*(float *)((int)puVar12 + 0x254) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)((int)puVar12 + 0x254) = fVar3;
            }
            if ((*(ushort *)((int)piVar8 + 0x1a) & 0x4000) != 0) {
              fVar3 = *(float *)(puVar12 + 0x4b);
              if (*(float *)(puVar12 + 0x4b) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              *(float *)(puVar12 + 0x4b) = fVar3;
            }
            if (*(short *)((int)piVar8 + 0x1a) < 0) {
              fVar3 = *(float *)((int)puVar12 + 0x25c);
              if (*(float *)((int)puVar12 + 0x25c) < *(float *)(puVar12 + 0xe)) {
                fVar3 = *(float *)(puVar12 + 0xe);
              }
              uVar22 = *(uint *)(param_1 + 0x2034);
              *(float *)((int)puVar12 + 0x25c) = fVar3;
              break;
            }
          }
          else {
            if (piVar7 == (int *)0x0) {
              cVar25 = func_0x001628e0(uVar22,uVar18 - 0x750,uVar38,piVar8);
            }
            else {
              cVar25 = func_0x00162cc0(uVar22,uVar18 - 0x750,piVar7,piVar8);
            }
            if (cVar25 != '\0') goto LAB_000db22c;
          }
          uVar22 = *(uint *)(param_1 + 0x2034);
        }
        uVar28 = uVar28 + 1;
        piVar29 = piVar29 + 1;
        if (uVar22 <= uVar28) goto LAB_000da020;
      }
      uVar28 = uVar28 + 1;
      piVar29 = piVar29 + 1;
    } while (uVar28 < uVar22);
  }
LAB_000da020:
  bVar16 = piVar7 == (int *)0x0;
  puVar30 = (uint *)(param_1 + 0x30);
  bVar15 = (param_8 & 2) == 0;
  bVar31 = bVar15 << 1;
  dataCacheBlockTouch(ZEXT48(puVar30));
  if (!bVar15) {
    func_0x00fe6bcc(uVar18 - 0x4e0,0,0x90);
    uVar19 = puVar12[5];
  }
  uVar22 = *(uint *)(iVar9 + -0x7fac);
  uVar28 = 0;
  iVar23 = *(int *)(param_1 + 0x2030);
  puVar13 = (undefined4 *)(uVar22 + 0x30 & 0xfffffff0);
  uVar43 = *puVar13;
  uVar45 = puVar13[1];
  uVar51 = puVar13[2];
  uVar52 = puVar13[3];
  iVar20 = **(int **)(iVar9 + -0x7fb4);
  puVar13 = (undefined4 *)(uVar22 & 0xfffffff0);
  uVar40 = *puVar13;
  uVar42 = puVar13[1];
  uVar44 = puVar13[2];
  uVar41 = puVar13[3];
  auVar39 = *(undefined1 (*) [16])(*(uint *)(iVar9 + -0x7fb0) & 0xfffffff0);
  uVar38 = *(undefined4 *)(param_1 + 0x4060);
  auVar57 = *(undefined1 (*) [16])(uVar22 + 0x10 & 0xfffffff0);
  puVar13 = (undefined4 *)(uVar22 + 0x20 & 0xfffffff0);
  uVar53 = *puVar13;
  uVar54 = puVar13[1];
  uVar55 = puVar13[2];
  uVar56 = puVar13[3];
  *(undefined4 *)(puVar12 + 0xd8) = *(undefined4 *)(iVar20 + 0x6d28);
  *(undefined4 *)((int)puVar12 + 0x6c4) = *(undefined4 *)(iVar20 + 0x6d24);
  *(undefined1 (*) [16])(puVar12 + 0x32) = auVar39;
  *(undefined1 (*) [16])(puVar12 + 0x2c) = auVar39;
  *(undefined4 *)(puVar12 + 0x80) = uVar40;
  *(undefined4 *)((int)puVar12 + 0x404) = uVar42;
  *(undefined4 *)(puVar12 + 0x81) = uVar44;
  *(undefined4 *)((int)puVar12 + 0x40c) = uVar41;
  *(undefined1 (*) [16])(puVar12 + 0x82) = auVar57;
  *(undefined4 *)(puVar12 + 0x84) = uVar53;
  *(undefined4 *)((int)puVar12 + 0x424) = uVar54;
  *(undefined4 *)(puVar12 + 0x85) = uVar55;
  *(undefined4 *)((int)puVar12 + 0x42c) = uVar56;
  *(undefined4 *)(puVar12 + 0x86) = uVar43;
  *(undefined4 *)((int)puVar12 + 0x434) = uVar45;
  *(undefined4 *)(puVar12 + 0x87) = uVar51;
  *(undefined4 *)((int)puVar12 + 0x43c) = uVar52;
  *(undefined1 (*) [16])(puVar12 + 0x2e) = auVar39;
  *(undefined4 *)(puVar12 + 0x88) = uVar40;
  *(undefined4 *)((int)puVar12 + 0x444) = uVar42;
  *(undefined4 *)(puVar12 + 0x89) = uVar44;
  *(undefined4 *)((int)puVar12 + 0x44c) = uVar41;
  *(undefined1 (*) [16])(puVar12 + 0x8a) = auVar57;
  *(undefined4 *)(puVar12 + 0x8c) = uVar53;
  *(undefined4 *)((int)puVar12 + 0x464) = uVar54;
  *(undefined4 *)(puVar12 + 0x8d) = uVar55;
  *(undefined4 *)((int)puVar12 + 0x46c) = uVar56;
  *(undefined4 *)(puVar12 + 0x8e) = uVar43;
  *(undefined4 *)((int)puVar12 + 0x474) = uVar45;
  *(undefined4 *)(puVar12 + 0x8f) = uVar51;
  *(undefined4 *)((int)puVar12 + 0x47c) = uVar52;
  *(undefined1 (*) [16])(puVar12 + 0x30) = auVar39;
  *(undefined4 *)(puVar12 + 0x90) = uVar40;
  *(undefined4 *)((int)puVar12 + 0x484) = uVar42;
  *(undefined4 *)(puVar12 + 0x91) = uVar44;
  *(undefined4 *)((int)puVar12 + 0x48c) = uVar41;
  *(undefined1 (*) [16])(puVar12 + 0x92) = auVar57;
  *(undefined4 *)(puVar12 + 0x94) = uVar53;
  *(undefined4 *)((int)puVar12 + 0x4a4) = uVar54;
  *(undefined4 *)(puVar12 + 0x95) = uVar55;
  *(undefined4 *)((int)puVar12 + 0x4ac) = uVar56;
  *(undefined4 *)(puVar12 + 0x96) = uVar43;
  *(undefined4 *)((int)puVar12 + 0x4b4) = uVar45;
  *(undefined4 *)(puVar12 + 0x97) = uVar51;
  *(undefined4 *)((int)puVar12 + 0x4bc) = uVar52;
  *(undefined4 *)((int)puVar12 + 0xbc) = uVar38;
  *(undefined4 *)(puVar12 + 0x16) = uVar38;
  *(undefined4 *)((int)puVar12 + 0xb4) = uVar38;
  *(undefined4 *)(puVar12 + 0x17) = uVar38;
  *(undefined4 *)(puVar12 + 0x98) = uVar40;
  *(undefined4 *)((int)puVar12 + 0x4c4) = uVar42;
  *(undefined4 *)(puVar12 + 0x99) = uVar44;
  *(undefined4 *)((int)puVar12 + 0x4cc) = uVar41;
  *(undefined1 (*) [16])(puVar12 + 0x9a) = auVar57;
  *(undefined4 *)(puVar12 + 0x9c) = uVar53;
  *(undefined4 *)((int)puVar12 + 0x4e4) = uVar54;
  *(undefined4 *)(puVar12 + 0x9d) = uVar55;
  *(undefined4 *)((int)puVar12 + 0x4ec) = uVar56;
  *(undefined4 *)(puVar12 + 0x9e) = uVar43;
  *(undefined4 *)((int)puVar12 + 0x4f4) = uVar45;
  *(undefined4 *)(puVar12 + 0x9f) = uVar51;
  *(undefined4 *)((int)puVar12 + 0x4fc) = uVar52;
  *(undefined4 *)(puVar12 + 0xd9) = 0;
  if (iVar23 != 0) {
    iVar20 = 0;
    do {
      piVar29 = (int *)*puVar30;
      uVar11 = ZEXT48(piVar29);
      dataCacheBlockTouch(uVar11);
      if ((((piVar29 != (int *)0x0) && ((param_7 & piVar29[7]) != 0)) &&
          ((bVar2 = *(byte *)(piVar29 + 6), (param_8 & bVar2) != 0 &&
           ((piVar29[1] & 0xe0120000U) == 0x40120000)))) &&
         (((uVar22 = (uint)piVar29[1] >> 0x16 & 0x7f, uVar22 == 0x3f ||
           ((*(uint *)(uVar22 * 0x20 + **(int **)(iVar9 + -0x7fbc) + 0x2c) & 0x20000000) != 0)) &&
          (((uint)*(byte *)((int)piVar29 + 7) & *(uint *)((int)puVar12 + 0x6cc)) != 0)))) {
        *(undefined1 *)((int)puVar12 + 0x6bf) = *(undefined1 *)((int)piVar29 + 0x19);
        if ((bVar2 & 0x40) != 0) {
          if (*(int *)(puVar12 + 0xda) == 1) {
            uVar38 = *(undefined4 *)(puVar12 + 0xdb);
            puVar13 = *(undefined4 **)(*piVar29 + 0x3c);
          }
          else {
            if (*(int *)(puVar12 + 0xda) != 2) goto LAB_000da8fc;
            uVar38 = *(undefined4 *)((int)puVar12 + 0x6dc);
            puVar13 = *(undefined4 **)(*piVar29 + 0x40);
          }
          pcVar32 = (code *)*puVar13;
          puVar12[5] = uVar19;
          cVar25 = (*pcVar32)(uVar11,uVar38);
          uVar19 = puVar12[5];
          if (cVar25 == '\0') goto LAB_000da198;
        }
LAB_000da8fc:
        uVar22 = piVar29[7];
        if (((uVar22 & 1) == 0) ||
           (dVar33 = (double)*(float *)(puVar12 + 0x44),
           dVar33 <= (double)*(float *)(iVar9 + -0x7f4c))) {
          dVar33 = (double)*(float *)(iVar9 + -0x7f4c);
        }
        if (((uVar22 & 2) != 0) && (dVar33 < (double)*(float *)((int)puVar12 + 0x224))) {
          dVar33 = (double)*(float *)((int)puVar12 + 0x224);
        }
        if (((uVar22 & 4) != 0) && (dVar33 < (double)*(float *)(puVar12 + 0x45))) {
          dVar33 = (double)*(float *)(puVar12 + 0x45);
        }
        if (((uVar22 & 8) != 0) && (dVar33 < (double)*(float *)((int)puVar12 + 0x22c))) {
          dVar33 = (double)*(float *)((int)puVar12 + 0x22c);
        }
        if (((uVar22 & 0x10) != 0) && (dVar33 < (double)*(float *)(puVar12 + 0x46))) {
          dVar33 = (double)*(float *)(puVar12 + 0x46);
        }
        if (((uVar22 & 0x20) != 0) && (dVar33 < (double)*(float *)((int)puVar12 + 0x234))) {
          dVar33 = (double)*(float *)((int)puVar12 + 0x234);
        }
        if (((uVar22 & 0x40) != 0) && (dVar33 < (double)*(float *)(puVar12 + 0x47))) {
          dVar33 = (double)*(float *)(puVar12 + 0x47);
        }
        if (((uVar22 & 0x80) != 0) && (dVar33 < (double)*(float *)((int)puVar12 + 0x23c))) {
          dVar33 = (double)*(float *)((int)puVar12 + 0x23c);
        }
        if (((uVar22 & 0x100) != 0) && (dVar33 < (double)*(float *)(puVar12 + 0x48))) {
          dVar33 = (double)*(float *)(puVar12 + 0x48);
        }
        if (((uVar22 & 0x200) != 0) && (dVar33 < (double)*(float *)((int)puVar12 + 0x244))) {
          dVar33 = (double)*(float *)((int)puVar12 + 0x244);
        }
        if (((uVar22 & 0x400) != 0) && (dVar33 < (double)*(float *)(puVar12 + 0x49))) {
          dVar33 = (double)*(float *)(puVar12 + 0x49);
        }
        if (((uVar22 & 0x800) != 0) && (dVar33 < (double)*(float *)((int)puVar12 + 0x24c))) {
          dVar33 = (double)*(float *)((int)puVar12 + 0x24c);
        }
        if (((uVar22 & 0x1000) != 0) && (dVar33 < (double)*(float *)(puVar12 + 0x4a))) {
          dVar33 = (double)*(float *)(puVar12 + 0x4a);
        }
        if (((uVar22 & 0x2000) != 0) && (dVar33 < (double)*(float *)((int)puVar12 + 0x254))) {
          dVar33 = (double)*(float *)((int)puVar12 + 0x254);
        }
        if (((uVar22 & 0x4000) != 0) && (dVar33 < (double)*(float *)(puVar12 + 0x4b))) {
          dVar33 = (double)*(float *)(puVar12 + 0x4b);
        }
        if (((uVar22 & 0x8000) != 0) && (dVar33 < (double)*(float *)((int)puVar12 + 0x25c))) {
          dVar33 = (double)*(float *)((int)puVar12 + 0x25c);
        }
        dVar35 = (double)*(float *)(iVar9 + -0x7fa8);
        dVar33 = (double)(float)(dVar35 - dVar33);
        if ((bVar2 & 2) != 0) {
          uVar22 = *puVar27;
          *(float *)(puVar12 + 0xe) = *(float *)(iVar9 + -0x7fa8);
          if (*(char *)(uVar22 + 0x2c) == '\0') {
            uVar38 = *(undefined4 *)((int)puVar12 + 0x6d4);
          }
          else {
            if (bVar16) {
              uVar38 = *(undefined4 *)((int)puVar12 + 0x6d4);
              cVar25 = func_0x001634f8(uVar22,uVar18 - 0x750,uVar38,uVar11);
            }
            else {
              uVar38 = *(undefined4 *)((int)puVar12 + 0x6d4);
              cVar25 = func_0x001686f8(uVar22,uVar18 - 0x750,piVar7,uVar11,
                                       *(undefined4 *)(param_2 + 0x34));
            }
            if (cVar25 == '\0') goto LAB_000da198;
          }
          pcVar32 = (code *)**(undefined4 **)(*piVar29 + 0x14);
          puVar12[5] = uVar19;
          iVar21 = (*pcVar32)(uVar11);
          iVar24 = *(int *)(*(int *)(iVar9 + -0x7fa0) + 4);
          if (*(int *)(iVar21 + 4) == iVar24) {
LAB_000db768:
            uVar40 = *(undefined4 *)(param_2 + 0x34);
            pcVar32 = (code *)**(undefined4 **)(*piVar29 + 0x44);
            puVar12[5] = puVar12[5];
            cVar25 = (*pcVar32)(uVar11,uVar38,uVar18 - 0x450,uVar40);
            uVar19 = puVar12[5];
            if (cVar25 == '\0') goto LAB_000dace0;
            uVar17 = 0x6a0;
            *(float *)(puVar12 + 0xd4) = (float)(dVar33 * (double)*(float *)(puVar12 + 0xe));
          }
          else {
            iVar21 = *(int *)(iVar21 + 0x10);
            if (iVar21 != 0) {
              iVar10 = *(int *)(iVar21 + 4);
              while (iVar10 != iVar24) {
                iVar21 = *(int *)(iVar21 + 0x10);
                if (iVar21 == 0) goto LAB_000dab90;
                iVar10 = *(int *)(iVar21 + 4);
              }
              goto LAB_000db768;
            }
LAB_000dab90:
            pcVar32 = (code *)**(undefined4 **)(*piVar29 + 0x38);
            puVar12[5] = puVar12[5];
            cVar25 = (*pcVar32)(uVar11,uVar38,uVar18 - 0x450);
            uVar19 = puVar12[5];
            if (cVar25 == '\0') goto LAB_000dace0;
            uVar17 = 0x690;
            *(float *)(puVar12 + 0xd2) = (float)(dVar33 * (double)*(float *)(puVar12 + 0xe));
          }
          auVar39 = loadVectorElementWordIndexed(lVar1,uVar17);
          auVar39 = auVar39 >> 0x60;
          auVar39 = auVar39 & (undefined1  [16])0xffffffff | auVar39 << 0x20 | auVar39 << 0x40 |
                    auVar39 << 0x60;
          auVar46 = vectorMultiplyAddFloatingPoint
                              (*(undefined1 (*) [16])(puVar12 + 0x6e),auVar39,(undefined1  [16])0x0)
          ;
          auVar60 = vectorMultiplyAddFloatingPoint
                              (*(undefined1 (*) [16])(puVar12 + 0x72),auVar39,(undefined1  [16])0x0)
          ;
          auVar61 = vectorMultiplyAddFloatingPoint
                              (*(undefined1 (*) [16])(puVar12 + 0x70),auVar39,(undefined1  [16])0x0)
          ;
          auVar57 = vectorMultiplyAddFloatingPoint
                              (*(undefined1 (*) [16])(puVar12 + 0x76),auVar39,(undefined1  [16])0x0)
          ;
          auVar59 = vectorMultiplyAddFloatingPoint
                              (*(undefined1 (*) [16])(puVar12 + 0x74),auVar39,(undefined1  [16])0x0)
          ;
          auVar48 = vectorMultiplyAddFloatingPoint
                              (*(undefined1 (*) [16])(puVar12 + 0x7a),auVar39,(undefined1  [16])0x0)
          ;
          auVar58 = vectorAddFloatingPoint(*(undefined1 (*) [16])(puVar12 + 0x60),auVar60);
          auVar49 = vectorMultiplyAddFloatingPoint
                              (*(undefined1 (*) [16])(puVar12 + 0x78),auVar39,(undefined1  [16])0x0)
          ;
          auVar60 = vectorMultiplyAddFloatingPoint
                              (*(undefined1 (*) [16])(puVar12 + 0x7e),auVar39,(undefined1  [16])0x0)
          ;
          auVar50 = vectorAddFloatingPoint(*(undefined1 (*) [16])(puVar12 + 100),auVar57);
          auVar47 = vectorMultiplyAddFloatingPoint
                              (*(undefined1 (*) [16])(puVar12 + 0x7c),auVar39,(undefined1  [16])0x0)
          ;
          auVar59 = vectorAddFloatingPoint(*(undefined1 (*) [16])(puVar12 + 0x62),auVar59);
          auVar57 = vectorAddFloatingPoint(*(undefined1 (*) [16])(puVar12 + 0x5e),auVar61);
          auVar48 = vectorAddFloatingPoint(*(undefined1 (*) [16])(puVar12 + 0x68),auVar48);
          auVar39 = vectorAddFloatingPoint(*(undefined1 (*) [16])(puVar12 + 0x5c),auVar46);
          auVar49 = vectorAddFloatingPoint(*(undefined1 (*) [16])(puVar12 + 0x66),auVar49);
          auVar46 = vectorAddFloatingPoint(*(undefined1 (*) [16])(puVar12 + 0x6c),auVar60);
          auVar60 = vectorAddFloatingPoint(*(undefined1 (*) [16])(puVar12 + 0x6a),auVar47);
          *(undefined1 (*) [16])(puVar12 + 0x5c) = auVar39;
          *(undefined1 (*) [16])(puVar12 + 0x5e) = auVar57;
          *(undefined1 (*) [16])(puVar12 + 0x60) = auVar58;
          *(undefined1 (*) [16])(puVar12 + 0x62) = auVar59;
          *(undefined1 (*) [16])(puVar12 + 100) = auVar50;
          *(undefined1 (*) [16])(puVar12 + 0x66) = auVar49;
          *(undefined1 (*) [16])(puVar12 + 0x68) = auVar48;
          *(undefined1 (*) [16])(puVar12 + 0x6a) = auVar60;
          *(undefined1 (*) [16])(puVar12 + 0x6c) = auVar46;
        }
LAB_000dace0:
        uVar22 = *puVar27;
        *(undefined1 (*) [16])(puVar12 + 0x18) =
             *(undefined1 (*) [16])((uint)(piVar29 + 0xc) & 0xfffffff0);
        if (*(char *)(uVar22 + 0x2c) != '\0') {
          if (bVar16) {
            uVar22 = func_0x0016ac8c(uVar22,uVar18 - 0x700,*(undefined4 *)((int)puVar12 + 0x6d4),
                                     uVar11);
          }
          else {
            uVar22 = func_0x0016ad24(uVar22,uVar18 - 0x700,piVar7,uVar11,
                                     *(undefined4 *)(param_2 + 0x34));
          }
          uVar22 = uVar22 & 0xff;
          if (uVar22 == 0) goto LAB_000da198;
        }
        if ((bVar2 & 4) != 0) {
          *(undefined4 *)((int)puVar12 + 0x60c) = 0;
          *(float *)(puVar12 + 0xc0) = -*(float *)(puVar12 + 0x18);
          *(float *)((int)puVar12 + 0x604) = -*(float *)((int)puVar12 + 0xc4);
          *(float *)(puVar12 + 0xc1) = -*(float *)(puVar12 + 0x19);
          *(undefined1 (*) [16])(puVar12 + 0x18) = *(undefined1 (*) [16])(puVar12 + 0xc0);
        }
        iVar24 = piVar29[8];
        iVar21 = piVar29[9];
        *(int *)(puVar12 + 0xc1) = iVar24;
        *(int *)((int)puVar12 + 0x60c) = iVar21;
        *(int *)(puVar12 + 0xc0) = iVar24;
        *(int *)((int)puVar12 + 0x604) = iVar21;
        uVar38 = *(undefined4 *)(puVar12 + 0xc0);
        uVar40 = *(undefined4 *)((int)puVar12 + 0x604);
        uVar42 = *(undefined4 *)(puVar12 + 0xc1);
        uVar44 = *(undefined4 *)((int)puVar12 + 0x60c);
        if ((((bVar2 & 0x10) != 0) &&
            (uVar26 = *(uint *)(puVar12 + 0xd9), uVar26 < *(uint *)(puVar12 + 0xd8))) &&
           (*(char *)((int)puVar12 + 0x6bf) == '\x02')) {
          *(float *)(puVar12 + 0xd0) = (float)dVar33;
          iVar24 = piVar29[0x18];
          auVar39 = loadVectorElementWordIndexed(lVar1,0x680);
          auVar39 = auVar39 >> 0x60;
          *(uint *)((int)puVar12 + 0x6e4) = uVar26 * 0x20 + 0x10;
          auVar39 = vectorMultiplyAddFloatingPoint
                              (*(undefined1 (*) [16])(puVar12 + 0x18),
                               auVar39 & (undefined1  [16])0xffffffff | auVar39 << 0x20 |
                               auVar39 << 0x40 | auVar39 << 0x60,(undefined1  [16])0x0);
          *(undefined1 (*) [16])(puVar12 + 0x12) = auVar39;
          *(int *)((int)puVar12 + 0x9c) = iVar24;
          uVar41 = *(undefined4 *)((int)puVar12 + 0x94);
          uVar43 = *(undefined4 *)(puVar12 + 0x13);
          uVar45 = *(undefined4 *)((int)puVar12 + 0x9c);
          auStack_560[uVar26 * 8] = *(undefined4 *)(puVar12 + 0x12);
          auStack_560[uVar26 * 8 + 1] = uVar41;
          auStack_560[uVar26 * 8 + 2] = uVar43;
          auStack_560[uVar26 * 8 + 3] = uVar45;
          fVar3 = (float)piVar29[0x19];
          fVar4 = (float)piVar29[0x18];
          puVar13 = (undefined4 *)((uint)(piVar29 + 0x14) & 0xfffffff0);
          uVar41 = puVar13[1];
          uVar43 = puVar13[2];
          uVar45 = puVar13[3];
          *(undefined4 *)(puVar12 + 0x10) = *puVar13;
          *(undefined4 *)((int)puVar12 + 0x84) = uVar41;
          *(undefined4 *)(puVar12 + 0x11) = uVar43;
          *(undefined4 *)((int)puVar12 + 0x8c) = uVar45;
          *(float *)((int)puVar12 + 0x8c) = (float)(dVar35 / (double)(fVar3 - fVar4));
          *(undefined1 (*) [16])(auStack_550 + uVar26 * 0x20) =
               *(undefined1 (*) [16])(puVar12 + 0x10);
          auStack_620[uVar26 * 4] = uVar38;
          auStack_620[uVar26 * 4 + 1] = uVar40;
          auStack_620[uVar26 * 4 + 2] = uVar42;
          auStack_620[uVar26 * 4 + 3] = uVar44;
          if (!bVar16) {
            pcVar32 = (code *)**(undefined4 **)(*piVar7 + 0x14);
            puVar12[5] = uVar19;
            iVar21 = (*pcVar32)(piVar7);
            uVar19 = puVar12[5];
            iVar24 = *(int *)(*(int *)(iVar9 + -0x7f9c) + 4);
            if (*(int *)(iVar21 + 4) != iVar24) {
              iVar21 = *(int *)(iVar21 + 0x10);
              uVar22 = 0;
              if (iVar21 == 0) goto LAB_000daed8;
              iVar10 = *(int *)(iVar21 + 4);
              while (iVar10 != iVar24) {
                iVar21 = *(int *)(iVar21 + 0x10);
                uVar22 = 0;
                if (iVar21 == 0) goto LAB_000daed8;
                iVar10 = *(int *)(iVar21 + 4);
              }
            }
            pcVar32 = (code *)**(undefined4 **)(*piVar29 + 0x14);
            puVar12[5] = uVar19;
            iVar21 = (*pcVar32)(uVar11);
            uVar19 = puVar12[5];
            iVar24 = *(int *)(*(int *)(iVar9 + -0x7f98) + 4);
            if (*(int *)(iVar21 + 4) != iVar24) {
              iVar21 = *(int *)(iVar21 + 0x10);
              uVar22 = 0;
              if (iVar21 == 0) goto LAB_000daed8;
              iVar10 = *(int *)(iVar21 + 4);
              while (iVar10 != iVar24) {
                iVar21 = *(int *)(iVar21 + 0x10);
                if (iVar21 == 0) {
                  uVar22 = 0;
                  goto LAB_000daed8;
                }
                iVar10 = *(int *)(iVar21 + 4);
              }
            }
            pcVar32 = (code *)**(undefined4 **)(*piVar7 + 0x48);
            puVar12[5] = uVar19;
            uVar22 = (*pcVar32)(piVar7,4);
            uVar19 = puVar12[5];
            auVar46 = *(undefined1 (*) [16])((uint)(piVar29 + 0x10) & 0xfffffff0);
            auVar39 = auVar46 >> 0x60;
            auVar57 = auVar46 >> 0x20;
            auVar46 = auVar46 >> 0x40;
            auVar39 = vectorMultiplyAddFloatingPoint
                                (*(undefined1 (*) [16])(uVar22 & 0xfffffff0),
                                 auVar39 & (undefined1  [16])0xffffffff | auVar39 << 0x20 |
                                 auVar39 << 0x40 | auVar39 << 0x60,(undefined1  [16])0x0);
            auVar46 = vectorMultiplyAddFloatingPoint
                                (*(undefined1 (*) [16])(uVar22 + 0x10 & 0xfffffff0),
                                 auVar46 & (undefined1  [16])0xffffffff | auVar46 << 0x20 |
                                 (auVar46 & (undefined1  [16])0xffffffff) << 0x40 | auVar46 << 0x60,
                                 *(undefined1 (*) [16])(uVar22 + 0x30 & 0xfffffff0));
            auVar39 = vectorMultiplyAddFloatingPoint
                                (*(undefined1 (*) [16])(uVar22 + 0x20 & 0xfffffff0),
                                 auVar57 & (undefined1  [16])0xffffffff | auVar57 << 0x20 |
                                 (auVar57 & (undefined1  [16])0xffffffff) << 0x40 | auVar57 << 0x60,
                                 auVar39);
            auVar57 = vectorAddFloatingPoint(auVar39,auVar46);
            uVar41 = storeVectorElementWordIndexed(auVar57,lVar1,0x66c);
            *(undefined4 *)((int)puVar12 + 0x66c) = uVar41;
            *(float *)(puVar12 + 0xce) = (float)(dVar35 / (double)*(float *)((int)puVar12 + 0x66c));
            fVar3 = (float)piVar29[0x19];
            fVar4 = (float)piVar29[0x18];
            auVar39 = loadVectorElementWordIndexed(lVar1,0x670);
            auVar39 = auVar39 >> 0x60;
            auVar39 = vectorMultiplyAddFloatingPoint
                                (auVar57,auVar39 & (undefined1  [16])0xffffffff | auVar39 << 0x20 |
                                         auVar39 << 0x40 | auVar39 << 0x60,(undefined1  [16])0x0);
            *(undefined1 (*) [16])(puVar12 + 0x1a) = auVar39;
            *(float *)((int)puVar12 + 0xdc) = (float)(dVar35 / (double)(fVar3 - fVar4));
            *(undefined1 (*) [16])((int)auStack_560 + *(int *)((int)puVar12 + 0x6e4) & 0xfffffff0) =
                 *(undefined1 (*) [16])(puVar12 + 0x1a);
          }
LAB_000daed8:
          *(int *)(puVar12 + 0xd9) = *(int *)(puVar12 + 0xd9) + 1;
        }
        if (((bVar2 & 8) != 0) && (uVar28 < *(uint *)((int)puVar12 + 0x6c4))) {
          bVar2 = *(byte *)((int)puVar12 + 0x6bf);
          if (bVar2 == 2) {
            *(float *)(puVar12 + 0xca) = (float)dVar33;
            iVar24 = piVar29[0x18];
            auVar39 = loadVectorElementWordIndexed(lVar1,0x650);
            auVar39 = auVar39 >> 0x60;
            auVar39 = vectorMultiplyAddFloatingPoint
                                (*(undefined1 (*) [16])(puVar12 + 0x18),
                                 auVar39 & (undefined1  [16])0xffffffff | auVar39 << 0x20 |
                                 auVar39 << 0x40 | auVar39 << 0x60,(undefined1  [16])0x0);
            auVar60 = *(undefined1 (*) [16])(*(uint *)(iVar9 + -0x7f94) & 0xfffffff0);
            *(undefined1 (*) [16])(puVar12 + 0x1c) = auVar39;
            *(int *)((int)puVar12 + 0xec) = iVar24;
            uVar41 = *(undefined4 *)((int)puVar12 + 0xe4);
            uVar43 = *(undefined4 *)(puVar12 + 0x1d);
            uVar45 = *(undefined4 *)((int)puVar12 + 0xec);
            auStack_2c0[uVar28 * 0x10] = *(undefined4 *)(puVar12 + 0x1c);
            auStack_2c0[uVar28 * 0x10 + 1] = uVar41;
            auStack_2c0[uVar28 * 0x10 + 2] = uVar43;
            auStack_2c0[uVar28 * 0x10 + 3] = uVar45;
            fVar3 = (float)piVar29[0x19];
            fVar4 = (float)piVar29[0x18];
            puVar13 = (undefined4 *)((uint)(piVar29 + 0x14) & 0xfffffff0);
            uVar41 = puVar13[1];
            uVar43 = puVar13[2];
            uVar45 = puVar13[3];
            uVar22 = *(uint *)(iVar9 + -0x7f8c);
            *(undefined4 *)(puVar12 + 0x1e) = *puVar13;
            *(undefined4 *)((int)puVar12 + 0xf4) = uVar41;
            *(undefined4 *)(puVar12 + 0x1f) = uVar43;
            *(undefined4 *)((int)puVar12 + 0xfc) = uVar45;
            auVar46 = *(undefined1 (*) [16])(uVar22 & 0xfffffff0);
            auVar57 = *(undefined1 (*) [16])(*(uint *)(iVar9 + -0x7f90) & 0xfffffff0);
            *(float *)((int)puVar12 + 0xfc) = (float)(dVar35 / (double)(fVar3 - fVar4));
            uVar41 = *(undefined4 *)((int)puVar12 + 0xf4);
            uVar43 = *(undefined4 *)(puVar12 + 0x1f);
            uVar45 = *(undefined4 *)((int)puVar12 + 0xfc);
            auStack_2b0[uVar28 * 0x10] = *(undefined4 *)(puVar12 + 0x1e);
            auStack_2b0[uVar28 * 0x10 + 1] = uVar41;
            auStack_2b0[uVar28 * 0x10 + 2] = uVar43;
            auStack_2b0[uVar28 * 0x10 + 3] = uVar45;
            *(undefined1 (*) [16])(auStack_2a0 + uVar28 * 0x40) = auVar60;
            *(int *)(puVar12 + 0xc0) = piVar29[0xf];
            auVar39 = loadVectorElementWordIndexed(lVar1,0x600);
            auVar39 = vectorPermute(auVar57,auVar39,auVar46);
            *(undefined1 (*) [16])(auStack_290 + uVar28 * 0x40) = auVar39;
            if (!bVar16) {
              pcVar32 = (code *)**(undefined4 **)(*piVar7 + 0x14);
              puVar12[5] = uVar19;
              iVar21 = (*pcVar32)(piVar7);
              uVar19 = puVar12[5];
              iVar24 = *(int *)(*(int *)(iVar9 + -0x7f9c) + 4);
              if (*(int *)(iVar21 + 4) != iVar24) {
                iVar21 = *(int *)(iVar21 + 0x10);
                if (iVar21 == 0) goto LAB_000dbb6c;
                iVar10 = *(int *)(iVar21 + 4);
                while (iVar10 != iVar24) {
                  iVar21 = *(int *)(iVar21 + 0x10);
                  if (iVar21 == 0) goto LAB_000dbb6c;
                  iVar10 = *(int *)(iVar21 + 4);
                }
              }
              pcVar32 = (code *)**(undefined4 **)(*piVar29 + 0x14);
              puVar12[5] = uVar19;
              iVar21 = (*pcVar32)(uVar11);
              uVar19 = puVar12[5];
              iVar24 = *(int *)(*(int *)(iVar9 + -0x7f98) + 4);
              if (*(int *)(iVar21 + 4) != iVar24) {
                iVar21 = *(int *)(iVar21 + 0x10);
                if (iVar21 == 0) goto LAB_000dbb6c;
                iVar10 = *(int *)(iVar21 + 4);
                while (iVar10 != iVar24) {
                  iVar21 = *(int *)(iVar21 + 0x10);
                  if (iVar21 == 0) goto LAB_000dbb6c;
                  iVar10 = *(int *)(iVar21 + 4);
                }
              }
              pcVar32 = (code *)**(undefined4 **)(*piVar7 + 0x48);
              puVar12[5] = uVar19;
              uVar22 = (*pcVar32)(piVar7,4);
              uVar19 = puVar12[5];
              auVar46 = *(undefined1 (*) [16])((uint)(piVar29 + 0x10) & 0xfffffff0);
              auVar39 = auVar46 >> 0x60;
              auVar57 = auVar46 >> 0x20;
              auVar46 = auVar46 >> 0x40;
              auVar39 = vectorMultiplyAddFloatingPoint
                                  (*(undefined1 (*) [16])(uVar22 & 0xfffffff0),
                                   auVar39 & (undefined1  [16])0xffffffff | auVar39 << 0x20 |
                                   auVar39 << 0x40 | auVar39 << 0x60,(undefined1  [16])0x0);
              auVar46 = vectorMultiplyAddFloatingPoint
                                  (*(undefined1 (*) [16])(uVar22 + 0x10 & 0xfffffff0),
                                   auVar46 & (undefined1  [16])0xffffffff | auVar46 << 0x20 |
                                   (auVar46 & (undefined1  [16])0xffffffff) << 0x40 |
                                   auVar46 << 0x60,
                                   *(undefined1 (*) [16])(uVar22 + 0x30 & 0xfffffff0));
              auVar39 = vectorMultiplyAddFloatingPoint
                                  (*(undefined1 (*) [16])(uVar22 + 0x20 & 0xfffffff0),
                                   auVar57 & (undefined1  [16])0xffffffff | auVar57 << 0x20 |
                                   (auVar57 & (undefined1  [16])0xffffffff) << 0x40 |
                                   auVar57 << 0x60,auVar39);
              auVar57 = vectorAddFloatingPoint(auVar39,auVar46);
              uVar41 = storeVectorElementWordIndexed(auVar57,lVar1,0x63c);
              *(undefined4 *)((int)puVar12 + 0x63c) = uVar41;
              *(float *)(puVar12 + 200) = (float)(dVar35 / (double)*(float *)((int)puVar12 + 0x63c))
              ;
              fVar3 = (float)piVar29[0x18];
              fVar4 = (float)piVar29[0x19];
              auVar39 = loadVectorElementWordIndexed(lVar1,0x640);
              auVar39 = auVar39 >> 0x60;
              auVar39 = vectorMultiplyAddFloatingPoint
                                  (auVar57,auVar39 & (undefined1  [16])0xffffffff | auVar39 << 0x20
                                           | auVar39 << 0x40 | auVar39 << 0x60,(undefined1  [16])0x0
                                  );
              *(undefined1 (*) [16])(puVar12 + 0x2a) = auVar39;
              *(float *)((int)puVar12 + 0x15c) = (float)(dVar35 / (double)(fVar4 - fVar3));
              *(undefined1 (*) [16])(auStack_2b0 + uVar28 * 0x10) =
                   *(undefined1 (*) [16])(puVar12 + 0x2a);
            }
LAB_000dbb6c:
            auStack_5e0[uVar28 * 4] = uVar38;
            auStack_5e0[uVar28 * 4 + 1] = uVar40;
            auStack_5e0[uVar28 * 4 + 2] = uVar42;
            auStack_5e0[uVar28 * 4 + 3] = uVar44;
            uVar28 = uVar28 + 1;
          }
          else if (bVar2 < 3) {
            if (bVar2 == 1) {
              *(float *)(puVar12 + 0xc2) = (float)dVar33;
              loadVectorElementWordIndexed(lVar1,0x610);
                    /* WARNING: Bad instruction - Truncating control flow here */
              halt_baddata();
            }
          }
          else if (bVar2 < 5) {
            fVar3 = (float)piVar29[0x26];
            fVar4 = (float)piVar29[0x27];
            *(float *)(puVar12 + 0xc4) = (float)dVar33;
            fVar5 = *(float *)(iVar9 + -0x7fe4);
            auVar39 = loadVectorElementWordIndexed(lVar1,0x620);
            *(uint *)(puVar12 + 0xdc) = uVar28 * 0x40;
            auVar39 = auVar39 >> 0x60;
            iVar24 = piVar29[0x24];
            fVar6 = *(float *)(iVar9 + -0x7f88);
            auVar39 = vectorMultiplyAddFloatingPoint
                                (*(undefined1 (*) [16])(puVar12 + 0x18),
                                 auVar39 & (undefined1  [16])0xffffffff | auVar39 << 0x20 |
                                 auVar39 << 0x40 | auVar39 << 0x60,(undefined1  [16])0x0);
            dVar36 = (double)(fVar3 * fVar5 * fVar6);
            *(undefined1 (*) [16])(puVar12 + 0x28) = auVar39;
            dVar37 = (double)((fVar3 - fVar4) * fVar5 * fVar6);
            *(int *)((int)puVar12 + 0x14c) = iVar24;
            uVar41 = *(undefined4 *)((int)puVar12 + 0x144);
            uVar43 = *(undefined4 *)(puVar12 + 0x29);
            uVar45 = *(undefined4 *)((int)puVar12 + 0x14c);
            auStack_2c0[uVar28 * 0x10] = *(undefined4 *)(puVar12 + 0x28);
            auStack_2c0[uVar28 * 0x10 + 1] = uVar41;
            auStack_2c0[uVar28 * 0x10 + 2] = uVar43;
            auStack_2c0[uVar28 * 0x10 + 3] = uVar45;
            fVar3 = (float)piVar29[0x24];
            fVar4 = (float)piVar29[0x25];
            puVar13 = (undefined4 *)((uint)(piVar29 + 0x1c) & 0xfffffff0);
            uVar41 = puVar13[1];
            uVar43 = puVar13[2];
            uVar45 = puVar13[3];
            *(undefined4 *)(puVar12 + 0x26) = *puVar13;
            *(undefined4 *)((int)puVar12 + 0x134) = uVar41;
            *(undefined4 *)(puVar12 + 0x27) = uVar43;
            *(undefined4 *)((int)puVar12 + 0x13c) = uVar45;
            iVar24 = *(int *)(puVar12 + 0xdc);
            *(float *)((int)puVar12 + 0x13c) = (float)(dVar35 / (double)(fVar4 - fVar3));
            uVar41 = *(undefined4 *)((int)puVar12 + 0x134);
            uVar43 = *(undefined4 *)(puVar12 + 0x27);
            uVar45 = *(undefined4 *)((int)puVar12 + 0x13c);
            auStack_2b0[uVar28 * 0x10] = *(undefined4 *)(puVar12 + 0x26);
            auStack_2b0[uVar28 * 0x10 + 1] = uVar41;
            auStack_2b0[uVar28 * 0x10 + 2] = uVar43;
            auStack_2b0[uVar28 * 0x10 + 3] = uVar45;
            puVar13 = (undefined4 *)((uint)(piVar29 + 0x20) & 0xfffffff0);
            uVar41 = puVar13[1];
            uVar43 = puVar13[2];
            uVar45 = puVar13[3];
            *(undefined4 *)(puVar12 + 0x20) = *puVar13;
            *(undefined4 *)((int)puVar12 + 0x104) = uVar41;
            *(undefined4 *)(puVar12 + 0x21) = uVar43;
            *(undefined4 *)((int)puVar12 + 0x10c) = uVar45;
            *(float *)((int)puVar12 + 0x10c) = (float)dVar35;
            uVar41 = *(undefined4 *)((int)puVar12 + 0x104);
            uVar43 = *(undefined4 *)(puVar12 + 0x21);
            uVar45 = *(undefined4 *)((int)puVar12 + 0x10c);
            puVar13 = (undefined4 *)((uint)(auStack_2a0 + iVar24) & 0xfffffff0);
            *puVar13 = *(undefined4 *)(puVar12 + 0x20);
            puVar13[1] = uVar41;
            puVar13[2] = uVar43;
            puVar13[3] = uVar45;
            uVar17 = func_0x00b2ac94(dVar36,uVar22,1);
            dVar33 = extraout_f1;
            uVar17 = func_0x00b2ac94(dVar37,uVar17,1);
            dVar37 = extraout_f1_00;
            dVar34 = (double)func_0x00b2ac94(dVar36,uVar17,1);
            *(float *)(puVar12 + 0xc0) = (float)dVar33;
            *(float *)((int)puVar12 + 0x604) = (float)(dVar35 / (double)(float)(dVar37 - dVar34));
            iVar24 = piVar29[0xf];
            *(undefined4 *)((int)puVar12 + 0x60c) = 0;
            *(int *)(puVar12 + 0xc1) = iVar24;
            *(undefined1 (*) [16])((uint)(auStack_290 + *(int *)(puVar12 + 0xdc)) & 0xfffffff0) =
                 *(undefined1 (*) [16])(puVar12 + 0xc0);
            auStack_5e0[uVar28 * 4] = uVar38;
            auStack_5e0[uVar28 * 4 + 1] = uVar40;
            auStack_5e0[uVar28 * 4 + 2] = uVar42;
            auStack_5e0[uVar28 * 4 + 3] = uVar44;
            if (bVar16) {
LAB_000dba14:
              uVar28 = uVar28 + 1;
            }
            else {
              pcVar32 = (code *)**(undefined4 **)(*piVar29 + 0x14);
              puVar12[5] = uVar19;
              iVar21 = (*pcVar32)(uVar11);
              uVar19 = puVar12[5];
              iVar24 = *(int *)(*(int *)(iVar9 + -0x7f80) + 4);
              if (*(int *)(iVar21 + 4) != iVar24) {
                iVar21 = *(int *)(iVar21 + 0x10);
                if (iVar21 == 0) goto LAB_000dba14;
                iVar10 = *(int *)(iVar21 + 4);
                while (iVar10 != iVar24) {
                  iVar21 = *(int *)(iVar21 + 0x10);
                  if (iVar21 == 0) goto LAB_000dba14;
                  iVar10 = *(int *)(iVar21 + 4);
                }
              }
              uVar17 = func_0x00b2a4d4(dVar36);
              dVar37 = ABS((double)(float)(extraout_f1_01 * (double)(float)piVar29[0x25]));
              uVar17 = func_0x00b2ac94(dVar36,uVar17,1);
              dVar33 = extraout_f1_02;
              dVar35 = (double)func_0x00b2ac94(dVar36,uVar17,0);
              *(float *)((int)puVar12 + 0x604) = (float)dVar35;
              *(float *)(puVar12 + 0xc0) = (float)dVar33;
              *(int *)(puVar12 + 0xc1) = piVar29[0x25];
              *(float *)((int)puVar12 + 0x60c) = (float)dVar37;
              uVar38 = *(undefined4 *)((int)puVar12 + 0x604);
              uVar40 = *(undefined4 *)(puVar12 + 0xc1);
              uVar42 = *(undefined4 *)((int)puVar12 + 0x60c);
              auStack_660[uVar28 * 4] = *(undefined4 *)(puVar12 + 0xc0);
              auStack_660[uVar28 * 4 + 1] = uVar38;
              auStack_660[uVar28 * 4 + 2] = uVar40;
              auStack_660[uVar28 * 4 + 3] = uVar42;
              iVar24 = func_0x00268114(uVar11);
              aiStack_710[uVar28] = iVar24;
              if (iVar24 == 0) {
                aiStack_710[uVar28] = *(int *)(param_1 + 0x4060);
              }
              iVar24 = *(int *)(puVar12 + 0xdc);
              puVar13 = (undefined4 *)((uint)(piVar29 + 0x38) & 0xfffffff0);
              uVar38 = puVar13[1];
              uVar40 = puVar13[2];
              uVar42 = puVar13[3];
              puVar14 = (undefined4 *)((uint)(auStack_3c0 + iVar24) & 0xfffffff0);
              *puVar14 = *puVar13;
              puVar14[1] = uVar38;
              puVar14[2] = uVar40;
              puVar14[3] = uVar42;
              puVar13 = (undefined4 *)((uint)(piVar29 + 0x3c) & 0xfffffff0);
              uVar38 = puVar13[1];
              uVar40 = puVar13[2];
              uVar42 = puVar13[3];
              puVar14 = (undefined4 *)((uint)(auStack_3b0 + iVar24) & 0xfffffff0);
              *puVar14 = *puVar13;
              puVar14[1] = uVar38;
              puVar14[2] = uVar40;
              puVar14[3] = uVar42;
              puVar13 = (undefined4 *)((uint)(piVar29 + 0x40) & 0xfffffff0);
              uVar38 = puVar13[1];
              uVar40 = puVar13[2];
              uVar42 = puVar13[3];
              puVar14 = (undefined4 *)((uint)(auStack_3a0 + iVar24) & 0xfffffff0);
              *puVar14 = *puVar13;
              puVar14[1] = uVar38;
              puVar14[2] = uVar40;
              puVar14[3] = uVar42;
              *(undefined1 (*) [16])((uint)(auStack_390 + iVar24) & 0xfffffff0) =
                   *(undefined1 (*) [16])((uint)(piVar29 + 0x44) & 0xfffffff0);
              uVar28 = uVar28 + 1;
            }
          }
        }
      }
LAB_000da198:
      iVar20 = iVar20 + 1;
      puVar30 = puVar30 + 1;
    } while (iVar23 != iVar20);
  }
  if (*(char *)(*puVar27 + 0x2c) == '\0') {
    if (!bVar16) {
      pcVar32 = (code *)**(undefined4 **)(*piVar7 + 0x14);
      puVar12[5] = uVar19;
      iVar20 = (*pcVar32)(piVar7);
      iVar23 = *(int *)(*(int *)(iVar9 + -0x7f74) + 4);
      if (*(int *)(iVar20 + 4) != iVar23) {
        iVar20 = *(int *)(iVar20 + 0x10);
        if (iVar20 == 0) goto LAB_000da238;
        iVar24 = *(int *)(iVar20 + 4);
        while (iVar24 != iVar23) {
          iVar20 = *(int *)(iVar20 + 0x10);
          if (iVar20 == 0) goto LAB_000da238;
          iVar24 = *(int *)(iVar20 + 4);
        }
      }
      if (((*(char *)(piVar7 + 0x3b0) != '\0') && (*(char *)(piVar7 + 0x3c9) != '\0')) &&
         (iVar23 = func_0x00128d90(**(undefined4 **)(iVar9 + -0x7fdc)), iVar23 != 0)) {
        halt_baddata();
      }
    }
  }
  else if (!bVar16) {
    pcVar32 = (code *)**(undefined4 **)(*piVar7 + 0x14);
    puVar12[5] = uVar19;
    iVar20 = (*pcVar32)(piVar7);
    iVar23 = *(int *)(*(int *)(iVar9 + -0x7f74) + 4);
    if (*(int *)(iVar20 + 4) != iVar23) {
      iVar20 = *(int *)(iVar20 + 0x10);
      if (iVar20 == 0) goto LAB_000da238;
      iVar24 = *(int *)(iVar20 + 4);
      while (iVar24 != iVar23) {
        iVar20 = *(int *)(iVar20 + 0x10);
        if (iVar20 == 0) goto LAB_000da238;
        iVar24 = *(int *)(iVar20 + 4);
      }
    }
    if (*(char *)(piVar7 + 0x3b0) != '\0') {
                    /* WARNING: Bad instruction - Truncating control flow here */
      halt_baddata();
    }
  }
LAB_000da238:
  if ((param_8 & 8) != 0) {
    piVar7 = *(int **)(iVar9 + -0x7f70);
    if (uVar28 == 0) {
      *(undefined4 *)(*piVar7 * 4 + *(int *)(param_2 + 0xc)) = 0;
      *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
      iVar23 = piVar7[1];
LAB_000db190:
      *(undefined4 *)(iVar23 * 4 + *(int *)(param_2 + 0xc)) = 0;
      *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
      iVar23 = piVar7[2];
LAB_000db1b8:
      *(undefined4 *)(iVar23 * 4 + *(int *)(param_2 + 0xc)) = 0;
      *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
      iVar23 = piVar7[3];
LAB_000db1e0:
      *(undefined4 *)(iVar23 * 4 + *(int *)(param_2 + 0xc)) = 0;
      *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
      if (uVar28 == 0) goto LAB_000da630;
    }
    else {
      uVar38 = *(undefined4 *)(iVar9 + -0x7fa8);
      *(undefined4 *)(*piVar7 * 4 + *(int *)(param_2 + 0xc)) = uVar38;
      *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
      iVar23 = piVar7[1];
      if (uVar28 < 2) goto LAB_000db190;
      *(undefined4 *)(iVar23 * 4 + *(int *)(param_2 + 0xc)) = uVar38;
      *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
      iVar23 = piVar7[2];
      if (uVar28 < 3) goto LAB_000db1b8;
      *(undefined4 *)(iVar23 * 4 + *(int *)(param_2 + 0xc)) = uVar38;
      *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
      iVar23 = piVar7[3];
      if (uVar28 < 4) goto LAB_000db1e0;
      *(undefined4 *)(iVar23 * 4 + *(int *)(param_2 + 0xc)) = uVar38;
      *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
    }
    iVar23 = *(int *)(param_2 + 0x28);
    piVar29 = (int *)(iVar23 + -8);
    uVar22 = (uint)(piVar29 + (uVar28 & 0x3ffffff) * -0x10) & 0xfffffff0;
    iVar20 = **(int **)(iVar9 + -0x7f6c);
    *(uint *)(param_2 + 0x28) = uVar22;
    func_0x00fe6c3c(uVar22,uVar18 - 0x2c0,uVar28 * 0x40);
    piVar7 = *(int **)(iVar9 + -0x7f68);
    *(uint *)(iVar23 + -4) = uVar22;
    *piVar29 = uVar28 << 3;
    *(int **)(iVar20 * 4 + *(int *)(param_2 + 0xc)) = piVar29;
    iVar23 = *(int *)(param_2 + 0x28);
    piVar29 = (int *)(iVar23 + -8);
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
    uVar22 = (uint)(piVar29 + (uVar28 & 0xfffffff) * -4) & 0xfffffff0;
    iVar20 = *piVar7;
    *(uint *)(param_2 + 0x28) = uVar22;
    func_0x00fe6c3c(uVar22,uVar18 - 0x5e0,uVar28 * 0x10);
    piVar7 = *(int **)(iVar9 + -0x7f64);
    *(uint *)(iVar23 + -4) = uVar22;
    *piVar29 = uVar28 << 1;
    *(int **)(iVar20 * 4 + *(int *)(param_2 + 0xc)) = piVar29;
    iVar23 = *(int *)(param_2 + 0x28);
    piVar29 = (int *)(iVar23 + -8);
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
    uVar22 = (uint)(piVar29 + (uVar28 & 0xfffffff) * -4) & 0xfffffff0;
    iVar20 = *piVar7;
    *(uint *)(param_2 + 0x28) = uVar22;
    func_0x00fe6c3c(uVar22,uVar18 - 0x660,uVar28 * 0x10);
    puVar13 = *(undefined4 **)(iVar9 + -0x7f60);
    *(uint *)(iVar23 + -4) = uVar22;
    *piVar29 = uVar28 << 1;
    *(int **)(iVar20 * 4 + *(int *)(param_2 + 0xc)) = piVar29;
    uVar38 = *(undefined4 *)(puVar12 + 0x16);
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
    func_0x00b8824c(param_2,*puVar13,uVar38);
    func_0x00b8824c(param_2,puVar13[1],*(undefined4 *)((int)puVar12 + 0xb4));
    func_0x00b8824c(param_2,puVar13[2],*(undefined4 *)(puVar12 + 0x17));
    func_0x00b8824c(param_2,puVar13[3],*(undefined4 *)((int)puVar12 + 0xbc));
    piVar7 = *(int **)(iVar9 + -0x7f5c);
    puVar13 = (undefined4 *)(*(int *)(param_2 + 0x28) - 0x40U & 0xfffffff0);
    iVar23 = *piVar7;
    uVar38 = *(undefined4 *)(puVar12 + 0x80);
    uVar40 = *(undefined4 *)((int)puVar12 + 0x404);
    uVar42 = *(undefined4 *)(puVar12 + 0x81);
    uVar44 = *(undefined4 *)((int)puVar12 + 0x40c);
    *(undefined4 **)(param_2 + 0x28) = puVar13;
    *puVar13 = uVar38;
    puVar13[1] = uVar40;
    puVar13[2] = uVar42;
    puVar13[3] = uVar44;
    uVar38 = *(undefined4 *)((int)puVar12 + 0x414);
    uVar40 = *(undefined4 *)(puVar12 + 0x83);
    uVar42 = *(undefined4 *)((int)puVar12 + 0x41c);
    puVar13[4] = *(undefined4 *)(puVar12 + 0x82);
    puVar13[5] = uVar38;
    puVar13[6] = uVar40;
    puVar13[7] = uVar42;
    uVar38 = *(undefined4 *)((int)puVar12 + 0x424);
    uVar40 = *(undefined4 *)(puVar12 + 0x85);
    uVar42 = *(undefined4 *)((int)puVar12 + 0x42c);
    puVar13[8] = *(undefined4 *)(puVar12 + 0x84);
    puVar13[9] = uVar38;
    puVar13[10] = uVar40;
    puVar13[0xb] = uVar42;
    uVar38 = *(undefined4 *)((int)puVar12 + 0x434);
    uVar40 = *(undefined4 *)(puVar12 + 0x87);
    uVar42 = *(undefined4 *)((int)puVar12 + 0x43c);
    puVar13[0xc] = *(undefined4 *)(puVar12 + 0x86);
    puVar13[0xd] = uVar38;
    puVar13[0xe] = uVar40;
    puVar13[0xf] = uVar42;
    *(undefined4 **)(iVar23 * 4 + *(int *)(param_2 + 0xc)) = puVar13;
    uVar38 = *(undefined4 *)(puVar12 + 0x88);
    uVar40 = *(undefined4 *)((int)puVar12 + 0x444);
    uVar42 = *(undefined4 *)(puVar12 + 0x89);
    uVar44 = *(undefined4 *)((int)puVar12 + 0x44c);
    puVar13 = (undefined4 *)(*(int *)(param_2 + 0x28) - 0x40U & 0xfffffff0);
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
    iVar23 = piVar7[1];
    *(undefined4 **)(param_2 + 0x28) = puVar13;
    *puVar13 = uVar38;
    puVar13[1] = uVar40;
    puVar13[2] = uVar42;
    puVar13[3] = uVar44;
    uVar38 = *(undefined4 *)((int)puVar12 + 0x454);
    uVar40 = *(undefined4 *)(puVar12 + 0x8b);
    uVar42 = *(undefined4 *)((int)puVar12 + 0x45c);
    puVar13[4] = *(undefined4 *)(puVar12 + 0x8a);
    puVar13[5] = uVar38;
    puVar13[6] = uVar40;
    puVar13[7] = uVar42;
    uVar38 = *(undefined4 *)((int)puVar12 + 0x464);
    uVar40 = *(undefined4 *)(puVar12 + 0x8d);
    uVar42 = *(undefined4 *)((int)puVar12 + 0x46c);
    puVar13[8] = *(undefined4 *)(puVar12 + 0x8c);
    puVar13[9] = uVar38;
    puVar13[10] = uVar40;
    puVar13[0xb] = uVar42;
    uVar38 = *(undefined4 *)((int)puVar12 + 0x474);
    uVar40 = *(undefined4 *)(puVar12 + 0x8f);
    uVar42 = *(undefined4 *)((int)puVar12 + 0x47c);
    puVar13[0xc] = *(undefined4 *)(puVar12 + 0x8e);
    puVar13[0xd] = uVar38;
    puVar13[0xe] = uVar40;
    puVar13[0xf] = uVar42;
    *(undefined4 **)(iVar23 * 4 + *(int *)(param_2 + 0xc)) = puVar13;
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
    iVar23 = piVar7[2];
    puVar13 = (undefined4 *)(*(int *)(param_2 + 0x28) - 0x40U & 0xfffffff0);
    *(undefined4 **)(param_2 + 0x28) = puVar13;
    uVar38 = *(undefined4 *)((int)puVar12 + 0x484);
    uVar40 = *(undefined4 *)(puVar12 + 0x91);
    uVar42 = *(undefined4 *)((int)puVar12 + 0x48c);
    *puVar13 = *(undefined4 *)(puVar12 + 0x90);
    puVar13[1] = uVar38;
    puVar13[2] = uVar40;
    puVar13[3] = uVar42;
    uVar38 = *(undefined4 *)((int)puVar12 + 0x494);
    uVar40 = *(undefined4 *)(puVar12 + 0x93);
    uVar42 = *(undefined4 *)((int)puVar12 + 0x49c);
    puVar13[4] = *(undefined4 *)(puVar12 + 0x92);
    puVar13[5] = uVar38;
    puVar13[6] = uVar40;
    puVar13[7] = uVar42;
    uVar38 = *(undefined4 *)((int)puVar12 + 0x4a4);
    uVar40 = *(undefined4 *)(puVar12 + 0x95);
    uVar42 = *(undefined4 *)((int)puVar12 + 0x4ac);
    puVar13[8] = *(undefined4 *)(puVar12 + 0x94);
    puVar13[9] = uVar38;
    puVar13[10] = uVar40;
    puVar13[0xb] = uVar42;
    uVar38 = *(undefined4 *)((int)puVar12 + 0x4b4);
    uVar40 = *(undefined4 *)(puVar12 + 0x97);
    uVar42 = *(undefined4 *)((int)puVar12 + 0x4bc);
    puVar13[0xc] = *(undefined4 *)(puVar12 + 0x96);
    puVar13[0xd] = uVar38;
    puVar13[0xe] = uVar40;
    puVar13[0xf] = uVar42;
    *(undefined4 **)(iVar23 * 4 + *(int *)(param_2 + 0xc)) = puVar13;
    uVar38 = *(undefined4 *)(puVar12 + 0x98);
    uVar40 = *(undefined4 *)((int)puVar12 + 0x4c4);
    uVar42 = *(undefined4 *)(puVar12 + 0x99);
    uVar44 = *(undefined4 *)((int)puVar12 + 0x4cc);
    puVar13 = (undefined4 *)(*(int *)(param_2 + 0x28) - 0x40U & 0xfffffff0);
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
    iVar23 = piVar7[3];
    *(undefined4 **)(param_2 + 0x28) = puVar13;
    *puVar13 = uVar38;
    puVar13[1] = uVar40;
    puVar13[2] = uVar42;
    puVar13[3] = uVar44;
    uVar38 = *(undefined4 *)((int)puVar12 + 0x4d4);
    uVar40 = *(undefined4 *)(puVar12 + 0x9b);
    uVar42 = *(undefined4 *)((int)puVar12 + 0x4dc);
    puVar13[4] = *(undefined4 *)(puVar12 + 0x9a);
    puVar13[5] = uVar38;
    puVar13[6] = uVar40;
    puVar13[7] = uVar42;
    uVar38 = *(undefined4 *)((int)puVar12 + 0x4e4);
    uVar40 = *(undefined4 *)(puVar12 + 0x9d);
    uVar42 = *(undefined4 *)((int)puVar12 + 0x4ec);
    puVar13[8] = *(undefined4 *)(puVar12 + 0x9c);
    puVar13[9] = uVar38;
    puVar13[10] = uVar40;
    puVar13[0xb] = uVar42;
    uVar38 = *(undefined4 *)((int)puVar12 + 0x4f4);
    uVar40 = *(undefined4 *)(puVar12 + 0x9f);
    uVar42 = *(undefined4 *)((int)puVar12 + 0x4fc);
    puVar13[0xc] = *(undefined4 *)(puVar12 + 0x9e);
    puVar13[0xd] = uVar38;
    puVar13[0xe] = uVar40;
    puVar13[0xf] = uVar42;
    *(undefined4 **)(iVar23 * 4 + *(int *)(param_2 + 0xc)) = puVar13;
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
  }
LAB_000da630:
  if ((param_8 & 0x10) == 0) goto LAB_000da7e0;
  piVar7 = *(int **)(iVar9 + -0x7f58);
  iVar23 = *(int *)(puVar12 + 0xd9);
  if (iVar23 == 0) {
    *(undefined4 *)(*piVar7 * 4 + *(int *)(param_2 + 0xc)) = 0;
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
    iVar20 = piVar7[1];
LAB_000db0ec:
    *(undefined4 *)(iVar20 * 4 + *(int *)(param_2 + 0xc)) = 0;
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
    iVar20 = piVar7[2];
LAB_000db114:
    *(undefined4 *)(iVar20 * 4 + *(int *)(param_2 + 0xc)) = 0;
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
    iVar20 = piVar7[3];
LAB_000db13c:
    *(undefined4 *)(iVar20 * 4 + *(int *)(param_2 + 0xc)) = 0;
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
    if (iVar23 == 0) goto LAB_000da7e0;
  }
  else {
    uVar38 = *(undefined4 *)(iVar9 + -0x7fa8);
    uVar22 = *(uint *)(puVar12 + 0xd9);
    *(undefined4 *)(*piVar7 * 4 + *(int *)(param_2 + 0xc)) = uVar38;
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
    iVar20 = piVar7[1];
    if (uVar22 < 2) goto LAB_000db0ec;
    uVar22 = *(uint *)(puVar12 + 0xd9);
    *(undefined4 *)(iVar20 * 4 + *(int *)(param_2 + 0xc)) = uVar38;
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
    iVar20 = piVar7[2];
    if (uVar22 < 3) goto LAB_000db114;
    uVar22 = *(uint *)(puVar12 + 0xd9);
    *(undefined4 *)(iVar20 * 4 + *(int *)(param_2 + 0xc)) = uVar38;
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
    iVar20 = piVar7[3];
    if (uVar22 < 4) goto LAB_000db13c;
    *(undefined4 *)(iVar20 * 4 + *(int *)(param_2 + 0xc)) = uVar38;
    *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
  }
  uVar22 = *(uint *)(puVar12 + 0xd9);
  iVar23 = *(int *)(param_2 + 0x28);
  piVar29 = (int *)(iVar23 + -8);
  uVar28 = (uint)(piVar29 + (uVar22 & 0x7ffffff) * -8) & 0xfffffff0;
  iVar20 = **(int **)(iVar9 + -0x7f54);
  *(uint *)(param_2 + 0x28) = uVar28;
  func_0x00fe6c3c(uVar28,uVar18 - 0x560,uVar22 * 0x20);
  uVar22 = *(uint *)(puVar12 + 0xd9);
  piVar7 = *(int **)(iVar9 + -0x7f50);
  *(uint *)(iVar23 + -4) = uVar28;
  *piVar29 = uVar22 << 2;
  *(int **)(iVar20 * 4 + *(int *)(param_2 + 0xc)) = piVar29;
  iVar9 = *(int *)(param_2 + 0x28);
  piVar29 = (int *)(iVar9 + -8);
  *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
  uVar28 = (uint)(piVar29 + (uVar22 & 0xfffffff) * -4) & 0xfffffff0;
  iVar23 = *piVar7;
  *(uint *)(param_2 + 0x28) = uVar28;
  func_0x00fe6c3c(uVar28,uVar18 - 0x620,uVar22 * 0x10);
  iVar20 = *(int *)(puVar12 + 0xd9);
  *(uint *)(iVar9 + -4) = uVar28;
  *piVar29 = iVar20 << 1;
  *(int **)(iVar23 * 4 + *(int *)(param_2 + 0xc)) = piVar29;
  *(ulonglong *)(param_2 + 0x18) = *(ulonglong *)(param_2 + 0x18) | 4;
LAB_000da7e0:
  if (!(bool)(bVar31 >> 1 & 1)) {
    func_0x00c24330(param_1,param_2,uVar18 - 0x4e0 & 0xffffffff,uVar18 - 0x4b0 & 0xffffffff,
                    uVar18 - 0x480 & 0xffffffff);
  }
  return;
}


