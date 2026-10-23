
void FUN_001465ac(int param_1,uint param_2)

{
  undefined1 uVar1;
  int iVar2;
  char *pcVar3;
  undefined1 *puVar4;
  int iVar5;
  
  iVar2 = **(int **)(iRam0171482c + -0x7fd4);
  if (0 < iVar2) {
    pcVar3 = *(char **)(iRam0171482c + -0x7f50);
    iVar5 = 0;
    puVar4 = *(undefined1 **)(iRam0171482c + -0x7fd0);
    do {
      while( true ) {
        iVar5 = iVar5 + 1;
        if ((byte)puVar4[1] == param_2) break;
LAB_00146614:
        puVar4 = puVar4 + 8;
        if (iVar2 == iVar5) {
          return;
        }
      }
      uVar1 = *puVar4;
      if ((*(char *)(param_1 + 0x20) != '\0') || (*pcVar3 != '\0')) {
        func_0x01399428(param_1 + 8,0);
      }
      func_0x00aec74c(param_1 + *(int *)(param_1 + 0x24) * 0x7eb8 + 0x40,uVar1);
      if ((*(char *)(param_1 + 0x20) == '\0') && (*pcVar3 == '\0')) goto LAB_00146614;
      func_0x01399448(param_1 + 8);
      puVar4 = puVar4 + 8;
    } while (iVar2 != iVar5);
  }
  return;
}


