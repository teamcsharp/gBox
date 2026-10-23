
void FUN_00620b74(void)

{
  int *piVar1;
  int iVar2;
  undefined4 uVar3;
  undefined4 unaff_r24;
  int unaff_r25;
  undefined1 unaff_r26;
  int unaff_r30;
  undefined8 unaff_r31;
  
  piVar1 = *(int **)(unaff_r30 + -0x7ff4);
  iVar2 = *piVar1;
  iVar2 = *(int *)(iVar2 + *(int *)(iVar2 + 0x24) * 0x7eb8 + 0x7c);
  func_0x00550c9c(unaff_r25,*(undefined4 *)(unaff_r30 + -0x7ff0),unaff_r26);
  func_0x0054d264(unaff_r25,*(undefined4 *)(unaff_r30 + -0x7fec));
  func_0x0054d264(unaff_r25,*(undefined4 *)(unaff_r30 + -0x7fe8));
  uVar3 = *(undefined4 *)(*(int *)(unaff_r30 + -0x7fe4) + iVar2 * 4);
  func_0x00fe6bbc(&stack0x00000088,*(undefined4 *)(unaff_r30 + -0x7fe0),uVar3);
  func_0x0054d264(unaff_r25,&stack0x00000088);
  func_0x0054d264(unaff_r25,*(undefined4 *)(unaff_r30 + -0x7fdc));
  func_0x0054d264(unaff_r25,*(undefined4 *)(unaff_r30 + -0x7fd8));
  func_0x0054d264(unaff_r25,*(undefined4 *)(unaff_r30 + -0x7fd4));
  func_0x00550c9c(unaff_r25,*(undefined4 *)(unaff_r30 + -0x7fd0),unaff_r26);
  func_0x0054d264(unaff_r25,*(undefined4 *)(unaff_r30 + -0x7fcc));
  func_0x0054d264(unaff_r25,*(undefined4 *)(unaff_r30 + -0x7fc8));
  func_0x00fe6bbc(&stack0x00000088,*(undefined4 *)(unaff_r30 + -0x7fc4),uVar3);
  func_0x0054d264(unaff_r25,&stack0x00000088);
  func_0x0054d264(unaff_r25,*(undefined4 *)(unaff_r30 + -0x7fc0));
  func_0x0054d264(unaff_r25,*(undefined4 *)(unaff_r30 + -0x7fbc));
  func_0x0054d264(unaff_r25,*(undefined4 *)(unaff_r30 + -0x7fb8));
  if (*(int *)(unaff_r25 + 0x174) == 0) {
    iVar2 = *piVar1;
    if (*(int *)(iVar2 + *(int *)(iVar2 + 0x24) * 0x5940 + 0x23cd4) == 0) {
      func_0x0054d264(unaff_r25,*(undefined4 *)(unaff_r30 + -0x7fb4));
      uVar3 = 0x20c;
    }
    else {
      func_0x0054f88c(unaff_r25,*(undefined4 *)(unaff_r30 + -0x7fb4),0,0xfffffffffffffeaa);
      uVar3 = 0xa4;
    }
    func_0x0054d9e0(unaff_r24,0x24,0x280,uVar3,&stack0x00000080,0x749,0x60,0xffffffffffffffff);
    func_0x005bd24c(unaff_r31,10,0xffffffffffffffff);
    return;
  }
  return;
}


