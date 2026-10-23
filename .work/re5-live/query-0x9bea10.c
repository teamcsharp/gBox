
void FUN_009bea10(void)

{
  undefined4 *puVar1;
  int unaff_r30;
  byte in_cr1;
  
  if ((bool)(in_cr1 >> 1 & 1)) {
    puVar1 = *(undefined4 **)(unaff_r30 + -0x8000);
    func_0x00b3002c(puVar1,*(undefined4 *)(unaff_r30 + -0x7fd8),*(undefined4 *)(unaff_r30 + -0x7fd4)
                    ,0x5940,0,0);
    *puVar1 = *(undefined4 *)(unaff_r30 + -0x7fd0);
  }
  return;
}


