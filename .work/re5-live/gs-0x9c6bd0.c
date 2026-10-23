
void FUN_009c6bd0(undefined4 *param_1)

{
  int *piVar1;
  int *piVar2;
  int iVar3;
  int iVar4;
  int iVar5;
  uint uVar6;
  uint uVar7;
  
  iVar3 = iRam01714ecc;
  uVar6 = param_1[6];
  *param_1 = *(undefined4 *)(iRam01714ecc + -0x7ffc);
  if (uVar6 == 0) {
    iVar4 = param_1[1];
  }
  else {
    uVar7 = 0;
    iVar4 = param_1[1];
    piVar1 = *(int **)(iVar3 + -0x7ff8);
    do {
      piVar2 = *(int **)(uVar7 * 4 + iVar4);
      if (piVar2 != (int *)0x0) {
        iVar5 = piVar2[0x31];
        if (iVar5 == 1) {
          iVar5 = *piVar1 + 0x2f30;
LAB_009c6c3c:
          if (iVar5 != 0) {
            (*(code *)**(undefined4 **)(*piVar2 + 4))();
            iVar4 = param_1[1];
          }
        }
        else if ((iVar5 == 2) || (iVar5 == 0)) {
          iVar5 = *piVar1 + 0x2f2c;
          goto LAB_009c6c3c;
        }
        *(undefined4 *)(uVar7 * 4 + iVar4) = 0;
        uVar6 = param_1[6];
        iVar4 = param_1[1];
      }
      uVar7 = uVar7 + 1;
    } while (uVar7 < uVar6);
  }
  if (iVar4 != 0) {
    (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar3 + -0x7fdc) + 0x1c))
              ((int *)**(undefined4 **)(iVar3 + -0x7fdc),iVar4);
    param_1[1] = 0;
  }
  if (param_1[3] != 0) {
    (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar3 + -0x7fdc) + 0x1c))
              ((int *)**(undefined4 **)(iVar3 + -0x7fdc),param_1[3]);
    param_1[3] = 0;
  }
  param_1[6] = 0;
  param_1[5] = 0;
  if (param_1[2] != 0) {
    func_0x00b85d98(param_1[2]);
    param_1[2] = 0;
  }
  *param_1 = *(undefined4 *)(iVar3 + -0x7ef4);
  return;
}


