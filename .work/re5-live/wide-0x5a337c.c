
void FUN_005a337c(int param_1,int param_2)

{
  int *piVar1;
  int *piVar2;
  undefined4 *puVar3;
  undefined4 uVar4;
  int iVar5;
  ushort *puVar6;
  int iVar7;
  uint uVar8;
  int iVar9;
  ushort uVar10;
  int iVar11;
  undefined2 *puVar12;
  
  iVar5 = iRam01714bdc;
  uVar8 = *(uint *)(param_2 + *(int *)(param_2 + 0x9dc) * 4 + 0x9e4);
  if (*(char *)(param_2 + 0x3d) == '\0') {
    iVar7 = *(int *)(param_2 + 0x54);
    iVar11 = *(int *)(param_2 + 0x50);
    iVar9 = func_0x005f38a4(param_1,iVar11,iVar7,0);
    if (uVar8 < 7) {
                    /* WARNING: Could not recover jumptable at 0x005a37a0. Too many branches */
                    /* WARNING: Treating indirect jump as call */
      (*(code *)(*(int *)(uVar8 * 4 + *(int *)(iVar5 + -0x7e18)) + *(int *)(iVar5 + -0x7e18)))();
      return;
    }
    uVar10 = (ushort)*(undefined4 *)(iVar9 + 4);
    iVar9 = *(int *)(param_2 + 0x54);
    piVar1 = *(int **)(iVar5 + -0x7f70);
    puVar6 = (ushort *)(param_1 + iVar7 * 0x48 + iVar11 * 0x288 + 0x1660);
  }
  else {
    iVar7 = *(int *)(param_2 + 0x58) * 4;
    piVar1 = *(int **)(iRam01714bdc + -0x7f70);
    iVar7 = (*(int *)(param_1 + iVar7 + 0x590c) + *(int *)(param_2 + 0x5c)) * 0x48 +
            *(int *)(param_1 + iVar7 + 0x58f4) * 0xf30 + *(int *)(param_2 + 0x58) * 0x1e60 + param_1
    ;
    puVar6 = (ushort *)(iVar7 + 0x1c24);
    iVar11 = (uint)*(byte *)(iVar7 + 0x1c2a) * 0xc + *(int *)(*piVar1 + 0x24) * 0x7eb8 + *piVar1;
    iVar7 = iVar11 + 0x3190 + uVar8;
    *(char *)(iVar7 + 4) = *(char *)(iVar7 + 4) + '\x01';
    if (uVar8 == 2) {
      uVar10 = *puVar6;
      if ((uVar10 < 0x150) && (uVar10 >> 8 == 1)) {
        *(undefined2 *)(iVar11 + 0x3192) =
             *(undefined2 *)
              (((uVar10 & 0xff) * 0x7a + (uint)*(byte *)(iVar11 + 0x3196)) * 4 +
               *(int *)(iVar5 + -0x7fd4) + 0xc2);
      }
      else {
        *(undefined2 *)(iVar11 + 0x3192) = 0;
      }
    }
    uVar10 = *(ushort *)(iVar11 + 0x3192);
    iVar9 = -1;
  }
  puVar6[1] = uVar10;
  *(char *)((int)puVar6 + uVar8 + 0x30) = *(char *)((int)puVar6 + uVar8 + 0x30) + '\x01';
  iVar7 = *piVar1;
  uVar4 = *(undefined4 *)(puVar6 + uVar8 * 2 + 8);
  if ((*(char *)(iVar7 + 0x20) != '\0') || (**(char **)(iVar5 + -0x7f00) != '\0')) {
    func_0x01399428(iVar7 + 8,0);
  }
  func_0x00aee00c(iVar7 + *(int *)(iVar7 + 0x24) * 0x7eb8 + 0x40,uVar4);
  if ((*(char *)(iVar7 + 0x20) != '\0') || (**(char **)(iVar5 + -0x7f00) != '\0')) {
    func_0x01399448(iVar7 + 8);
  }
  iVar7 = func_0x005f3998(*puVar6);
  uVar8 = func_0x005f3c58(param_1,puVar6);
  *(uint *)(puVar6 + 6) =
       iVar7 / 10 + ((int)uVar8 >> 2) + (uint)((int)uVar8 < 0 && (uVar8 & 3) != 0);
  func_0x00fe6c3c(param_2 + 0xa04,puVar6,0x48);
  piVar2 = *(int **)(iVar5 + -0x7fc8);
  *(undefined1 *)(param_2 + 0xa4c) = 0xff;
  if (*(char *)(*(int *)(*piVar2 + 0x182d4) + 0x2e0) != '\0') {
    *(undefined1 *)(param_1 + 0x5b24) = *(undefined1 *)(param_2 + 2);
    *(undefined1 *)(param_1 + 0x5b25) = 7;
    *(char *)(param_1 + 0x5b26) = (char)iVar9;
    if (-1 < iVar9) {
      puVar12 = (undefined2 *)(param_1 + iVar9 * 0x48 + *(char *)(param_2 + 2) * 0x288 + 0x1660);
      *(undefined2 *)(param_1 + 0x5b28) = *puVar12;
      *(undefined2 *)(param_1 + 0x5b2c) = puVar12[1];
      *(undefined1 *)(param_1 + 0x5b30) = *(undefined1 *)(puVar12 + 0x18);
      *(undefined1 *)(param_1 + 0x5b31) = *(undefined1 *)((int)puVar12 + 0x31);
      *(undefined1 *)(param_1 + 0x5b32) = *(undefined1 *)(puVar12 + 0x19);
      *(undefined1 *)(param_1 + 0x5b33) = *(undefined1 *)((int)puVar12 + 0x33);
      *(undefined1 *)(param_1 + 0x5b34) = *(undefined1 *)(puVar12 + 0x1a);
      *(undefined1 *)(param_1 + 0x5b35) = *(undefined1 *)((int)puVar12 + 0x35);
      *(undefined1 *)(param_1 + 0x5b36) = *(undefined1 *)(puVar12 + 0x1b);
      *(undefined1 *)(param_1 + 0x5b37) = *(undefined1 *)((int)puVar12 + 0x37);
    }
    puVar3 = *(undefined4 **)(iVar5 + -0x7fc4);
    *(undefined2 *)(param_1 + 0x5b2a) = *(undefined2 *)(param_2 + 0xa04);
    func_0x000fb26c(*puVar3,param_1 + 0x5b24);
  }
  *(undefined1 *)(param_1 + 0x173) = 1;
  func_0x00597b80(param_1,puVar6);
  func_0x0059606c(param_1,param_2);
  func_0x0014bc48(*piVar1);
  return;
}


