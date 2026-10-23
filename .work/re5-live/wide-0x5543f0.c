
void FUN_005543f0(void)

{
  bool bVar1;
  uint uVar2;
  byte bVar4;
  char *pcVar3;
  undefined4 unaff_r14;
  undefined4 unaff_r15;
  uint unaff_r16;
  undefined8 unaff_r17;
  char *unaff_r18;
  char unaff_r19;
  int unaff_r20;
  int *unaff_r21;
  int *unaff_r22;
  uint unaff_r23;
  uint unaff_r24;
  int unaff_r25;
  undefined4 unaff_r26;
  int iVar5;
  int iVar6;
  int unaff_r29;
  int unaff_r30;
  undefined4 in_stack_00000090;
  
  do {
    func_0x0014723c(*unaff_r21,0x41);
    if (*(int *)(unaff_r29 + 0x6c) == 0) {
      func_0x0014723c(*unaff_r21,0x42);
    }
    if (*(int *)(unaff_r25 + 0x180) == 3) {
      func_0x0014723c(*unaff_r21,0x43);
    }
LAB_00554364:
    if ((*(int *)(unaff_r25 + 0x308) >> (unaff_r23 & 0x3f) & 1U) != 0) {
      bVar4 = func_0x009c199c(*(undefined4 *)(*unaff_r22 + 0x182d4));
      pcVar3 = (char *)func_0x00aecff0(*unaff_r21 + *(int *)(*unaff_r21 + 0x24) * 0x7eb8 + 0x40,
                                       unaff_r26,bVar4 ^ 1,*(undefined4 *)(unaff_r25 + 0x180));
      if ((*pcVar3 == '\0') || (*(uint *)(pcVar3 + 4) < *(uint *)(unaff_r29 + 0x54))) {
        *pcVar3 = '\x01';
        *(undefined4 *)(pcVar3 + 4) = *(undefined4 *)(unaff_r29 + 0x54);
      }
    }
    FUN_001426f0(*unaff_r21);
    do {
      bVar1 = unaff_r24 == 1;
      unaff_r20 = unaff_r20 + 4;
      unaff_r24 = unaff_r24 + 1;
      if (bVar1) {
        return;
      }
      func_0x009c0ce0(*(undefined4 *)(*unaff_r22 + 0x182d4),unaff_r24);
    } while (((*(int *)(*(int *)(*unaff_r22 + 0x182d4) + 0x1e8) >> (unaff_r24 & 0x3f) & 1U) == 0) ||
            (unaff_r23 = *(uint *)(*(int *)(*unaff_r22 + 0x182d4) + unaff_r20), (int)unaff_r23 < 0))
    ;
    unaff_r21 = *(int **)(unaff_r30 + -0x7ebc);
    FUN_001426ec(*unaff_r21,unaff_r23);
    uVar2 = func_0x00aecc88(*unaff_r21 + *(int *)(*unaff_r21 + 0x24) * 0x7eb8 + 0x40,unaff_r17);
    if (uVar2 == 0) {
      func_0x009c0d08(*(undefined4 *)(*unaff_r22 + 0x182d4),unaff_r24,unaff_r14);
      func_0x009c0d08(*(undefined4 *)(*unaff_r22 + 0x182d4),unaff_r24,unaff_r15);
      iVar6 = *(int *)(unaff_r25 + 0x180);
      if (1 < iVar6) goto LAB_00554220;
LAB_0055422c:
      iVar5 = *unaff_r21;
      if (*(char *)(iVar5 + 0x20) != '\0') goto LAB_0055424c;
LAB_00554240:
      if (*unaff_r18 != '\0') goto LAB_0055424c;
    }
    else {
      iVar6 = *(int *)(unaff_r25 + 0x180);
      if (iVar6 < 2) goto LAB_0055422c;
LAB_00554220:
      if ((uVar2 & 0xc) != 0) goto LAB_0055422c;
      func_0x009c0d08(*(undefined4 *)(**(int **)(unaff_r30 + -0x7ffc) + 0x182d4),unaff_r24,
                      in_stack_00000090);
      iVar5 = *unaff_r21;
      iVar6 = *(int *)(unaff_r25 + 0x180);
      if (*(char *)(iVar5 + 0x20) == '\0') goto LAB_00554240;
LAB_0055424c:
      func_0x01399428(iVar5 + 8,0);
    }
    func_0x00aeccc0(iVar5 + *(int *)(iVar5 + 0x24) * 0x7eb8 + 0x40,unaff_r17,iVar6);
    if ((*(char *)(iVar5 + 0x20) != '\0') || (*unaff_r18 != '\0')) {
      func_0x01399448(iVar5 + 8);
    }
    iVar6 = *unaff_r21;
    if ((*(char *)(iVar6 + 0x20) != '\0') || (*unaff_r18 != '\0')) {
      func_0x01399428(iVar6 + 8,0);
    }
    iVar5 = iVar6 + *(int *)(iVar6 + 0x24) * 0x7eb8 + 0x40;
    *(uint *)(iVar5 + 0x3f34) = *(uint *)(iVar5 + 0x3f34) | unaff_r16;
    if ((*(char *)(iVar6 + 0x20) != '\0') || (*unaff_r18 != '\0')) {
      func_0x01399448(iVar6 + 8);
    }
  } while (unaff_r19 == '\0');
  func_0x0014723c(*unaff_r21,0x3c);
  if (*(int *)(unaff_r29 + 0x6c) == 0) {
    func_0x0014723c(*unaff_r21,0x3d);
  }
  if (*(int *)(unaff_r25 + 0x180) == 3) {
    func_0x0014723c(*unaff_r21,0x3e);
  }
  goto LAB_00554364;
}


