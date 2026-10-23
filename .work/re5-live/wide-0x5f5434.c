
void FUN_005f5434(undefined8 param_1,uint param_2)

{
  char cVar1;
  int iVar2;
  int iVar3;
  int unaff_r30;
  int unaff_r31;
  
  if (param_2 < 0x1200) {
    iVar2 = **(int **)(unaff_r30 + -0x7ffc);
    if ((*(char *)(iVar2 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f8c) != '\0')) {
      func_0x01399428(iVar2 + 8,0);
    }
    iVar3 = iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0x40;
    *(uint *)(iVar3 + 0x70) = *(uint *)(iVar3 + 0x70) | 1 << (unaff_r31 - 0x10ffU & 0x3f);
    cVar1 = *(char *)(iVar2 + 0x20);
  }
  else if (param_2 < 0x1300) {
    iVar2 = **(int **)(unaff_r30 + -0x7ffc);
    if ((*(char *)(iVar2 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f8c) != '\0')) {
      func_0x01399428(iVar2 + 8,0);
    }
    iVar3 = iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0x40;
    *(uint *)(iVar3 + 0x74) = *(uint *)(iVar3 + 0x74) | 1 << (unaff_r31 - 0x1200U & 0x3f);
    cVar1 = *(char *)(iVar2 + 0x20);
  }
  else {
    if (param_2 < 0x1400) {
      iVar2 = **(int **)(unaff_r30 + -0x7ffc);
      cVar1 = *(char *)(param_2 + *(int *)(unaff_r30 + -0x7ff4) + -0x12d8);
      if ((*(char *)(iVar2 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f8c) != '\0')) {
        func_0x01399428(iVar2 + 8,0);
      }
      iVar3 = iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0x40;
      *(ushort *)(iVar3 + 0xc4) = (ushort)(1 << ((int)cVar1 & 0x3fU)) | *(ushort *)(iVar3 + 0xc4);
      if ((*(char *)(iVar2 + 0x20) == '\0') && (**(char **)(unaff_r30 + -0x7f8c) == '\0')) {
        return;
      }
      func_0x01399448(iVar2 + 8);
      return;
    }
    if (param_2 < 0x1500) {
      iVar2 = **(int **)(unaff_r30 + -0x7ffc);
      if ((*(char *)(iVar2 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f8c) != '\0')) {
        func_0x01399428(iVar2 + 8,0);
      }
      func_0x00aec714(iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0x40,unaff_r31 + -0x1400);
      cVar1 = *(char *)(iVar2 + 0x20);
    }
    else {
      if (0x15ff < param_2) {
        return;
      }
      iVar2 = **(int **)(unaff_r30 + -0x7ffc);
      if ((*(char *)(iVar2 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7f8c) != '\0')) {
        func_0x01399428(iVar2 + 8,0);
      }
      func_0x00aec74c(iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0x40,unaff_r31 + -0x1500);
      cVar1 = *(char *)(iVar2 + 0x20);
    }
  }
  if ((cVar1 == '\0') && (**(char **)(unaff_r30 + -0x7f8c) == '\0')) {
    return;
  }
  func_0x01399448(iVar2 + 8);
  return;
}


