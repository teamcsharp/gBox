
void FUN_00615bb4(int param_1)

{
  undefined4 uVar1;
  float fVar2;
  undefined4 *puVar3;
  int iVar4;
  float fVar5;
  int iVar6;
  int iVar7;
  int iVar8;
  int iVar9;
  int iVar10;
  ulonglong uVar11;
  
  iVar6 = iRam01714c1c;
  puVar3 = *(undefined4 **)(iRam01714c1c + -0x7fd4);
  func_0x00110a1c(*puVar3,*(undefined4 *)(param_1 + 0x178));
  func_0x00110a4c(*puVar3,*(undefined4 *)(param_1 + 0x178));
  func_0x00110c68(*puVar3,*(undefined4 *)(param_1 + 0x178));
  if (*(byte *)(param_1 + 0x17) < 0x5d) {
                    /* WARNING: Could not recover jumptable at 0x00615ca0. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (*(code *)(*(int *)((uint)*(byte *)(param_1 + 0x17) * 4 + *(int *)(iVar6 + -0x7e24)) +
              *(int *)(iVar6 + -0x7e24)))();
    return;
  }
  if (0 < (int)*(uint *)(param_1 + 0x184)) {
    uVar11 = (ulonglong)*(uint *)(param_1 + 0x184);
    iVar4 = *(int *)(param_1 + 0x180);
    uVar1 = *(undefined4 *)(iVar6 + -0x7f54);
    iVar9 = 0;
    iVar7 = 0x180;
    iVar10 = param_1;
LAB_00615f0c:
    do {
      if (iVar4 == iVar9) {
        fVar2 = *(float *)(iVar6 + -0x7f38);
        iVar8 = param_1 + iVar7;
        fVar5 = *(float *)(iVar8 + 0xc) - *(float *)(param_1 + 0x10);
        *(float *)(iVar8 + 0xc) = fVar5;
        if (fVar5 <= fVar2) {
          *(float *)(iVar8 + 0xc) = fVar2;
          iVar9 = iVar9 + 1;
          iVar7 = iVar7 + 4;
          iVar10 = iVar10 + 4;
          uVar11 = uVar11 - 1;
          if (uVar11 == 0) break;
          goto LAB_00615f0c;
        }
      }
      else {
        *(undefined4 *)(iVar10 + 0x18c) = uVar1;
      }
      iVar9 = iVar9 + 1;
      iVar7 = iVar7 + 4;
      iVar10 = iVar10 + 4;
      uVar11 = uVar11 - 1;
    } while (uVar11 != 0);
  }
  func_0x00610698(param_1);
  func_0x005bbc2c(param_1);
  return;
}


