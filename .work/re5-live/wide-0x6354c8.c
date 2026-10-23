
void FUN_006354c8(void)

{
  bool bVar1;
  undefined4 uVar2;
  undefined4 *puVar3;
  float fVar4;
  int iVar5;
  int iVar6;
  undefined4 *puVar7;
  undefined4 *puVar8;
  int unaff_r15;
  int unaff_r16;
  int unaff_r17;
  undefined4 *unaff_r18;
  int unaff_r19;
  undefined4 *unaff_r20;
  undefined4 *puVar9;
  undefined4 *unaff_r21;
  undefined4 *puVar10;
  undefined4 *unaff_r22;
  undefined4 *puVar11;
  undefined4 *unaff_r23;
  undefined4 *puVar12;
  undefined4 *unaff_r24;
  undefined4 *puVar13;
  undefined4 *unaff_r25;
  undefined4 *puVar14;
  undefined4 *unaff_r26;
  int unaff_r27;
  float *pfVar15;
  undefined4 *unaff_r29;
  int unaff_r30;
  int unaff_r31;
  double dVar16;
  double in_f28;
  double in_f30;
  double in_f31;
  undefined4 *in_stack_00000074;
  undefined4 *in_stack_0000007c;
  undefined4 *in_stack_00000084;
  undefined4 *in_stack_0000008c;
  undefined4 *in_stack_00000094;
  undefined4 *in_stack_0000009c;
  
  do {
    if ((*(uint *)(**(int **)(unaff_r30 + -0x7f4c) +
                   *(int *)(**(int **)(unaff_r30 + -0x7f4c) + 0x24) * 0x7eb8 + 0xa4) & 0x10) != 0) {
      *unaff_r29 = *in_stack_0000009c;
      unaff_r29[1] = in_stack_0000009c[1];
      unaff_r29[2] = in_stack_0000009c[2];
      unaff_r29[3] = in_stack_0000009c[3];
    }
LAB_006353c0:
    while( true ) {
      do {
        puVar14 = unaff_r26;
        puVar11 = unaff_r23;
        puVar13 = unaff_r25;
        puVar12 = unaff_r24;
        puVar10 = unaff_r22;
        puVar9 = unaff_r21;
        puVar8 = unaff_r20;
        puVar7 = unaff_r18;
        bVar1 = unaff_r19 == 1;
        unaff_r18 = puVar7 + 4;
        unaff_r20 = puVar8 + 4;
        unaff_r21 = puVar9 + 4;
        unaff_r22 = puVar10 + 4;
        unaff_r23 = puVar11 + 4;
        unaff_r24 = puVar12 + 4;
        unaff_r25 = puVar13 + 4;
        unaff_r26 = puVar14 + 4;
        unaff_r19 = unaff_r19 + 1;
        if (bVar1) {
          pfVar15 = (float *)(unaff_r27 + 0x3e4);
          iVar5 = -0x20;
          *(undefined4 *)(unaff_r31 + 0x7c) = 1;
          *(undefined4 *)(unaff_r31 + 0x5e4) = 0;
          *(undefined4 *)(unaff_r31 + 0x80) = 0;
          do {
            dVar16 = (double)func_0x00b299e8((double)(float)((double)((float)((double)(longlong)
                                                                                      iVar5 / in_f31
                                                                             ) *
                                                                     (float)((double)(longlong)iVar5
                                                                            / in_f31)) * in_f30));
            bVar1 = iVar5 != 0x1f;
            iVar5 = iVar5 + 1;
            fVar4 = (float)(dVar16 * in_f28) + *(float *)(unaff_r31 + 0x5e4);
            *pfVar15 = (float)(dVar16 * in_f28);
            pfVar15[0x40] = fVar4;
            pfVar15 = pfVar15 + 1;
            *(float *)(unaff_r31 + 0x5e4) = fVar4;
          } while (bVar1);
          return;
        }
        iVar5 = unaff_r16;
        if (unaff_r19 != 0) {
          iVar5 = unaff_r15;
        }
      } while (((iVar5 == 0) || (0x1d < iVar5)) ||
              (puVar3 = *(undefined4 **)(*(int *)(unaff_r30 + -0x7f50) + iVar5 * 4),
              puVar3 == (undefined4 *)0x0));
      *unaff_r18 = *puVar3;
      puVar7[5] = puVar3[1];
      puVar7[6] = puVar3[2];
      puVar7[7] = puVar3[3];
      *unaff_r20 = puVar3[4];
      puVar8[5] = puVar3[5];
      puVar8[6] = puVar3[6];
      puVar8[7] = puVar3[7];
      *unaff_r21 = puVar3[8];
      puVar9[5] = puVar3[9];
      puVar9[6] = puVar3[10];
      puVar9[7] = puVar3[0xb];
      *unaff_r22 = puVar3[0xc];
      puVar10[5] = puVar3[0xd];
      puVar10[6] = puVar3[0xe];
      puVar10[7] = puVar3[0xf];
      *unaff_r23 = puVar3[0x10];
      puVar11[5] = puVar3[0x11];
      puVar11[6] = puVar3[0x12];
      puVar11[7] = puVar3[0x13];
      *unaff_r24 = puVar3[0x14];
      puVar12[5] = puVar3[0x15];
      puVar12[6] = puVar3[0x16];
      puVar12[7] = puVar3[0x17];
      *unaff_r25 = puVar3[0x18];
      puVar13[5] = puVar3[0x19];
      puVar13[6] = puVar3[0x1a];
      puVar13[7] = puVar3[0x1b];
      *unaff_r26 = puVar3[0x1c];
      puVar14[5] = puVar3[0x1d];
      puVar14[6] = puVar3[0x1e];
      puVar14[7] = puVar3[0x1f];
      if (iVar5 == 1) {
        if ((*(uint *)(**(int **)(unaff_r30 + -0x7f4c) +
                       *(int *)(**(int **)(unaff_r30 + -0x7f4c) + 0x24) * 0x7eb8 + 0xa4) & 2) != 0)
        {
          *unaff_r25 = *in_stack_00000074;
          puVar13[5] = in_stack_00000074[1];
          puVar13[6] = in_stack_00000074[2];
          puVar13[7] = in_stack_00000074[3];
        }
        puVar7 = in_stack_0000007c;
        if (*(int *)(**(int **)(unaff_r30 + -0x7f48) + 0x45a0) == 0) goto LAB_006355d8;
        goto LAB_00635564;
      }
      unaff_r29 = unaff_r24;
      if (iVar5 == 2) break;
      if (iVar5 == 3) {
        if ((*(uint *)(**(int **)(unaff_r30 + -0x7fd4) + 0x182dc) & 0x200000) != 0) {
          *unaff_r22 = *in_stack_0000008c;
          puVar10[5] = in_stack_0000008c[1];
          puVar10[6] = in_stack_0000008c[2];
          puVar10[7] = in_stack_0000008c[3];
        }
      }
      else if ((iVar5 == 8) &&
              ((*(uint *)(**(int **)(unaff_r30 + -0x7fd4) + 0x182dc) & 0x200000) != 0)) {
        *unaff_r24 = *in_stack_00000094;
        puVar12[5] = in_stack_00000094[1];
        puVar12[6] = in_stack_00000094[2];
        puVar12[7] = in_stack_00000094[3];
      }
    }
  } while( true );
LAB_006355d8:
  uVar2 = **(undefined4 **)(unaff_r30 + -0x7f44);
  iVar5 = func_0x00201ba8(uVar2,0);
  iVar6 = func_0x00201ba8(uVar2,7);
  puVar7 = in_stack_00000084;
  if (iVar5 != 0 || iVar6 != 0) {
LAB_00635564:
    puVar8 = (undefined4 *)(unaff_r17 + unaff_r19 * 0x10);
    *puVar8 = *puVar7;
    puVar8[1] = puVar7[1];
    puVar8[2] = puVar7[2];
    puVar8[3] = puVar7[3];
  }
  goto LAB_006353c0;
}


