
void FUN_00615ffc(void)

{
  undefined4 uVar1;
  float fVar2;
  int iVar3;
  float fVar4;
  char cVar5;
  int iVar6;
  int iVar7;
  int iVar8;
  int iVar9;
  int *unaff_r24;
  int unaff_r27;
  int unaff_r29;
  int unaff_r30;
  ulonglong uVar10;
  
  fVar2 = *(float *)(unaff_r30 + -0x7f38);
  fVar4 = *(float *)(unaff_r29 + 0x40) - *(float *)(**(int **)(unaff_r30 + -0x7f3c) + 0x2c);
  *(float *)(unaff_r29 + 0x40) = fVar4;
  if (fVar4 <= fVar2) {
    *(undefined1 *)(unaff_r29 + 0x39) = 0;
    cVar5 = func_0x009c0afc(*(undefined4 *)(*unaff_r24 + 0x182d4));
    if (cVar5 == '\0') {
      *(undefined1 *)(unaff_r29 + 0x17) = 0x5a;
    }
    else {
      *(undefined1 *)(unaff_r29 + 0x17) = 0x50;
    }
  }
  if (0 < (int)*(uint *)(unaff_r29 + 0x184)) {
    uVar10 = (ulonglong)*(uint *)(unaff_r29 + 0x184);
    iVar3 = *(int *)(unaff_r29 + 0x180);
    uVar1 = *(undefined4 *)(unaff_r30 + -0x7f54);
    iVar8 = 0;
    iVar6 = 0x180;
    iVar9 = unaff_r27;
LAB_00615f0c:
    do {
      if (iVar3 == iVar8) {
        fVar2 = *(float *)(unaff_r30 + -0x7f38);
        iVar7 = unaff_r27 + iVar6;
        fVar4 = *(float *)(iVar7 + 0xc) - *(float *)(unaff_r29 + 0x10);
        *(float *)(iVar7 + 0xc) = fVar4;
        if (fVar4 <= fVar2) {
          *(float *)(iVar7 + 0xc) = fVar2;
          iVar8 = iVar8 + 1;
          iVar6 = iVar6 + 4;
          iVar9 = iVar9 + 4;
          uVar10 = uVar10 - 1;
          if (uVar10 == 0) break;
          goto LAB_00615f0c;
        }
      }
      else {
        *(undefined4 *)(iVar9 + 0x18c) = uVar1;
      }
      iVar8 = iVar8 + 1;
      iVar6 = iVar6 + 4;
      iVar9 = iVar9 + 4;
      uVar10 = uVar10 - 1;
    } while (uVar10 != 0);
  }
  FUN_00610698(unaff_r27);
  func_0x005bbc2c(unaff_r27);
  return;
}


