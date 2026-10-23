
void FUN_00e35b30(int param_1)

{
  bool bVar1;
  uint uVar2;
  int iVar3;
  int iVar4;
  longlong lVar5;
  char cVar6;
  ulonglong uVar7;
  uint uVar8;
  ulonglong uVar9;
  int iVar10;
  int iStack_90;
  int iStack_8c;
  int iStack_84;
  int iStack_80;
  int iStack_78;
  int iStack_74;
  undefined4 auStack_6c [9];
  
  iVar4 = iRam017154ec;
  if ((*(int *)(param_1 + 0x20) != 5) && (*(int *)(param_1 + 0x20) != 7)) {
    lVar5 = func_0x01399528();
    if (*(int *)(param_1 + 0x94) < (int)(lVar5 / 1000) - *(int *)(param_1 + 0x90)) {
      if (*(int *)(param_1 + 0x90) != -1) {
        iVar10 = *(int *)(param_1 + 0xa8) + 1 + ((*(int *)(param_1 + 0xa8) + 1U) / 3) * -3;
        *(int *)(param_1 + 0xa8) = iVar10;
        func_0x00b87f6c(&iStack_90,*(undefined4 *)(param_1 + iVar10 * 4 + 0x6c),0,0);
        func_0x00b87f6c(&iStack_84,*(undefined4 *)(param_1 + *(int *)(param_1 + 0xa8) * 4 + 0x78),0,
                        0);
        func_0x00b87f6c(&iStack_78,*(undefined4 *)(param_1 + *(int *)(param_1 + 0xa8) * 4 + 0x84),0,
                        0);
        if (*(char *)(param_1 + 0xad) == '\0') {
          if (*(int *)(param_1 + 0x54) != 0) {
            uVar8 = 0;
            do {
              uVar8 = uVar8 + 1;
              func_0x00fe6bcc(iStack_90,0,*(undefined4 *)(param_1 + 0x50));
              iStack_90 = iStack_90 + iStack_8c;
            } while (uVar8 < *(uint *)(param_1 + 0x54));
            if (*(uint *)(param_1 + 0x54) >> 1 != 0) {
              uVar8 = 0;
              do {
                uVar8 = uVar8 + 1;
                func_0x00fe6bcc(iStack_84,0,*(uint *)(param_1 + 0x50) >> 1);
                uVar2 = *(uint *)(param_1 + 0x54) >> 1;
                iStack_84 = iStack_84 + iStack_80;
              } while (uVar8 < uVar2);
              if (uVar2 != 0) {
                uVar8 = 0;
                do {
                  uVar8 = uVar8 + 1;
                  func_0x00fe6bcc(iStack_78,0,*(uint *)(param_1 + 0x50) >> 1);
                  iStack_78 = iStack_78 + iStack_74;
                } while (uVar8 < *(uint *)(param_1 + 0x54) >> 1);
              }
            }
          }
        }
        else {
          uVar9 = (ulonglong)*(uint *)(param_1 + 0x9c);
          if (*(int *)(param_1 + 0x54) != 0) {
            uVar8 = 0;
            uVar7 = (ulonglong)*(uint *)(param_1 + 0x50);
            do {
              uVar8 = uVar8 + 1;
              func_0x00fe6c3c(iStack_90,uVar9 & 0xffffffff,uVar7);
              uVar7 = (ulonglong)*(uint *)(param_1 + 0x50);
              uVar9 = uVar9 + uVar7;
              iStack_90 = iStack_90 + iStack_8c;
            } while (uVar8 < *(uint *)(param_1 + 0x54));
            iVar10 = *(int *)(param_1 + 0xa0);
            if (*(uint *)(param_1 + 0x54) >> 1 != 0) {
              uVar8 = 0;
              do {
                uVar8 = uVar8 + 1;
                func_0x00fe6c3c(iStack_84,iVar10,uVar7 >> 1);
                uVar7 = (ulonglong)*(uint *)(param_1 + 0x50);
                uVar2 = *(uint *)(param_1 + 0x54) >> 1;
                iVar10 = iVar10 + (*(uint *)(param_1 + 0x50) >> 1);
                iStack_84 = iStack_84 + iStack_80;
              } while (uVar8 < uVar2);
              iVar10 = *(int *)(param_1 + 0xa4);
              if (uVar2 != 0) {
                uVar8 = 0;
                do {
                  uVar8 = uVar8 + 1;
                  func_0x00fe6c3c(iStack_78,iVar10,uVar7 >> 1);
                  uVar7 = (ulonglong)*(uint *)(param_1 + 0x50);
                  iVar10 = iVar10 + (*(uint *)(param_1 + 0x50) >> 1);
                  iStack_78 = iStack_78 + iStack_74;
                } while (uVar8 < *(uint *)(param_1 + 0x54) >> 1);
              }
            }
          }
          *(undefined1 *)(param_1 + 0xac) = 1;
          *(int *)(param_1 + 0x1c) = *(int *)(param_1 + 0x1c) + 1;
        }
        func_0x00b87f44(*(undefined4 *)(param_1 + *(int *)(param_1 + 0xa8) * 4 + 0x6c),0);
        func_0x00b87f44(*(undefined4 *)(param_1 + *(int *)(param_1 + 0xa8) * 4 + 0x78),0);
        func_0x00b87f44(*(undefined4 *)(param_1 + *(int *)(param_1 + 0xa8) * 4 + 0x84),0);
      }
      iVar10 = 0;
      *(undefined4 *)(param_1 + 0x94) = 0xffffffff;
      while (cVar6 = func_0x00e336a4(*(undefined4 *)(param_1 + 0x4c),auStack_6c), cVar6 != '\0') {
        if (*(int *)(param_1 + 0x24) == 0) {
          *(undefined4 *)(param_1 + 0x94) = auStack_6c[0];
        }
        else {
          *(undefined4 *)(param_1 + 0x94) = 0;
        }
        lVar5 = func_0x01399528();
        bVar1 = iVar10 == 7;
        *(undefined1 *)(param_1 + 0xad) = 1;
        iVar10 = iVar10 + 1;
        *(int *)(param_1 + 0x90) = (int)(lVar5 / 1000);
        if (-1 < *(int *)(param_1 + 0x94)) {
          return;
        }
        if (bVar1) {
          return;
        }
      }
      iVar10 = *(int *)(param_1 + 0x4c);
      iVar3 = iVar10 + 0x30;
      func_0x01399428(iVar3,0);
      if (((*(int *)(iVar10 + 0x28) == 4) && (*(char *)(iVar10 + 0x50) != '\0')) &&
         (lVar5 = func_0x01399528(),
         (longlong)(ulonglong)*(uint *)(iVar10 + 0x54) <=
         (longlong)(lVar5 / 1000 - (ulonglong)*(uint *)(iVar10 + 0x48)))) {
        func_0x01399448(iVar3);
        iVar10 = *(int *)(param_1 + 0x4c);
        func_0x01399428(iVar10 + 0x30,0);
        if ((*(int *)(iVar10 + 0x28) == 4) || (*(int *)(iVar10 + 0x28) == 6)) {
          if (*(char *)(iVar10 + 0x50) == '\0') {
            *(ulonglong *)(*(int *)(iVar10 + 0x1e0) + 0x180) =
                 *(ulonglong *)(*(int *)(iVar10 + 0x1e0) + 0x180) | 0x40;
          }
          if (*(int *)(iVar10 + 0x1dc) != -1) {
            func_0x00c8211c(**(undefined4 **)(iVar4 + -0x7fc8),iVar10);
            *(undefined1 *)(iVar10 + 0x1d0) = 0;
            *(undefined4 *)(iVar10 + 0x1d4) = 0xffffffff;
          }
          *(undefined4 *)(iVar10 + 0x28) = 7;
        }
        func_0x01399448(iVar10 + 0x30);
        *(undefined4 *)(param_1 + 0x20) = 7;
      }
      else {
        func_0x01399448(iVar3);
      }
      *(undefined4 *)(param_1 + 0x94) = 0xffffffff;
      *(undefined4 *)(param_1 + 0x90) = 0xffffffff;
    }
  }
  return;
}


