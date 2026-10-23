
void FUN_009279e4(int param_1)

{
  int *piVar1;
  int *piVar2;
  undefined4 *puVar3;
  uint uVar4;
  int iVar5;
  char cVar7;
  int iVar6;
  
  iVar5 = iRam01714e70;
  cVar7 = *(char *)(param_1 + 5);
  if (cVar7 == '\x01') {
    iVar6 = *(int *)(param_1 + 0x18);
    if (*(char *)(iVar6 + 0x38) != '\0') {
      if (*(char *)(iVar6 + 0x3a) == '\0') {
        func_0x0010f5b8(**(undefined4 **)(iRam01714e70 + -0x7f28));
        piVar1 = *(int **)(iVar5 + -0x7fc4);
        *(undefined4 *)(*(int *)(*piVar1 + 0x182d4) + 0x2ec) = 0;
        *(undefined4 *)(*(int *)(*piVar1 + 0x182d4) + 0x2e8) = 0;
        iVar6 = *(int *)(param_1 + 0x18);
        *(undefined1 *)(param_1 + 4) = 0;
        *(char *)(param_1 + 5) = *(char *)(param_1 + 5) + '\x01';
      }
      else {
        *(undefined1 *)(param_1 + 5) = 0x5a;
      }
      if (iVar6 != 0) {
        *(uint *)(iVar6 + 4) = *(uint *)(iVar6 + 4) & 0xfff7ffff;
        (*(code *)**(undefined4 **)(**(int **)(param_1 + 0x18) + 0x34))(*(int **)(param_1 + 0x18));
        *(undefined4 *)(param_1 + 0x18) = 0;
        return;
      }
    }
    return;
  }
  if (cVar7 == '\0') {
    iVar6 = **(int **)(iRam01714e70 + -0x7ef8);
    func_0x00aee8b0(iVar6 + *(int *)(iVar6 + 0x24) * 0x7eb8 + 0x40);
    FUN_00147714(iVar6);
    if ((*(int *)(param_1 + 0x14) != 0) &&
       (cVar7 = func_0x00633984(*(int *)(param_1 + 0x14)), cVar7 != '\0')) {
      return;
    }
    iVar6 = FUN_00604acc(*(undefined4 *)(iVar5 + -0x7e0c));
    *(int *)(param_1 + 0x18) = iVar6;
    if (iVar6 != 0) {
      puVar3 = *(undefined4 **)(iVar5 + -0x7fe4);
      *(uint *)(iVar6 + 4) =
           *(uint *)(iVar6 + 4) & 0xffc0ffff | *(uint *)(iVar6 + 4) & 0x3f0000 | 0x80000;
      *(undefined4 *)(*(int *)(param_1 + 0x18) + 0x120) = *(undefined4 *)(param_1 + 0x14);
      func_0x00c9a40c(*puVar3,0x1a,*(undefined4 *)(param_1 + 0x18));
      *(char *)(param_1 + 5) = *(char *)(param_1 + 5) + '\x01';
      return;
    }
  }
  else {
    if (cVar7 == '\x02') {
      iVar6 = **(int **)(iRam01714e70 + -0x7fc4);
      if ((*(uint *)(iVar6 + 0x182dc) & 1) == 0) {
        uVar4 = *(uint *)(*(int *)(iVar6 + 0x182d4) + 0x1c);
        if (uVar4 < 0xc) {
                    /* WARNING: Could not recover jumptable at 0x00927cc0. Too many branches */
                    /* WARNING: Treating indirect jump as call */
          (*(code *)(*(int *)(uVar4 * 4 + *(int *)(iRam01714e70 + -0x7e10)) +
                    *(int *)(iRam01714e70 + -0x7e10)))();
          return;
        }
      }
      else {
        iVar6 = *(int *)(*(int *)(iVar6 + 0x182d4) + 0x1c);
        if (iVar6 == 1) {
          if (0xb < *(byte *)(param_1 + 4)) {
            return;
          }
                    /* WARNING: Could not recover jumptable at 0x00924da4. Too many branches */
                    /* WARNING: Treating indirect jump as call */
          (*(code *)(*(int *)((uint)*(byte *)(param_1 + 4) * 4 + *(int *)(iRam01714e70 + -0x7e40)) +
                    *(int *)(iRam01714e70 + -0x7e40)))();
          return;
        }
        if (iVar6 == 2) {
          cVar7 = *(char *)(param_1 + 4);
          if (cVar7 == '\x01') {
            iVar6 = func_0x0091a394(param_1,1);
            if (iVar6 < 1) {
              if (iVar6 != 0) {
                func_0x00201a38(**(undefined4 **)(iVar5 + -0x7fe8),2,0);
                *(undefined1 *)(param_1 + 5) = 0;
                return;
              }
              return;
            }
          }
          else if (cVar7 == '\0') {
            piVar1 = *(int **)(iRam01714e70 + -0x7fc4);
            piVar2 = *(int **)(iRam01714e70 + -0x7ef8);
            *(undefined4 *)(*piVar1 + 0x18368) = 0;
            *(undefined4 *)(*piVar1 + 0x1836c) = 0;
            iVar6 = *piVar2;
            if ((*(char *)(iVar6 + 0x20) != '\0') || (**(char **)(iVar5 + -0x7eac) != '\0')) {
              func_0x01399428(iVar6 + 8,0);
            }
            *(undefined4 *)(iVar6 + *(int *)(iVar6 + 0x24) * 0x5940 + 0x23ce0) = 0;
            if ((*(char *)(iVar6 + 0x20) != '\0') || (**(char **)(iVar5 + -0x7eac) != '\0')) {
              func_0x01399448(iVar6 + 8);
              *(undefined1 *)(param_1 + 0x25) = 0;
              *(char *)(param_1 + 4) = *(char *)(param_1 + 4) + '\x01';
              return;
            }
          }
          else {
            if (cVar7 != '\x02') {
              if (cVar7 == '\x03') {
                func_0x009243cc();
                piVar1 = *(int **)(iVar5 + -0x7fc4);
                func_0x009c074c(*(undefined4 *)(*piVar1 + 0x182d4),1,2);
                *(uint *)(*(int *)(*piVar1 + 0x182d4) + 0x1ec) =
                     *(uint *)(*(int *)(*piVar1 + 0x182d4) + 0x1ec) | 4;
                func_0x009c08a4(*(undefined4 *)(*piVar1 + 0x182d4),1,0);
                func_0x009c08c4(*(int *)(*piVar1 + 0x182d4),1,
                                *(undefined4 *)(*(int *)(*piVar1 + 0x182d4) + 0x3b8));
                iVar5 = *(int *)(iVar5 + -0x8000);
                *(undefined1 *)(param_1 + 8) = 4;
                *(undefined4 *)(iVar5 + 0x24) = 1;
                return;
              }
              return;
            }
            iVar5 = func_0x0091a394(param_1,0);
            if (iVar5 < 1) {
              if (iVar5 != 0) {
                *(undefined1 *)(param_1 + 0x25) = 0;
                *(char *)(param_1 + 4) = *(char *)(param_1 + 4) + -1;
                return;
              }
              return;
            }
          }
          *(undefined1 *)(param_1 + 0x25) = 0;
          *(char *)(param_1 + 4) = *(char *)(param_1 + 4) + '\x01';
          return;
        }
        if (iVar6 == 0) {
          cVar7 = *(char *)(param_1 + 4);
          if (cVar7 == '\x01') {
            iVar6 = func_0x0091a394(param_1,1);
            if (0 < iVar6) {
              *(char *)(param_1 + 4) = *(char *)(param_1 + 4) + '\x01';
              return;
            }
            if (iVar6 != 0) {
              func_0x00201a38(**(undefined4 **)(iVar5 + -0x7fe8),2,0);
              *(undefined1 *)(param_1 + 5) = 0;
            }
          }
          else {
            if (cVar7 == '\0') {
              piVar1 = *(int **)(iRam01714e70 + -0x7fc4);
              piVar2 = *(int **)(iRam01714e70 + -0x7ef8);
              *(undefined4 *)(*piVar1 + 0x18368) = 0;
              *(undefined4 *)(*piVar1 + 0x1836c) = 0;
              iVar6 = *piVar2;
              if ((*(char *)(iVar6 + 0x20) != '\0') || (**(char **)(iVar5 + -0x7eac) != '\0')) {
                func_0x01399428(iVar6 + 8,0);
              }
              *(undefined4 *)(iVar6 + *(int *)(iVar6 + 0x24) * 0x5940 + 0x23ce0) = 0;
              if ((*(char *)(iVar6 + 0x20) == '\0') && (**(char **)(iVar5 + -0x7eac) == '\0')) {
                *(undefined1 *)(param_1 + 0x25) = 0;
                *(char *)(param_1 + 4) = *(char *)(param_1 + 4) + '\x01';
              }
              else {
                func_0x01399448(iVar6 + 8);
                *(undefined1 *)(param_1 + 0x25) = 0;
                *(char *)(param_1 + 4) = *(char *)(param_1 + 4) + '\x01';
              }
              return;
            }
            if (cVar7 == '\x02') {
              func_0x009243cc();
              func_0x009c074c(*(undefined4 *)(**(int **)(iVar5 + -0x7fc4) + 0x182d4),1,2);
              iVar5 = *(int *)(iVar5 + -0x8000);
              *(undefined1 *)(param_1 + 8) = 4;
              *(undefined4 *)(iVar5 + 0x24) = 1;
              return;
            }
          }
          return;
        }
      }
      *(undefined1 *)(param_1 + 5) = 0x5a;
      return;
    }
    if (cVar7 != 'Z') {
      return;
    }
    *(undefined4 *)(*(int *)(**(int **)(iRam01714e70 + -0x7fc4) + 0x182d4) + 0x1c) = 0;
  }
  *(char *)(param_1 + 6) = *(char *)(param_1 + 6) + '\x01';
  return;
}


