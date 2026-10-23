
void FUN_0014c430(int param_1,uint param_2,uint param_3)

{
  bool bVar1;
  char *pcVar2;
  int *piVar3;
  uint uVar4;
  uint *puVar5;
  int iVar6;
  char cVar7;
  uint uVar8;
  uint uVar9;
  int iVar10;
  int iVar11;
  int iVar12;
  int iVar13;
  ushort *puVar14;
  ulonglong uVar15;
  
  iVar6 = iRam0171482c;
  if ((*(char *)(param_1 + 0x20) != '\0') || (**(char **)(iRam0171482c + -0x7f50) != '\0')) {
    func_0x01399428(param_1 + 8,0);
  }
  iVar10 = param_1 + 8;
  pcVar2 = *(char **)(iVar6 + -0x7f50);
  iVar11 = 0;
  piVar3 = *(int **)(iVar6 + -0x7ffc);
  iVar12 = 0x200;
  uVar4 = *(uint *)(param_1 + *(int *)(param_1 + 0x24) * 0x5940 + 0x23ce8);
  do {
    while ((iVar13 = *(int *)(*(int *)(*piVar3 + 0x182d4) + iVar12), iVar13 < 0 ||
           (cVar7 = func_0x00201908(**(undefined4 **)(iVar6 + -0x7fc4),iVar13), cVar7 == '\0'))) {
LAB_0014c698:
      bVar1 = iVar11 == 3;
      iVar12 = iVar12 + 4;
      iVar11 = iVar11 + 1;
      if (bVar1) goto LAB_0014c6a8;
    }
    puVar5 = *(uint **)(iVar6 + -0x7fe4);
    if (0 < (int)*puVar5) {
      iVar13 = 0;
      puVar14 = *(ushort **)(iVar6 + -0x7f14);
LAB_0014c55c:
      do {
        if (((*puVar14 == uVar4) && (*(byte *)((int)puVar14 + 3) == param_2)) &&
           (puVar14[2] == param_3)) {
          if ((*(char *)(param_1 + 0x20) != '\0') || (*pcVar2 != '\0')) {
            func_0x01399428(iVar10,0);
          }
          func_0x00aec9b0(param_1 + *(int *)(param_1 + 0x24) * 0x7eb8 + 0x40,iVar13);
          if ((*(char *)(param_1 + 0x20) != '\0') || (*pcVar2 != '\0')) {
            func_0x01399448(iVar10);
            iVar13 = iVar13 + 1;
            uVar8 = *puVar5;
            puVar14 = puVar14 + 3;
            if ((int)uVar8 <= iVar13) break;
            goto LAB_0014c55c;
          }
        }
        iVar13 = iVar13 + 1;
        uVar8 = *puVar5;
        puVar14 = puVar14 + 3;
      } while (iVar13 < (int)uVar8);
      if (0 < (int)uVar8) {
        uVar15 = (ulonglong)uVar8;
        uVar9 = 0;
        uVar8 = *(uint *)(param_1 + *(int *)(param_1 + 0x24) * 0x7eb8 + 0x150) & 1;
        while (uVar8 != 0) {
          uVar9 = uVar9 + 1;
          uVar15 = uVar15 - 1;
          if (uVar15 == 0) goto LAB_0014c680;
          uVar8 = 1 << (uVar9 & 0x1f) &
                  *(uint *)(param_1 + (*(int *)(param_1 + 0x24) * 0x1fae + (uVar9 >> 5)) * 4 + 0x150
                           );
        }
        goto LAB_0014c698;
      }
    }
LAB_0014c680:
    uVar8 = *(uint *)(*piVar3 + 0x182dc);
    if (((uVar8 & 2) != 0) || ((uVar8 & 1) != 0)) goto LAB_0014c698;
    if ((*(char *)(param_1 + 0x20) != '\0') || (**(char **)(iVar6 + -0x7f50) != '\0')) {
      func_0x01399428(iVar10,0);
    }
    func_0x00ef8c9c(**(undefined4 **)(iVar6 + -0x7f38),0x1a);
    if ((*(char *)(param_1 + 0x20) == '\0') && (**(char **)(iVar6 + -0x7f50) == '\0'))
    goto LAB_0014c698;
    iVar12 = iVar12 + 4;
    func_0x01399448(iVar10);
    bVar1 = iVar11 != 3;
    iVar11 = iVar11 + 1;
  } while (bVar1);
LAB_0014c6a8:
  if ((*(char *)(param_1 + 0x20) != '\0') || (**(char **)(iVar6 + -0x7f50) != '\0')) {
    func_0x01399448(param_1 + 8);
  }
  return;
}


