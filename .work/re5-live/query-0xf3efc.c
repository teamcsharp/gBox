
void FUN_000f3efc(undefined8 param_1,int param_2,uint *param_3)

{
  int *piVar1;
  undefined4 *puVar2;
  int *piVar3;
  int *piVar4;
  int iVar5;
  int iVar6;
  ulonglong uVar7;
  int iVar8;
  char cVar10;
  int iVar9;
  
  iVar5 = iRam017147ec;
  piVar1 = *(int **)(iRam017147ec + -0x7ffc);
  if (*(int *)(*(int *)(*piVar1 + 0x182d4) + 0x2e8) != param_2) {
    puVar2 = *(undefined4 **)(iRam017147ec + -0x7fe8);
    iVar8 = func_0x001a617c(*puVar2,*(undefined1 *)((int)param_3 + 10));
    cVar10 = func_0x001a61bc(*puVar2,iVar8);
    if ((cVar10 != '\0') && (*(int *)(iVar8 + 0x2f20) != 2)) {
      piVar3 = *(int **)(iVar5 + -0x7ff8);
      uVar7 = (ulonglong)(*param_3 >> 8) & 0xfff;
      piVar4 = *(int **)(((int)(uVar7 << 4) - (int)(uVar7 << 2)) + *(int *)(*piVar3 + 0x84) + 8);
      if (piVar4 != (int *)0x0) {
        iVar9 = (*(code *)**(undefined4 **)(*piVar4 + 0x14))(piVar4);
        iVar5 = *(int *)(*(int *)(iVar5 + -0x7f18) + 4);
        if (*(int *)(iVar9 + 4) != iVar5) {
          iVar9 = *(int *)(iVar9 + 0x10);
          if (iVar9 == 0) {
            return;
          }
          iVar6 = *(int *)(iVar9 + 4);
          while (iVar6 != iVar5) {
            iVar9 = *(int *)(iVar9 + 0x10);
            if (iVar9 == 0) {
              return;
            }
            iVar6 = *(int *)(iVar9 + 4);
          }
        }
        uVar7 = (ulonglong)(*param_3 >> 8) & 0xfff;
        *(char *)(((int)(uVar7 << 4) - (int)(uVar7 << 2)) + *(int *)(*piVar3 + 0x84) + 3) =
             (char)*(undefined4 *)(*(int *)(*piVar1 + 0x182d4) + 0x2e8);
        (*(code *)**(undefined4 **)(*piVar4 + 0x128))(piVar4,*(undefined2 *)(param_3 + 2));
        piVar1 = (int *)piVar4[0x72a];
        piVar4[0x739] = iVar8;
        if (piVar1 != (int *)0x0) {
          *(undefined1 *)(piVar1 + 9) = 0;
          piVar1[8] = 1;
          (*(code *)**(undefined4 **)(*piVar1 + 0x48))(piVar1,iVar8);
          piVar1[0xc] = 0;
          if (param_3[1] != 0xffffffff) {
            (*(code *)**(undefined4 **)(*piVar1 + 0x4c))(piVar1,param_3[1]);
          }
        }
      }
    }
  }
  return;
}


