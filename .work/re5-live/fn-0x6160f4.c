
void FUN_006160f4(void)

{
  undefined4 uVar1;
  float fVar2;
  int iVar3;
  float fVar4;
  int iVar5;
  int iVar6;
  int iVar7;
  int iVar8;
  int unaff_r27;
  int unaff_r29;
  int unaff_r30;
  ulonglong uVar9;
  
  if (0 < (int)*(uint *)(unaff_r29 + 0x184)) {
    uVar9 = (ulonglong)*(uint *)(unaff_r29 + 0x184);
    iVar3 = *(int *)(unaff_r29 + 0x180);
    uVar1 = *(undefined4 *)(unaff_r30 + -0x7f54);
    iVar7 = 0;
    iVar5 = 0x180;
    iVar8 = unaff_r27;
LAB_00615f0c:
    do {
      if (iVar3 == iVar7) {
        fVar2 = *(float *)(unaff_r30 + -0x7f38);
        iVar6 = unaff_r27 + iVar5;
        fVar4 = *(float *)(iVar6 + 0xc) - *(float *)(unaff_r29 + 0x10);
        *(float *)(iVar6 + 0xc) = fVar4;
        if (fVar4 <= fVar2) {
          *(float *)(iVar6 + 0xc) = fVar2;
          iVar7 = iVar7 + 1;
          iVar5 = iVar5 + 4;
          iVar8 = iVar8 + 4;
          uVar9 = uVar9 - 1;
          if (uVar9 == 0) break;
          goto LAB_00615f0c;
        }
      }
      else {
        *(undefined4 *)(iVar8 + 0x18c) = uVar1;
      }
      iVar7 = iVar7 + 1;
      iVar5 = iVar5 + 4;
      iVar8 = iVar8 + 4;
      uVar9 = uVar9 - 1;
    } while (uVar9 != 0);
  }
  FUN_00610698(unaff_r27);
  func_0x005bbc2c(unaff_r27);
  return;
}


