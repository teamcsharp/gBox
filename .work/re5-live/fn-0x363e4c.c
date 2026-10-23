
void FUN_00363e4c(int param_1)

{
  float fVar1;
  float fVar2;
  float *pfVar3;
  undefined4 *puVar4;
  int iVar5;
  int iVar6;
  int iVar7;
  int iVar8;
  int *piVar9;
  
  iVar7 = iRam01714a8c;
  if (*(int *)(param_1 + 0x20) != 0) goto LAB_00363e80;
  piVar9 = *(int **)(param_1 + 8);
  if (piVar9 == (int *)0x0) {
LAB_00363fc4:
    piVar9 = (int *)0x0;
  }
  else {
    iVar8 = (*(code *)**(undefined4 **)(*piVar9 + 0x14))(piVar9);
    iVar5 = *(int *)(*(int *)(iVar7 + -0x7fe0) + 4);
    if (*(int *)(iVar8 + 4) != iVar5) {
      iVar8 = *(int *)(iVar8 + 0x10);
      if (iVar8 == 0) goto LAB_00363fc4;
      iVar6 = *(int *)(iVar8 + 4);
      while (iVar6 != iVar5) {
        iVar8 = *(int *)(iVar8 + 0x10);
        if (iVar8 == 0) goto LAB_00363fc4;
        iVar6 = *(int *)(iVar8 + 4);
      }
    }
  }
  *(int **)(param_1 + 0x20) = piVar9;
  *(undefined1 *)(piVar9 + 0x818) = 1;
LAB_00363e80:
  pfVar3 = *(float **)(iVar7 + -0x7cc4);
  fVar1 = *(float *)(iVar7 + -0x7ff0);
  fVar2 = *(float *)(iVar7 + -0x7ef8);
  *(byte *)(*(int *)(param_1 + 0x20) + 0x1a1c) = *(byte *)(*(int *)(param_1 + 0x20) + 0x1a1c) | 0x40
  ;
  piVar9 = *(int **)(param_1 + 0x20);
  (*(code *)**(undefined4 **)(*piVar9 + 0x188))
            ((double)*pfVar3,(double)fVar1,(double)fVar2,piVar9,0,piVar9[0x3ab] + 0x3dU & 0xff);
  if (*(int *)(*(int *)(param_1 + 0x20) + 0xeac) == 0) {
    piVar9 = *(int **)(iVar7 + -0x7e78);
    puVar4 = *(undefined4 **)(iVar7 + -0x7e6c);
    *(undefined1 *)(param_1 + 0x24) = 1;
    func_0x000c101c(*puVar4,*(undefined4 *)(*(int *)(*piVar9 + 0x3834) + 0x868),0);
  }
  return;
}


