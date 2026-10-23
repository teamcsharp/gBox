
uint FUN_00c26654(undefined4 param_1,int *param_2)

{
  int iVar1;
  char cVar3;
  uint uVar2;
  undefined1 auStack_370 [840];
  
  iVar1 = iRam01715464;
  uVar2 = 0;
  cVar3 = (*(code *)**(undefined4 **)(*param_2 + 0x18))(param_2);
  if (cVar3 != '\0') {
    func_0x00b635f4(auStack_370);
    uVar2 = func_0x00b6490c(auStack_370,param_2,*(undefined4 *)(iVar1 + -0x7fd8),param_1,1);
    uVar2 = (((int)uVar2 >> 0x1f ^ uVar2) - ((int)uVar2 >> 0x1f)) - 1 >> 0x1f ^ 1;
    func_0x00b635fc(auStack_370);
  }
  return uVar2;
}


