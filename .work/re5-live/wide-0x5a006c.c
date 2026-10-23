
void FUN_005a006c(void)

{
  byte bVar1;
  short sVar2;
  short sVar3;
  int *piVar4;
  int iVar5;
  ulonglong uVar6;
  ulonglong uVar7;
  bool bVar8;
  uint in_r9;
  int in_r11;
  short *psVar9;
  undefined4 unaff_r23;
  int unaff_r24;
  longlong unaff_r27;
  longlong unaff_r28;
  int unaff_r29;
  int unaff_r30;
  ulonglong unaff_r31;
  ulonglong uVar10;
  longlong lVar11;
  
  uVar10 = unaff_r31;
  if ((in_r9 & 0x10010) == 0) {
    if ((in_r9 & 0x20020) == 0) {
      bVar8 = false;
      if ((in_r9 & 0x80080) != 0) {
        if ((int)unaff_r28 < 5) {
          bVar8 = false;
          uVar10 = unaff_r31 - (5 - unaff_r28);
          unaff_r28 = 0;
          unaff_r31 = uVar10;
          if ((int)uVar10 < 0) {
            uVar10 = 0;
            unaff_r31 = 0;
          }
        }
        else {
          unaff_r28 = unaff_r28 + -5;
        }
      }
    }
    else {
      lVar11 = unaff_r28 + 5;
      if ((int)lVar11 < (int)unaff_r27) {
        unaff_r28 = unaff_r27 + -5;
        if ((int)unaff_r28 < (int)lVar11) {
          bVar8 = false;
          uVar10 = unaff_r31 + (lVar11 - unaff_r28);
          unaff_r31 = uVar10;
          if (4 < (int)uVar10) {
            uVar10 = 4;
            unaff_r31 = 4;
          }
        }
        else {
          bVar8 = false;
          unaff_r28 = lVar11;
        }
      }
      else {
        bVar8 = false;
        uVar10 = (unaff_r27 - unaff_r28) - 1;
        unaff_r31 = uVar10;
      }
    }
  }
  else {
    bVar8 = true;
    if ((int)unaff_r28 != 0 || (int)unaff_r31 != 0) {
      if ((int)unaff_r31 == 0) {
        unaff_r28 = unaff_r28 + -1;
        bVar8 = false;
        uVar10 = 0;
      }
      else {
        uVar10 = unaff_r31 - 1;
        bVar8 = false;
        unaff_r31 = uVar10;
      }
    }
  }
  uVar10 = func_0x0013fd34(**(undefined4 **)(unaff_r30 + -0x7f30),uVar10 & 0xffffffff,5,0,
                           *(undefined1 *)(unaff_r29 + 2),0);
  iVar5 = (int)unaff_r28;
  if (iVar5 + (int)uVar10 < (int)unaff_r27) {
    unaff_r31 = uVar10;
  }
  if ((*(int *)(unaff_r29 + 0x80) == iVar5) && (*(int *)(unaff_r29 + 0x84) == (int)unaff_r31)) {
    if ((bVar8) || ((*(uint *)(unaff_r29 + 0x10) & 0x50050) == 0)) {
      lVar11 = 0x69;
      uVar10 = 0;
      sVar2 = *(short *)(in_r11 + (int)((unaff_r28 + unaff_r31 & 0xffffffff) << 3) +
                                  (int)((unaff_r28 + unaff_r31 & 0xffffffff) << 6) + 0x88);
      do {
        uVar6 = uVar10 & 0xffffffff;
        uVar7 = uVar10 & 0xffffffff;
        uVar10 = uVar10 + 1;
        psVar9 = (short *)(((int)(uVar7 << 4) - (int)(uVar6 << 2)) + *(int *)(unaff_r30 + -0x7ff8));
        if (*psVar9 == sVar2) {
          if (*(int *)(psVar9 + 4) == 0) {
            return;
          }
          if (*(short *)(unaff_r29 + 0xa56) == 0) {
            sVar3 = *(short *)(unaff_r29 + 0xa58);
            if (sVar3 == 0) {
              sVar3 = *(short *)(unaff_r29 + 0xa5a);
            }
            if (sVar3 == sVar2) {
              return;
            }
          }
          if (*(char *)(unaff_r29 + 0xa54) == '\0') {
            *(undefined1 *)(unaff_r29 + 0xa54) = 1;
          }
          *(short *)(unaff_r29 + 0xa56) = sVar2;
          return;
        }
        lVar11 = lVar11 + -1;
      } while (lVar11 != 0);
    }
  }
  else {
    piVar4 = *(int **)(unaff_r30 + -0x7f70);
    *(int *)(unaff_r29 + 0x84) = (int)unaff_r31;
    *(int *)(unaff_r29 + 0x80) = iVar5;
    iVar5 = *piVar4;
    bVar1 = *(byte *)(in_r11 + (int)((unaff_r31 + unaff_r28 & 0xffffffff) << 3) +
                               (int)((unaff_r31 + unaff_r28 & 0xffffffff) << 6) + 0x8e);
    if ((1 << (bVar1 & 0x1f) &
        *(uint *)(iVar5 + (*(int *)(iVar5 + 0x24) * 0x1fae + (uint)(bVar1 >> 5)) * 4 + 0xd4)) != 0)
    {
      if ((*(char *)(iVar5 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f00) != '\0')) {
        func_0x01399428(iVar5 + 8,0);
      }
      func_0x00aec7f4(iVar5 + *(int *)(iVar5 + 0x24) * 0x7eb8 + 0x40,bVar1);
      if ((*(char *)(iVar5 + 0x20) == '\0') && (**(char **)(unaff_r30 + -0x7f00) == '\0')) {
        *(undefined1 *)(unaff_r24 + 0x173) = 1;
      }
      else {
        func_0x01399448(iVar5 + 8);
        *(undefined1 *)(unaff_r24 + 0x173) = 1;
      }
    }
    func_0x0054bff8(unaff_r23);
  }
  return;
}


