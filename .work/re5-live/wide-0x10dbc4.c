
void FUN_0010dbc4(void)

{
  bool bVar1;
  uint uVar2;
  uint uVar3;
  char cVar5;
  char *pcVar4;
  undefined1 unaff_r14;
  int unaff_r15;
  int unaff_r16;
  int *unaff_r17;
  int *unaff_r20;
  int unaff_r21;
  int unaff_r22;
  int unaff_r23;
  int unaff_r25;
  int unaff_r26;
  ulonglong uVar6;
  int unaff_r29;
  int iVar7;
  int *piVar8;
  int unaff_r30;
  
  do {
    FUN_001426ec(*unaff_r17,unaff_r29);
    uVar2 = *(uint *)(unaff_r21 + 0x10790);
    uVar3 = *(uint *)(unaff_r21 + 0x10794);
    if (uVar2 < 4) {
      if (uVar3 < 6) {
        uVar6 = 0;
        iVar7 = 0;
        do {
          pcVar4 = (char *)func_0x00142884(*unaff_r17,iVar7);
          if ((int)*pcVar4 == uVar3) {
            pcVar4 = (char *)func_0x00aeceb4(*unaff_r17 +
                                             *(int *)(*unaff_r17 + 0x24) * 0x7eb8 + 0x40,uVar2,iVar7
                                            );
            if (*pcVar4 == '\0') goto LAB_0010dd98;
            uVar6 = uVar6 + *(uint *)(pcVar4 + 4);
          }
          bVar1 = iVar7 != 0xf;
          iVar7 = iVar7 + 1;
        } while (bVar1);
        if (*(int *)(unaff_r21 + 0x10798) < 5) {
          piVar8 = (int *)(unaff_r22 + *(int *)(unaff_r21 + 0x10798) * 0x170 + 0x10800);
          func_0x00ef4280(piVar8);
          piVar8[1] = unaff_r16;
          *piVar8 = uVar3 + uVar2 * 7;
          (*(code *)**(undefined4 **)(**(int **)(unaff_r23 + 0x40) + 0x20))
                    (*(int **)(unaff_r23 + 0x40),piVar8 + 2);
          piVar8[0x18] = unaff_r15;
          *(ulonglong *)(piVar8 + 0x16) = ~uVar6;
          *(undefined1 *)(piVar8 + 0x1a) = unaff_r14;
          iVar7 = *(int *)(unaff_r23 + 0x19a8);
          *(ulonglong *)(piVar8 + 0x20) = uVar6;
          piVar8[0x1c] = iVar7;
          *(undefined1 *)(piVar8 + 0x1e) = 4;
          *(int *)(unaff_r21 + 0x10798) = *(int *)(unaff_r21 + 0x10798) + 1;
        }
LAB_0010dd98:
        uVar2 = *(uint *)(unaff_r21 + 0x10790);
        if (3 < uVar2) goto LAB_0010dc60;
      }
      uVar6 = 0;
      iVar7 = 0;
      do {
        pcVar4 = (char *)func_0x00aeceb4(*unaff_r17 + *(int *)(*unaff_r17 + 0x24) * 0x7eb8 + 0x40,
                                         uVar2,iVar7);
        bVar1 = iVar7 != 0xf;
        iVar7 = iVar7 + 1;
        if (*pcVar4 == '\0') goto LAB_0010dc60;
        uVar6 = uVar6 + *(uint *)(pcVar4 + 4);
      } while (bVar1);
      if (*(int *)(unaff_r21 + 0x10798) < 5) {
        piVar8 = (int *)(unaff_r22 + *(int *)(unaff_r21 + 0x10798) * 0x170 + 0x10800);
        func_0x00ef4280(piVar8);
        piVar8[1] = unaff_r16;
        *piVar8 = uVar2 * 7 + 6;
        (*(code *)**(undefined4 **)(**(int **)(unaff_r23 + 0x40) + 0x20))
                  (*(int **)(unaff_r23 + 0x40),piVar8 + 2);
        piVar8[0x18] = unaff_r15;
        *(ulonglong *)(piVar8 + 0x16) = ~uVar6;
        *(undefined1 *)(piVar8 + 0x1a) = unaff_r14;
        iVar7 = *(int *)(unaff_r23 + 0x19a8);
        *(ulonglong *)(piVar8 + 0x20) = uVar6;
        piVar8[0x1c] = iVar7;
        *(undefined1 *)(piVar8 + 0x1e) = 4;
        *(int *)(unaff_r21 + 0x10798) = *(int *)(unaff_r21 + 0x10798) + 1;
      }
    }
LAB_0010dc60:
    FUN_001426f0(*unaff_r17);
    do {
      bVar1 = unaff_r25 == 1;
      unaff_r26 = unaff_r26 + 4;
      unaff_r25 = unaff_r25 + 1;
      if (bVar1) {
        return;
      }
      unaff_r29 = *(int *)(*(int *)(*unaff_r20 + 0x182d4) + unaff_r26);
    } while ((unaff_r29 < 0) ||
            (cVar5 = func_0x00201950(**(undefined4 **)(unaff_r30 + -0x7f94),unaff_r29),
            cVar5 == '\0'));
  } while( true );
}


