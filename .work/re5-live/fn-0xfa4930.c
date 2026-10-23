
void FUN_00fa4930(int *param_1,int param_2)

{
  undefined4 uVar1;
  undefined4 uVar2;
  undefined4 uVar3;
  undefined4 uVar4;
  undefined4 uVar5;
  undefined4 uVar6;
  undefined4 uVar7;
  undefined4 uVar8;
  undefined4 uVar9;
  undefined4 uVar10;
  int iVar11;
  uint uVar12;
  int *piVar13;
  int iVar14;
  undefined4 *puVar15;
  uint uVar16;
  undefined1 auStack_bc0 [8];
  undefined1 auStack_bb8 [2836];
  uint uStack_a4;
  
  iVar11 = iRam017164f0;
  uVar12 = (*(code *)**(undefined4 **)(*param_1 + 0x18))(param_1);
  if ((uVar12 != 0) &&
     (piVar13 = (int *)(*(code *)**(undefined4 **)(*param_1 + 0x1c))(param_1,0),
     piVar13 != (int *)0x0)) {
    func_0x00fe74bc(auStack_bc0);
    (*(code *)**(undefined4 **)(*piVar13 + 0x10))(piVar13,auStack_bc0);
    if (1 < uVar12) {
      uVar16 = 1;
      do {
        func_0x00fe74bc(auStack_bb8);
        piVar13 = (int *)(*(code *)**(undefined4 **)(*param_1 + 0x1c))(param_1,uVar16);
        if (piVar13 == (int *)0x0) {
          func_0x00fe74dc(auStack_bb8);
          func_0x00fe74dc(auStack_bc0);
          return;
        }
        (*(code *)**(undefined4 **)(*piVar13 + 0x10))(piVar13,auStack_bb8);
        for (piVar13 = (int *)func_0x00fe74cc(auStack_bc0); piVar13 != (int *)0x0;
            piVar13 = (int *)piVar13[0xc]) {
          while ((((*piVar13 == 0 || ((*(ushort *)((int)piVar13 + 6) & 1) != 0)) ||
                  ((*(ushort *)((int)piVar13 + 6) & 0x20) != 0)) ||
                 (iVar14 = func_0x00fe76ac(auStack_bb8,*(undefined2 *)(piVar13 + 1),*piVar13),
                 iVar14 != 0))) {
            piVar13 = (int *)piVar13[0xc];
            if (piVar13 == (int *)0x0) goto LAB_00fa4b78;
          }
          *piVar13 = 0;
        }
LAB_00fa4b78:
        uVar16 = uVar16 + 1;
        func_0x00fe74dc(auStack_bb8);
      } while (uVar12 != uVar16);
    }
    piVar13 = (int *)func_0x00fe74cc(auStack_bc0);
    if (piVar13 != (int *)0x0) {
      iVar14 = 0;
      do {
        if (((*piVar13 != 0) && ((*(ushort *)((int)piVar13 + 6) & 1) == 0)) &&
           ((*(ushort *)((int)piVar13 + 6) & 0x20) == 0)) {
          puVar15 = *(undefined4 **)(iVar11 + -0x7ff8);
          uVar12 = puVar15[1];
          uVar1 = puVar15[10];
          uVar2 = *puVar15;
          uVar3 = puVar15[2];
          uVar4 = puVar15[3];
          uVar5 = puVar15[4];
          uVar6 = puVar15[5];
          uVar7 = puVar15[6];
          uVar8 = puVar15[7];
          uVar9 = puVar15[8];
          uVar10 = puVar15[9];
          uStack_a4._0_2_ = (short)(uVar12 >> 0x10);
          if (*(ushort *)(piVar13 + 1) < 0x3b) {
            iVar11 = *(int *)(iVar11 + -0x7fa8);
                    /* WARNING: Could not recover jumptable at 0x00fa4c78. Too many branches */
                    /* WARNING: Treating indirect jump as call */
            (*(code *)(*(int *)((uint)*(ushort *)(piVar13 + 1) * 4 + iVar11) + iVar11))();
            return;
          }
          if (uStack_a4._0_2_ != 0) {
            puVar15 = (undefined4 *)func_0x00fe787c(param_2);
            uStack_a4 = uVar12 | 0x40;
            *puVar15 = uVar2;
            puVar15[1] = uStack_a4;
            puVar15[2] = uVar3;
            puVar15[3] = uVar4;
            puVar15[5] = uVar6;
            puVar15[4] = uVar5;
            puVar15[6] = uVar7;
            puVar15[7] = uVar8;
            puVar15[9] = uVar10;
            puVar15[8] = uVar9;
            puVar15[10] = uVar1;
            puVar15[0xb] = iVar14;
            puVar15[0xd] = 0;
            puVar15[0xc] = 0;
            if (*(int *)(param_2 + 4) != 0) {
              *(undefined4 **)(*(int *)(param_2 + 4) + 0x30) = puVar15;
              puVar15[0xd] = *(undefined4 *)(param_2 + 4);
            }
            *(undefined4 **)(param_2 + 4) = puVar15;
          }
        }
        piVar13 = (int *)piVar13[0xc];
        iVar14 = iVar14 + 1;
      } while (piVar13 != (int *)0x0);
    }
    func_0x00fe74dc(auStack_bc0);
  }
  return;
}


