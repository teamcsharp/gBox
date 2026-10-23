
void FUN_00364108(int param_1)

{
  bool bVar1;
  int iVar2;
  int iVar3;
  uint uVar4;
  undefined4 uVar6;
  ulonglong uVar5;
  int iVar7;
  int iVar8;
  int *piVar9;
  undefined4 *puVar10;
  double dVar11;
  
  iVar3 = iRam01714a8c;
  if (*(int *)(param_1 + 0x20) == 0) {
    piVar9 = *(int **)(param_1 + 8);
    if (piVar9 == (int *)0x0) {
LAB_00364428:
      piVar9 = (int *)0x0;
    }
    else {
      iVar7 = (*(code *)**(undefined4 **)(*piVar9 + 0x14))(piVar9);
      iVar8 = *(int *)(*(int *)(iVar3 + -0x7fe0) + 4);
      if (*(int *)(iVar7 + 4) != iVar8) {
        iVar7 = *(int *)(iVar7 + 0x10);
        if (iVar7 == 0) goto LAB_00364428;
        iVar2 = *(int *)(iVar7 + 4);
        while (iVar2 != iVar8) {
          iVar7 = *(int *)(iVar7 + 0x10);
          if (iVar7 == 0) goto LAB_00364428;
          iVar2 = *(int *)(iVar7 + 4);
        }
      }
    }
    *(int **)(param_1 + 0x20) = piVar9;
    *(undefined1 *)(piVar9 + 0x818) = 1;
  }
  iVar8 = *(int *)(param_1 + 0x20);
  *(undefined4 *)(param_1 + 0x24) = *(undefined4 *)(iVar8 + 0x1fb4);
  *(undefined4 *)(param_1 + 0x28) = *(undefined4 *)(iVar8 + 0x1fb8);
  *(undefined4 *)(param_1 + 0x2c) = 0;
  *(byte *)(iVar8 + 0x1a1c) = *(byte *)(iVar8 + 0x1a1c) | 0x40;
  piVar9 = *(int **)(param_1 + 0x20);
  if ((((*(byte *)(piVar9 + 0x687) & 0x10) != 0) || (iVar8 = piVar9[0x3ab], iVar8 == 2)) ||
     (iVar8 == 3)) goto LAB_003642b8;
  iVar7 = *(int *)(param_1 + 0x24);
  if (iVar7 == 1) {
    iVar7 = 2 - iVar8;
    uVar4 = iVar8 + 0x12;
LAB_003641d4:
    uVar4 = uVar4 & 0xff;
    uVar6 = func_0x0034d2e8(piVar9[0x82d],iVar7);
    *(undefined4 *)(param_1 + 0x2c) = uVar6;
    func_0x0082a95c(*(undefined4 *)(param_1 + 0x20),0x31,*(undefined4 *)(param_1 + 0x20),0xf);
    piVar9 = *(int **)(param_1 + 0x20);
  }
  else if (iVar7 == 2) {
    uVar4 = iVar8 + 0x19U & 0xff;
    uVar6 = func_0x0034d2e8(piVar9[0x82d],iVar8 + 3);
    *(undefined4 *)(param_1 + 0x2c) = uVar6;
    func_0x0082a95c(*(undefined4 *)(param_1 + 0x20),0x30,*(undefined4 *)(param_1 + 0x20),0xf);
    piVar9 = *(int **)(param_1 + 0x20);
  }
  else {
    uVar4 = 0xffff;
    if (iVar7 == 0) {
      iVar7 = iVar8 + 1;
      uVar4 = iVar8 + 0x10;
      goto LAB_003641d4;
    }
  }
  (*(code *)**(undefined4 **)(*piVar9 + 0xa4))(piVar9,1);
  dVar11 = (double)*(float *)(iVar3 + -0x7ef8);
  (*(code *)**(undefined4 **)(**(int **)(param_1 + 0x20) + 0x188))
            ((double)**(float **)(iVar3 + -0x7cc4),(double)*(float *)(iVar3 + -0x7ff0),dVar11,
             *(int **)(param_1 + 0x20),0,uVar4);
  (*(code *)**(undefined4 **)(**(int **)(param_1 + 0x20) + 0x188))
            ((double)*(float *)(iVar3 + -0x7f00),(double)*(float *)(iVar3 + -0x7ff0),dVar11,
             *(int **)(param_1 + 0x20),1,0x1b);
LAB_003642b8:
  puVar10 = (undefined4 *)(param_1 + 0x30);
  iVar8 = 0;
  do {
    iVar7 = iVar8 + param_1;
    bVar1 = iVar8 != 8;
    iVar8 = iVar8 + 4;
    *puVar10 = 0;
    puVar10[1] = 0;
    puVar10[2] = 0;
    puVar10[3] = 0;
    *(undefined4 *)(iVar7 + 0x60) = 0;
    puVar10 = puVar10 + 4;
  } while (bVar1);
  iVar8 = *(int *)(iVar3 + -0x7edc);
  *(undefined4 *)(param_1 + 0x6c) = 0x313;
  if ((*(char *)(*(int *)(param_1 + 0x28) * 8 + iVar8 + 0x40) != '\0') &&
     (uVar5 = func_0x00b7f730(*(undefined4 *)(iVar3 + -0x7f8c)), (uVar5 & 1) != 0)) {
    *(undefined4 *)(param_1 + 0x6c) = 0x30f;
    return;
  }
  return;
}


