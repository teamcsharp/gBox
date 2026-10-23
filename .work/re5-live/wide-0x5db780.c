
void FUN_005db780(void)

{
  int iVar1;
  undefined4 unaff_r28;
  int unaff_r30;
  
  iVar1 = **(int **)(unaff_r30 + -0x7ffc);
  if ((*(char *)(iVar1 + 0x20) != '\0') || (**(char **)(unaff_r30 + -0x7fc8) != '\0')) {
    func_0x01399428(iVar1 + 8,0);
  }
  *(undefined4 *)(iVar1 + *(int *)(iVar1 + 0x24) * 0x7eb8 + 0x6c) = unaff_r28;
  if ((*(char *)(iVar1 + 0x20) == '\0') && (**(char **)(unaff_r30 + -0x7fc8) == '\0')) {
    return;
  }
  func_0x01399448(iVar1 + 8);
  return;
}


