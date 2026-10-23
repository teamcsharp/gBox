
void FUN_0001f7a8(int param_1)

{
  int *piVar1;
  int *piVar2;
  int iVar3;
  undefined4 uVar4;
  undefined4 *puVar5;
  char *pcVar6;
  int iVar7;
  char cVar10;
  int iVar8;
  uint uVar9;
  undefined8 uVar11;
  int iVar12;
  ulonglong uVar13;
  undefined4 uVar14;
  int *unaff_r24;
  int iVar15;
  int iVar16;
  int unaff_r30;
  
  piVar1 = *(int **)(unaff_r30 + -0x7ff4);
  piVar2 = *(int **)(unaff_r30 + -0x7f78);
  uVar13 = 0;
  iVar8 = *piVar1;
  iVar3 = *(int *)(*piVar2 + 0x1f98);
  iVar12 = *(int *)(iVar8 + 0x24) * 0x5940;
  iVar7 = *(int *)(iVar8 + iVar12 + 0x23ce0);
  uVar4 = *(undefined4 *)(iVar8 + iVar12 + 0x23cd8);
  func_0x01399428(param_1 + 8,0);
  do {
    uVar14 = (undefined4)uVar13;
    func_0x009c0ce0(*(undefined4 *)(*unaff_r24 + 0x182d4),uVar14);
    iVar12 = (int)((uVar13 & 0xffffffff) << 2) + 0x200;
    iVar8 = *(int *)(*(int *)(*unaff_r24 + 0x182d4) + iVar12);
    if (iVar3 == iVar8) {
LAB_0001fb8c:
      iVar12 = *piVar1;
      cVar10 = *(char *)(iVar12 + ((int)((uVar13 & 0xffffffff) << 5) -
                                  (int)((uVar13 & 0xffffffff) << 3)) +
                                  *(int *)(iVar12 + 0x24) * 0x5940 + 0x23d0c);
      FUN_001426ec(iVar12,iVar8);
      if (cVar10 != '\0') {
        iVar8 = *piVar1;
        if ((*(char *)(iVar8 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
          func_0x01399428(iVar8 + 8,0);
        }
        func_0x00aec97c(iVar8 + *(int *)(iVar8 + 0x24) * 0x7eb8 + 0x40,uVar4,iVar7);
        if ((*(char *)(iVar8 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
          func_0x01399448(iVar8 + 8);
        }
        func_0x0014723c(*piVar1,iVar7);
      }
      iVar8 = func_0x00aee48c(*piVar1 + *(int *)(*piVar1 + 0x24) * 0x7eb8 + 0x40);
      if (-1 < iVar8) {
        iVar12 = iVar8 + 1;
        if (((*(uint *)(*piVar1 + *(int *)(*piVar1 + 0x24) * 0x7eb8 + 0xb4) & 0x40000) == 0) &&
           (0 < iVar12)) {
          pcVar6 = *(char **)(unaff_r30 + -0x7e58);
          iVar15 = 0;
          do {
            iVar16 = iVar15 + 1;
            uVar9 = func_0x00aed720(*piVar1 + *(int *)(*piVar1 + 0x24) * 0x7eb8 + 0x40,iVar15);
            if ((uVar9 != 0) && (uVar9 < 0x4651)) {
              iVar15 = *piVar1;
              if ((*(char *)(iVar15 + 0x20) != '\0') || (*pcVar6 != '\0')) {
                func_0x01399428(iVar15 + 8,0);
              }
              iVar16 = iVar15 + *(int *)(iVar15 + 0x24) * 0x7eb8 + 0x40;
              *(uint *)(iVar16 + 0x74) = *(uint *)(iVar16 + 0x74) | 0x40000;
              if ((*(char *)(iVar15 + 0x20) != '\0') || (*pcVar6 != '\0')) {
                func_0x01399448(iVar15 + 8);
              }
              func_0x009c0d08(*(undefined4 *)(*unaff_r24 + 0x182d4),uVar14,0xc);
              break;
            }
            iVar15 = iVar16;
          } while (iVar12 != iVar16);
        }
        iVar15 = *piVar1;
        if ((*(uint *)(iVar15 + *(int *)(iVar15 + 0x24) * 0x7eb8 + 0xa4) & 4) == 0) {
          if ((*(char *)(iVar15 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
            func_0x01399428(iVar15 + 8,0);
          }
          iVar16 = iVar15 + *(int *)(iVar15 + 0x24) * 0x7eb8 + 0x40;
          *(uint *)(iVar16 + 100) = *(uint *)(iVar16 + 100) | 2;
          if ((*(char *)(iVar15 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
            func_0x01399448(iVar15 + 8);
          }
          iVar15 = *piVar1;
          if ((*(char *)(iVar15 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
            func_0x01399428(iVar15 + 8,0);
          }
          iVar16 = iVar15 + *(int *)(iVar15 + 0x24) * 0x7eb8 + 0x40;
          *(uint *)(iVar16 + 100) = *(uint *)(iVar16 + 100) | 4;
          if ((*(char *)(iVar15 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
            func_0x01399448(iVar15 + 8);
          }
          func_0x009c0d08(*(undefined4 *)(*unaff_r24 + 0x182d4),uVar14,0xb);
          cVar10 = FUN_000dbff4(*unaff_r24);
          if (cVar10 != '\0') {
            func_0x009c0d08(*(undefined4 *)(*unaff_r24 + 0x182d4),uVar14,0x16);
            func_0x009c0d08(*(undefined4 *)(*unaff_r24 + 0x182d4),uVar14,0x17);
            func_0x009c0d08(*(undefined4 *)(*unaff_r24 + 0x182d4),uVar14,0x18);
            func_0x009c0d08(*(undefined4 *)(*unaff_r24 + 0x182d4),uVar14,0x19);
            func_0x009c0d08(*(undefined4 *)(*unaff_r24 + 0x182d4),uVar14,0x1a);
          }
        }
        iVar15 = *piVar1;
        if ((*(uint *)(iVar15 + *(int *)(iVar15 + 0x24) * 0x7eb8 + 0xa4) & 8) == 0) {
          if ((*(char *)(iVar15 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
            func_0x01399428(iVar15 + 8,0);
          }
          iVar16 = iVar15 + *(int *)(iVar15 + 0x24) * 0x7eb8 + 0x40;
          *(uint *)(iVar16 + 100) = *(uint *)(iVar16 + 100) | 8;
          if ((*(char *)(iVar15 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
            func_0x01399448(iVar15 + 8);
          }
          func_0x009c0d08(*(undefined4 *)(*unaff_r24 + 0x182d4),uVar14,0xd);
        }
        if ((1 < iVar8) &&
           (iVar8 = *piVar1, (*(uint *)(iVar8 + *(int *)(iVar8 + 0x24) * 0x7eb8 + 0xa4) & 0x10) == 0
           )) {
          if ((*(char *)(iVar8 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
            func_0x01399428(iVar8 + 8,0);
          }
          iVar15 = iVar8 + *(int *)(iVar8 + 0x24) * 0x7eb8 + 0x40;
          *(uint *)(iVar15 + 100) = *(uint *)(iVar15 + 100) | 0x10;
          if ((*(char *)(iVar8 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
            func_0x01399448(iVar8 + 8);
          }
          func_0x009c0d08(*(undefined4 *)(*unaff_r24 + 0x182d4),uVar14,0xe);
        }
        iVar8 = *unaff_r24;
        if ((*(char *)(iVar8 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
          func_0x01399428(iVar8 + 8,0);
        }
        *(uint *)(iVar8 + 0x182dc) = *(uint *)(iVar8 + 0x182dc) | 0x200000;
        if ((*(char *)(iVar8 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
          func_0x01399448(iVar8 + 8);
        }
        if (0 < iVar12) {
          iVar8 = 0;
          func_0x0014723c(*piVar1,0x10);
LAB_00020010:
          iVar15 = iVar8 + 1;
          iVar16 = iVar8;
          if (iVar12 != iVar8 + 1) {
            do {
              iVar8 = iVar15;
              func_0x0014723c(*piVar1,iVar16 + 0x11);
              uVar11 = 2;
              if (iVar8 != 2) {
                uVar11 = 3;
                if ((iVar8 != 3) && (uVar11 = 1, iVar8 != 1)) goto LAB_00020010;
              }
              func_0x001036d4(**(undefined4 **)(unaff_r30 + -0x7fc8),uVar11);
              iVar15 = iVar8 + 1;
              iVar16 = iVar8;
              if (iVar12 == iVar8 + 1) break;
            } while( true );
          }
        }
      }
      func_0x005f50a8();
      iVar8 = 0;
      if (((((((iVar7 == 1) || (iVar8 = 1, iVar7 == 4)) || (iVar8 = 2, iVar7 == 5)) ||
            ((iVar8 = 3, iVar7 == 6 || (iVar8 = 4, iVar7 == 7)))) ||
           ((iVar8 = 5, iVar7 == 9 || ((iVar8 = 6, iVar7 == 10 || (iVar8 = 7, iVar7 == 0xb)))))) ||
          (iVar8 = 8, iVar7 == 0xc)) || (iVar8 = 9, iVar7 == 0xe)) {
LAB_00020220:
        cVar10 = func_0x00aecb50(*piVar1 + *(int *)(*piVar1 + 0x24) * 0x7eb8 + 0x40,iVar7);
        if (cVar10 != '\0') {
          iVar12 = *piVar1;
          uVar9 = 1 << iVar8 + 1;
          if ((uVar9 & *(uint *)(iVar12 + *(int *)(iVar12 + 0x24) * 0x7eb8 + 0xb8)) == 0) {
            if ((*(char *)(iVar12 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
              func_0x01399428(iVar12 + 8,0);
            }
            iVar15 = iVar12 + *(int *)(iVar12 + 0x24) * 0x7eb8 + 0x40;
            *(uint *)(iVar15 + 0x78) = uVar9 | *(uint *)(iVar15 + 0x78);
            if ((*(char *)(iVar12 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
              func_0x01399448(iVar12 + 8);
            }
            func_0x009c0d08(*(undefined4 *)(*unaff_r24 + 0x182d4),uVar14,iVar8);
            cVar10 = FUN_000dbff4(*unaff_r24);
            if ((cVar10 != '\0') && (iVar8 == 2)) {
              func_0x009c0d08(*(undefined4 *)(*unaff_r24 + 0x182d4),uVar14,0x15);
            }
          }
        }
      }
      else if (iVar7 == 0xf) {
        iVar8 = 10;
        goto LAB_00020220;
      }
      FUN_001426f0(*piVar1);
    }
    else {
      func_0x000bbca0(**(undefined4 **)(unaff_r30 + -0x7f6c));
      puVar5 = *(undefined4 **)(unaff_r30 + -0x7f7c);
      cVar10 = func_0x00201908(*puVar5,*(undefined4 *)(*piVar2 + 0x1f98));
      if (((cVar10 != '\0') &&
          (iVar12 = *(int *)(*(int *)(*unaff_r24 + 0x182d4) + iVar12), -1 < iVar12)) &&
         (cVar10 = func_0x00201908(*puVar5,iVar12), cVar10 != '\0')) goto LAB_0001fb8c;
    }
    uVar13 = uVar13 + 1;
    if (uVar13 == 2) {
      func_0x01399448(param_1 + 8);
      iVar8 = *piVar1;
      if ((*(char *)(iVar8 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
        func_0x01399428(iVar8 + 8,0);
      }
      func_0x009be56c(iVar8 + *(int *)(iVar8 + 0x24) * 0x5940 + 0x1fb20);
      if ((*(char *)(iVar8 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
        func_0x01399448(iVar8 + 8);
      }
      iVar8 = *piVar1;
      if ((*(char *)(iVar8 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
        func_0x01399428(iVar8 + 8,0);
      }
      func_0x009be8d8(iVar8 + *(int *)(iVar8 + 0x24) * 0x5940 + 0x1fb20);
      if ((*(char *)(iVar8 + 0x20) == '\0') && (**(char **)(unaff_r30 + -0x7e58) == '\0')) {
        iVar8 = *piVar1;
        uVar9 = *(uint *)(iVar8 + *(int *)(iVar8 + 0x24) * 0x5940 + 0x23ce0);
      }
      else {
        func_0x01399448(iVar8 + 8);
        iVar8 = *piVar1;
        uVar9 = *(uint *)(iVar8 + *(int *)(iVar8 + 0x24) * 0x5940 + 0x23ce0);
      }
      if (0xf < uVar9) {
        if ((*(char *)(iVar8 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
          func_0x01399428(iVar8 + 8,0);
        }
        *(undefined4 *)(iVar8 + *(int *)(iVar8 + 0x24) * 0x5940 + 0x23cd0) = 2;
        if ((*(char *)(iVar8 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
          func_0x01399448(iVar8 + 8);
        }
      }
      if (((*(uint *)(*unaff_r24 + 0x182dc) & 4) != 0) &&
         (iVar8 = *piVar1, 1 < *(uint *)(iVar8 + *(int *)(iVar8 + 0x24) * 0x5940 + 0x23ce0))) {
        if ((*(char *)(iVar8 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
          func_0x01399428(iVar8 + 8,0);
        }
        *(undefined4 *)(iVar8 + *(int *)(iVar8 + 0x24) * 0x5940 + 0x23cd0) = 0;
        if ((*(char *)(iVar8 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7e58) != '\0')) {
          func_0x01399448(iVar8 + 8);
        }
      }
      func_0x001445d4(*piVar1);
      if (*(int *)(*(int *)(*unaff_r24 + 0x182d4) + 0x2e8) ==
          *(int *)(*(int *)(*unaff_r24 + 0x182d4) + 0x2ec)) {
        func_0x0010b588(**(undefined4 **)(unaff_r30 + -0x7fc8));
      }
      return;
    }
  } while( true );
}


