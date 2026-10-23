
void FUN_000e426c(int param_1)

{
  undefined1 uVar1;
  undefined1 uVar2;
  undefined1 uVar3;
  undefined4 uVar4;
  float fVar5;
  int *piVar6;
  undefined1 *puVar7;
  undefined4 uVar8;
  int *piVar9;
  int iVar10;
  int iVar11;
  undefined4 *puVar12;
  int *piVar13;
  undefined4 *puVar14;
  undefined4 uVar15;
  int iVar16;
  undefined4 *puVar17;
  undefined4 *puVar18;
  undefined4 *puVar19;
  undefined4 *puVar20;
  char cVar22;
  undefined4 *puVar21;
  int *piVar23;
  double dVar24;
  double dVar25;
  undefined1 auStack_290 [4];
  undefined1 auStack_28c [8];
  undefined1 auStack_284 [36];
  undefined1 auStack_260 [36];
  undefined1 auStack_23c [36];
  undefined1 auStack_218 [36];
  undefined1 auStack_1f4 [36];
  undefined1 auStack_1d0 [40];
  undefined1 auStack_1a8 [264];
  
  iVar10 = iRam017147e8;
  func_0x00b5fba8(*(undefined4 *)(iRam017147e8 + -0x7d88));
  func_0x000dc0ac(param_1);
  func_0x00c26e64(param_1);
  *(undefined4 *)(param_1 + 0x182e0) = 0;
  *(undefined4 *)(param_1 + 0x182dc) = 0;
  if ((*(char *)(param_1 + 0x20) != '\0') || (**(char **)(iVar10 + -0x7e9c) != '\0')) {
    func_0x01399428(param_1 + 8,0);
  }
  *(undefined4 *)(param_1 + 0x182f0) = 0;
  *(undefined4 *)(param_1 + 0x182e4) = 0;
  *(undefined4 *)(param_1 + 0x182e8) = 0;
  *(undefined4 *)(param_1 + 0x182ec) = 0;
  if ((*(char *)(param_1 + 0x20) == '\0') && (**(char **)(iVar10 + -0x7e9c) == '\0')) {
LAB_000e4360:
    *(undefined4 *)(param_1 + 0x18300) = 0;
    *(undefined4 *)(param_1 + 0x182f4) = 0;
    *(undefined4 *)(param_1 + 0x182f8) = 0;
    *(undefined4 *)(param_1 + 0x182fc) = 0;
    if (*(char *)(param_1 + 0x20) != '\0') goto LAB_000e8520;
LAB_000e4384:
    if (**(char **)(iVar10 + -0x7e9c) != '\0') goto LAB_000e8520;
  }
  else {
    func_0x01399448(param_1 + 8);
    if ((*(char *)(param_1 + 0x20) == '\0') && (**(char **)(iVar10 + -0x7e9c) == '\0'))
    goto LAB_000e4360;
    func_0x01399428(param_1 + 8,0);
    *(undefined4 *)(param_1 + 0x18300) = 0;
    *(undefined4 *)(param_1 + 0x182f4) = 0;
    *(undefined4 *)(param_1 + 0x182f8) = 0;
    *(undefined4 *)(param_1 + 0x182fc) = 0;
    if (*(char *)(param_1 + 0x20) == '\0') goto LAB_000e4384;
LAB_000e8520:
    func_0x01399448(param_1 + 8);
    if ((*(char *)(param_1 + 0x20) != '\0') || (**(char **)(iVar10 + -0x7e9c) != '\0')) {
      func_0x01399428(param_1 + 8,0);
    }
  }
  *(undefined4 *)(param_1 + 0x18310) = 0;
  *(undefined4 *)(param_1 + 0x18304) = 0;
  *(undefined4 *)(param_1 + 0x18308) = 0;
  *(undefined4 *)(param_1 + 0x1830c) = 0;
  if ((*(char *)(param_1 + 0x20) != '\0') || (**(char **)(iVar10 + -0x7e9c) != '\0')) {
    func_0x01399448(param_1 + 8);
  }
  puVar14 = *(undefined4 **)(iVar10 + -0x7fe0);
  *(undefined1 *)(param_1 + 0x18372) = 0;
  *(undefined4 *)(param_1 + 0x182cc) = 0;
  *(undefined1 *)(param_1 + 0x182d0) = 0;
  *(undefined1 *)(param_1 + 0x182d1) = 0;
  *(undefined1 *)(param_1 + 0x182d3) = 0;
  *(undefined1 *)(param_1 + 0x18370) = 0;
  *(undefined1 *)(param_1 + 0x18371) = 0;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x70,0x10);
  if (iVar11 != 0) {
    func_0x00b21070(iVar11,*(undefined4 *)(iVar10 + -0x7d84));
  }
  *(int *)(param_1 + 0x1822c) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x4f8,0x10);
  if (iVar11 != 0) {
    func_0x00b24a78(iVar11);
  }
  *(int *)(param_1 + 0x18230) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x900,0x10);
  if (iVar11 != 0) {
    func_0x00b28ee0(iVar11);
  }
  *(int *)(param_1 + 0x18228) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x221a8,0x10);
  if (iVar11 != 0) {
    func_0x00c621c8(iVar11,0x100000);
  }
  *(int *)(param_1 + 0x181e0) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x82e80,0x10);
  if (iVar11 != 0) {
    func_0x00116eac(iVar11,0,0x1402,0x700000,0x400000,0x200000,0x80000,0xa00000);
  }
  *(int *)(param_1 + 0x181d4) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x3200,0x10);
  if (iVar11 != 0) {
    func_0x000c2190(iVar11);
  }
  *(int *)(param_1 + 0x181e4) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x17900,0x10);
  if (iVar11 != 0) {
    func_0x00119aa0(iVar11);
  }
  *(int *)(param_1 + 0x181fc) = iVar11;
  puVar12 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x19a0,0x10);
  if (puVar12 != (undefined4 *)0x0) {
    func_0x00c94ea8(puVar12);
    *puVar12 = *(undefined4 *)(iVar10 + -0x7ecc);
  }
  *(undefined4 **)(param_1 + 0x181d8) = puVar12;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x21a0,0x10);
  if (iVar11 != 0) {
    func_0x00111f98(iVar11);
  }
  *(int *)(param_1 + 0x181e8) = iVar11;
  (*(code *)**(undefined4 **)(**(int **)(param_1 + 0x181fc) + 0x34))(*(int **)(param_1 + 0x181fc));
  func_0x00b6d80c(*(undefined4 *)(iVar10 + -0x7d80));
  func_0x00b6d824(*(undefined4 *)(iVar10 + -0x7d7c));
  func_0x00b6d83c(*(undefined4 *)(iVar10 + -0x7d78));
  func_0x00b6d854(*(undefined4 *)(iVar10 + -0x7d74));
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x4f30,0x10);
  if (iVar11 != 0) {
    func_0x00c35088(iVar11,0x10000);
  }
  *(int *)(param_1 + 0x181ec) = iVar11;
  *(undefined4 *)(iVar11 + 0x60) = 0;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x2f40,0x10);
  if (iVar11 != 0) {
    func_0x000c5c44(iVar11);
  }
  *(int *)(param_1 + 0x181f4) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x4070,0x10);
  if (iVar11 != 0) {
    func_0x000d9978(iVar11);
  }
  *(int *)(param_1 + 0x181f8) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x3b1e0,0x10);
  if (iVar11 != 0) {
    func_0x00c8c1a0(iVar11);
  }
  *(int *)(param_1 + 0x18200) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x630,0x10);
  if (iVar11 != 0) {
    func_0x0011e138(iVar11);
  }
  *(int *)(param_1 + 0x1823c) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x28,0x10);
  if (iVar11 != 0) {
    func_0x0011fff4(iVar11);
  }
  *(int *)(param_1 + 0x18240) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x8c0,0x10);
  if (iVar11 != 0) {
    func_0x0012749c(iVar11);
  }
  *(int *)(param_1 + 0x18224) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x38,0x10);
  if (iVar11 != 0) {
    func_0x0013db9c(iVar11);
  }
  *(int *)(param_1 + 0x18238) = iVar11;
  func_0x0013db3c(iVar11);
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x98,0x10);
  if (iVar11 != 0) {
    func_0x00be7f08(iVar11);
  }
  *(int *)(param_1 + 0x18204) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x3850,0x10);
  if (iVar11 != 0) {
    func_0x000bc1e4(iVar11);
  }
  *(int *)(param_1 + 0x18208) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x4640,0x10);
  if (iVar11 != 0) {
    func_0x0017e594(iVar11);
  }
  puVar12 = *(undefined4 **)(iVar10 + -0x7fd8);
  *(int *)(param_1 + 0x18248) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x1b8,0x10);
  if (iVar11 != 0) {
    func_0x00159cf4(iVar11);
  }
  *(int *)(param_1 + 0x1824c) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x28,0x10);
  if (iVar11 != 0) {
    func_0x000b94c4(iVar11);
  }
  *(int *)(param_1 + 0x18218) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x70,0x10);
  if (iVar11 != 0) {
    func_0x00c229c0(iVar11,0x2000,0x2000);
  }
  *(int *)(param_1 + 0x1820c) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x308c8,0x10);
  if (iVar11 != 0) {
    func_0x0017a06c(iVar11);
  }
  *(int *)(param_1 + 0x1828c) = iVar11;
  puVar12 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x568,0x10);
  if (puVar12 != (undefined4 *)0x0) {
    func_0x00c99bd8(puVar12);
    *puVar12 = *(undefined4 *)(iVar10 + -0x7d70);
  }
  *(undefined4 **)(param_1 + 0x181dc) = puVar12;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x2a0,0x10);
  if (iVar11 != 0) {
    func_0x000d13ac(iVar11);
  }
  *(int *)(param_1 + 0x18210) = iVar11;
  func_0x000c818c(iVar11);
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x5c0,0x10);
  if (iVar11 != 0) {
    func_0x001924c8(iVar11);
  }
  *(int *)(param_1 + 0x18260) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x5f0,0x10);
  if (iVar11 != 0) {
    func_0x001a9500(iVar11);
  }
  *(int *)(param_1 + 0x18264) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x128,0x10);
  if (iVar11 != 0) {
    func_0x00137c44(iVar11);
  }
  *(int *)(param_1 + 0x18268) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x108,0x10);
  if (iVar11 != 0) {
    func_0x0018b06c(iVar11);
  }
  *(int *)(param_1 + 0x1826c) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x38,0x10);
  if (iVar11 != 0) {
    func_0x00203238(iVar11);
  }
  *(int *)(param_1 + 0x18244) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x1050,0x10);
  if (iVar11 != 0) {
    func_0x000ba900(iVar11);
  }
  *(int *)(param_1 + 0x18254) = iVar11;
  func_0x000baffc(iVar11);
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0xd10,0x10);
  if (iVar11 != 0) {
    func_0x000b8eb0(iVar11);
  }
  *(int *)(param_1 + 0x18258) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x3e0,0x10);
  if (iVar11 != 0) {
    func_0x0014cee0(iVar11);
  }
  *(int *)(param_1 + 0x18270) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0xa0,0x10);
  if (iVar11 != 0) {
    func_0x00201230(iVar11);
  }
  *(int *)(param_1 + 0x18274) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x100,0x10);
  if (iVar11 != 0) {
    func_0x001fde9c(iVar11);
  }
  *(int *)(param_1 + 0x1825c) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x38,0x10);
  if (iVar11 != 0) {
    func_0x001290e4(iVar11);
  }
  *(int *)(param_1 + 0x18278) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x13d0,0x10);
  if (iVar11 != 0) {
    func_0x00162530(iVar11);
  }
  *(int *)(param_1 + 0x1827c) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x158,0x10);
  if (iVar11 != 0) {
    func_0x0013c660(iVar11);
  }
  *(int *)(param_1 + 0x18250) = iVar11;
  piVar13 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,70000,0x10)
  ;
  if (piVar13 != (int *)0x0) {
    func_0x000d5928(piVar13);
  }
  *(int **)(param_1 + 0x18280) = piVar13;
  (*(code *)**(undefined4 **)(*piVar13 + 0x28))(piVar13);
  piVar13 = (int *)(*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))
                             ((int *)*puVar14,0x26948,0x10);
  if (piVar13 != (int *)0x0) {
    func_0x0010f7e4(piVar13);
  }
  *(int **)(param_1 + 0x18284) = piVar13;
  (*(code *)**(undefined4 **)(*piVar13 + 0x24))(piVar13);
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x5920,0x10);
  if (iVar11 != 0) {
    func_0x00125ac0(iVar11);
  }
  *(int *)(param_1 + 0x18288) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0xb20,0x10);
  if (iVar11 != 0) {
    func_0x00141700(iVar11);
  }
  *(int *)(param_1 + 0x18294) = iVar11;
  func_0x00c75194(*(undefined4 *)(param_1 + 0x18200),0x411);
  func_0x00c89448(*(undefined4 *)(param_1 + 0x18200),0x73);
  if (*(int *)(param_1 + 0x1820c) != 0) {
    func_0x00c220d8(*(int *)(param_1 + 0x1820c),0,0x8000);
  }
  func_0x00e49af0();
  func_0x00bb4288();
  func_0x00de7dd0();
  func_0x00de7dc8();
  func_0x00de7dd4();
  func_0x00de7dd8();
  func_0x00de7de0();
  func_0x00ddc1e0();
  func_0x00e61ab8();
  func_0x00e61abc();
  func_0x00e61ac0();
  func_0x00e68c9c();
  func_0x00df54f0();
  func_0x00e2e2e8();
  func_0x00df22b0();
  func_0x00d974a8();
  func_0x00ddc8f8();
  func_0x00e306b0();
  func_0x00e4db58();
  func_0x00e26c6c();
  func_0x00d91e90();
  func_0x00e4d380();
  func_0x00dda920();
  func_0x00b94950();
  func_0x00ca23d0();
  func_0x00bac260();
  func_0x00bb1810();
  func_0x00cb54d8();
  func_0x00caa840();
  func_0x00dd7948();
  func_0x00e67478();
  func_0x00dd0e70();
  func_0x00e3fae0();
  func_0x00e3c728();
  func_0x00e39c08();
  func_0x00e67478();
  func_0x00b9f2f8();
  func_0x00bc52d0();
  func_0x00bbdb1c();
  func_0x00bc1b80();
  func_0x00bcf380();
  func_0x00bb6590();
  func_0x00bba64c();
  func_0x00bbbd50();
  func_0x00248ec8();
  func_0x0024b7cc();
  func_0x0024ec40();
  iVar11 = func_0x00b30fe4(0x500);
  if (iVar11 != 0) {
    func_0x009c06ac(iVar11);
  }
  *(int *)(param_1 + 0x182d4) = iVar11;
  iVar11 = func_0x00b30fe4(0xe0);
  if (iVar11 != 0) {
    func_0x00ade24c(iVar11);
  }
  *(int *)(param_1 + 0x182d8) = iVar11;
  iVar11 = (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x36060,0x10);
  if (iVar11 != 0) {
    func_0x00148918(iVar11);
  }
  *(int *)(param_1 + 0x18290) = iVar11;
  func_0x00c25ac0(param_1,0);
  func_0x00c25a90(param_1,*(undefined4 *)(iVar10 + -0x7e94));
  func_0x00b7f678(param_1 + 0x182d2,0x55c030);
  piVar13 = *(int **)(iVar10 + -0x7d6c);
  *(undefined4 *)(param_1 + 0x18358) = 0;
  *(undefined4 *)(param_1 + 0x1835c) = 0;
  *(undefined1 *)(param_1 + 0x18360) = 0;
  *(undefined4 *)(param_1 + 0x18364) = 0;
  *(undefined4 *)(param_1 + 0x18344) = 0;
  *(undefined1 *)(param_1 + 0x18340) = 0;
  *(undefined1 *)(param_1 + 0x18341) = 0;
  *(undefined4 *)(param_1 + 0x18334) = 0;
  *(undefined4 *)(param_1 + 0x18348) = 0;
  *(undefined4 *)(param_1 + 0x1834c) = 0;
  *(undefined4 *)(param_1 + 0x18350) = 0;
  *(undefined4 *)(param_1 + 0x18354) = 0;
  if (*piVar13 == 0) {
    dVar25 = (double)*(float *)(iVar10 + -0x7cd4);
    goto LAB_000e8018;
  }
  func_0x000ba364(*piVar13);
  puVar12 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7f7c) + 0x18))
                      ((int *)**(undefined4 **)(iVar10 + -0x7f7c),0x24,0x10);
  puVar14 = (undefined4 *)0x0;
  if (puVar12 != (undefined4 *)0x0) {
    func_0x008d0de8(puVar12);
    piVar23 = puVar12 + 1;
    uVar15 = *(undefined4 *)(iVar10 + -0x7edc);
    *puVar12 = *(undefined4 *)(iVar10 + -0x7ee0);
    puVar12[8] = 0;
    puVar12[4] = uVar15;
    puVar12[5] = 0;
    puVar12[6] = 0;
    *(undefined1 *)(puVar12 + 7) = 0;
    piVar6 = (int *)*piVar23;
    if ((piVar6 == (int *)0x0) || (iVar11 = *piVar6, *piVar6 = iVar11 + -1, iVar11 + -1 != 0)) {
      puVar14 = *(undefined4 **)(iVar10 + -0x7fb0);
    }
    else {
      puVar14 = *(undefined4 **)(iVar10 + -0x7fb0);
      (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x1c))((int *)*puVar14,*piVar23);
    }
    puVar14 = (undefined4 *)
              (*(code *)**(undefined4 **)(*(int *)*puVar14 + 0x18))((int *)*puVar14,0x1f,0x10);
    *piVar23 = (int)puVar14;
    puVar7 = *(undefined1 **)(iVar10 + -0x7d68);
    *puVar14 = 1;
    *(undefined4 *)(*piVar23 + 4) = 0x13;
    iVar11 = *piVar23;
    uVar1 = puVar7[1];
    uVar2 = puVar7[2];
    uVar3 = puVar7[3];
    *(undefined1 *)(iVar11 + 8) = *puVar7;
    *(undefined1 *)(iVar11 + 9) = uVar1;
    *(undefined1 *)(iVar11 + 10) = uVar2;
    *(undefined1 *)(iVar11 + 0xb) = uVar3;
    uVar1 = puVar7[5];
    uVar2 = puVar7[6];
    uVar3 = puVar7[7];
    *(undefined1 *)(iVar11 + 0xc) = puVar7[4];
    *(undefined1 *)(iVar11 + 0xd) = uVar1;
    *(undefined1 *)(iVar11 + 0xe) = uVar2;
    *(undefined1 *)(iVar11 + 0xf) = uVar3;
    uVar1 = puVar7[9];
    uVar2 = puVar7[10];
    uVar3 = puVar7[0xb];
    *(undefined1 *)(iVar11 + 0x10) = puVar7[8];
    *(undefined1 *)(iVar11 + 0x11) = uVar1;
    *(undefined1 *)(iVar11 + 0x12) = uVar2;
    *(undefined1 *)(iVar11 + 0x13) = uVar3;
    uVar1 = puVar7[0xd];
    uVar2 = puVar7[0xe];
    uVar3 = puVar7[0xf];
    *(undefined1 *)(iVar11 + 0x14) = puVar7[0xc];
    *(undefined1 *)(iVar11 + 0x15) = uVar1;
    *(undefined1 *)(iVar11 + 0x16) = uVar2;
    *(undefined1 *)(iVar11 + 0x17) = uVar3;
    uVar1 = puVar7[0x10];
    uVar2 = puVar7[0x11];
    uVar3 = puVar7[0x12];
    *(undefined1 *)(iVar11 + 0x1b) = puVar7[0x13];
    *(undefined1 *)(iVar11 + 0x18) = uVar1;
    *(undefined1 *)(iVar11 + 0x19) = uVar2;
    *(undefined1 *)(iVar11 + 0x1a) = uVar3;
    puVar14 = puVar12;
  }
  puVar12 = *(undefined4 **)(iVar10 + -0x7f80);
  piVar6 = (int *)*puVar12;
  iVar11 = (*(code *)**(undefined4 **)(*piVar6 + 0x18))(piVar6,0x3c,0x10);
  if (iVar11 == 0) {
    dVar24 = (double)*(float *)(iVar10 + -0x7d58);
  }
  else {
    dVar24 = (double)*(float *)(iVar10 + -0x7d58);
    func_0x00900a64((double)*(float *)(iVar10 + -0x7d60),dVar24,iVar11,
                    *(undefined4 *)(iVar10 + -0x7d64),0,0);
  }
  func_0x009017bc(puVar14,iVar11);
  piVar6 = (int *)*puVar12;
  iVar11 = (*(code *)**(undefined4 **)(*piVar6 + 0x18))(piVar6,0x3c,0x10);
  if (iVar11 != 0) {
    func_0x00900a64((double)*(float *)(iVar10 + -0x7d60),(double)*(float *)(iVar10 + -0x7d4c),iVar11
                    ,*(undefined4 *)(iVar10 + -0x7d50),0,0x10);
  }
  func_0x009017bc(puVar14,iVar11);
  func_0x000b941c(*piVar13,puVar14);
  func_0x000ba110(*piVar13,*(undefined4 *)(iVar10 + -0x7d44),*(undefined4 *)(iVar10 + -0x7d40));
  iVar11 = *piVar13;
  uVar15 = func_0x000b9e78(iVar11,auStack_260,0);
  iVar16 = (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7f88) + 0x18))
                     ((int *)**(undefined4 **)(iVar10 + -0x7f88),0x1c,0x10);
  if (iVar16 != 0) {
    func_0x008f84f8(iVar16,*(undefined4 *)(iVar10 + -0x7d3c),uVar15,0);
  }
  func_0x000b941c(iVar11,iVar16);
  puVar14 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fbc) + 0x18))
                      ((int *)**(undefined4 **)(iVar10 + -0x7fbc),0x20,0x10);
  if (puVar14 != (undefined4 *)0x0) {
    puVar12 = *(undefined4 **)(iVar10 + -0x7fb0);
    piVar6 = puVar14 + 1;
    *puVar14 = *(undefined4 *)(iVar10 + -0x7d38);
    puVar12 = (undefined4 *)
              (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x10,0x10);
    *piVar6 = (int)puVar12;
    puVar7 = *(undefined1 **)(iVar10 + -0x7d34);
    uVar15 = *(undefined4 *)(iVar10 + -0x7edc);
    *puVar12 = 1;
    *(undefined4 *)(*piVar6 + 4) = 4;
    iVar11 = *piVar6;
    uVar1 = puVar7[2];
    uVar2 = puVar7[1];
    uVar3 = puVar7[3];
    *(undefined1 *)(iVar11 + 8) = *puVar7;
    *(undefined1 *)(iVar11 + 9) = uVar2;
    *(undefined1 *)(iVar11 + 10) = uVar1;
    *(undefined1 *)(iVar11 + 0xb) = uVar3;
    *(undefined1 *)(iVar11 + 0xc) = puVar7[4];
    puVar14[2] = uVar15;
    puVar14[3] = 0;
    puVar14[4] = 0;
    puVar14[6] = 0;
    *(undefined1 *)(puVar14 + 7) = 0;
    *(undefined1 *)(puVar14 + 5) = 1;
  }
  puVar12 = *(undefined4 **)(iVar10 + -0x7fc0);
  *(undefined1 *)(puVar14 + 7) = 1;
  puVar17 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x20,0x10);
  if (puVar17 != (undefined4 *)0x0) {
    uVar15 = *(undefined4 *)(iVar10 + -0x7edc);
    uVar8 = *(undefined4 *)(iVar10 + -0x7d2c);
    *puVar17 = *(undefined4 *)(iVar10 + -0x7d30);
    puVar17[1] = 0;
    puVar17[2] = 0;
    puVar17[3] = uVar15;
    puVar17[7] = 0;
    puVar17[4] = 0;
    puVar17[5] = 0;
    *(undefined1 *)(puVar17 + 6) = 0;
    func_0x00ff136c(puVar17 + 1,uVar8);
    *(undefined1 *)(puVar17 + 6) = 1;
  }
  puVar21 = *(undefined4 **)(iVar10 + -0x7fc4);
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x18,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    piVar6 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *piVar6 = 0;
    iVar11 = *(int *)(iVar11 + 4);
    if (iVar11 == 0) {
      *piVar6 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) {
        *piVar6 = 0;
      }
      else {
        puVar20 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar20;
        *puVar20 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
      }
    }
    piVar9 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d1c);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d20);
    piVar23 = (int *)*piVar9;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar9);
    }
    if (iVar11 == 0) {
LAB_000e5b90:
      *piVar9 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e5b90;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar9 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar9 + 4) = iVar16;
      func_0x00fe6bfc(*piVar9 + 8,iVar11);
    }
    piVar9 = puVar18 + 1;
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d18);
    *(undefined1 *)(puVar18 + 5) = 1;
    puVar18[4] = 0;
    puVar18[2] = 0;
    puVar18[3] = 0;
    piVar23 = (int *)*piVar9;
    iVar11 = *(int *)(*(int *)(iVar10 + -0x7d14) + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar9);
    }
    if (iVar11 == 0) {
LAB_000e5c10:
      *piVar9 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e5c10;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar9 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar9 + 4) = iVar16;
      func_0x00fe6bfc(*piVar9 + 8,iVar11);
    }
    uVar15 = *(undefined4 *)(iVar10 + -0x7d0c);
    uVar8 = *(undefined4 *)(iVar10 + -0x7d04);
    uVar4 = *(undefined4 *)(iVar10 + -0x7cfc);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d10);
    *(undefined1 *)(puVar18 + 5) = 1;
    puVar18[2] = uVar15;
    puVar18[3] = uVar8;
    puVar18[4] = uVar4;
    piVar23 = (int *)*piVar6;
    iVar11 = *(int *)(*(int *)(iVar10 + -0x7cf4) + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar6);
    }
    if (iVar11 != 0) {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 != 0) {
        puVar20 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar20;
        *puVar20 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
        goto LAB_000e5c94;
      }
    }
    *piVar6 = 0;
  }
LAB_000e5c94:
  puVar17[2] = puVar18;
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x10,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    puVar20 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    puVar19 = puVar18 + 3;
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *puVar20 = 0;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7cec);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cf0);
    puVar18[2] = 1;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7ce4);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7ce8);
    *puVar19 = 0;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    func_0x00ff136c(puVar19,*(undefined4 *)(iVar10 + -0x7ce0));
    uVar15 = *(undefined4 *)(iVar10 + -0x7cdc);
    uVar8 = *(undefined4 *)(iVar10 + -0x7d64);
    puVar18[2] = 300;
    *puVar18 = uVar15;
    func_0x00ff136c(puVar19,uVar8);
  }
  func_0x0021ea10(puVar17,puVar18);
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x10,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    puVar20 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    puVar19 = puVar18 + 3;
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *puVar20 = 0;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7cec);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cf0);
    puVar18[2] = 1;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7ce4);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7ce8);
    *puVar19 = 0;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    func_0x00ff136c(puVar19,*(undefined4 *)(iVar10 + -0x7ce0));
    uVar15 = *(undefined4 *)(iVar10 + -0x7cdc);
    uVar8 = *(undefined4 *)(iVar10 + -0x7d50);
    puVar18[2] = 0xffffff06;
    *puVar18 = uVar15;
    func_0x00ff136c(puVar19,uVar8);
  }
  func_0x0021ea10(puVar17,puVar18);
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x10,0x10);
  if (puVar18 == (undefined4 *)0x0) {
    dVar25 = (double)*(float *)(iVar10 + -0x7cd4);
  }
  else {
    piVar6 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *piVar6 = 0;
    iVar11 = *(int *)(iVar11 + 4);
    if (iVar11 == 0) {
      *piVar6 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) {
        *piVar6 = 0;
      }
      else {
        puVar20 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar20;
        *puVar20 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
      }
    }
    piVar23 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7cec);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cf0);
    puVar18[2] = 1;
    piVar6 = (int *)*piVar23;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar6 != (int *)0x0) && (iVar16 = *piVar6, *piVar6 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar23);
    }
    if (iVar11 == 0) {
LAB_000e5f84:
      *piVar23 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e5f84;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar23 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar23 + 4) = iVar16;
      func_0x00fe6bfc(*piVar23 + 8,iVar11);
    }
    piVar23 = puVar18 + 1;
    fVar5 = *(float *)(iVar10 + -0x7cd4);
    dVar25 = (double)fVar5;
    iVar11 = *(int *)(iVar10 + -0x7ccc);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cd8);
    puVar18[3] = fVar5;
    piVar6 = (int *)*piVar23;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar6 != (int *)0x0) && (iVar16 = *piVar6, *piVar6 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar23);
    }
    if (iVar11 == 0) {
LAB_000e5ff4:
      *piVar23 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e5ff4;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar23 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar23 + 4) = iVar16;
      func_0x00fe6bfc(*piVar23 + 8,iVar11);
    }
    uVar15 = *(undefined4 *)(iVar10 + -0x7cc4);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cc8);
    puVar18[3] = uVar15;
    puVar18[2] = 1;
  }
  func_0x0021ea10(puVar17,puVar18);
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x10,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    puVar20 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *puVar20 = 0;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7cec);
    uVar15 = *(undefined4 *)(iVar10 + -0x7cf0);
    puVar18[2] = 1;
    *puVar18 = uVar15;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7ccc);
    uVar15 = *(undefined4 *)(iVar10 + -0x7cbc);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cd8);
    puVar18[3] = uVar15;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    puVar18[2] = 1;
  }
  func_0x0021ea10(puVar17,puVar18);
  func_0x0021df68(puVar14,puVar17);
  puVar17 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x20,0x10);
  if (puVar17 != (undefined4 *)0x0) {
    uVar15 = *(undefined4 *)(iVar10 + -0x7edc);
    uVar8 = *(undefined4 *)(iVar10 + -0x7cb4);
    *puVar17 = *(undefined4 *)(iVar10 + -0x7d30);
    puVar17[1] = 0;
    puVar17[2] = 0;
    puVar17[7] = 0;
    puVar17[4] = 0;
    puVar17[5] = 0;
    *(undefined1 *)(puVar17 + 6) = 0;
    puVar17[3] = uVar15;
    func_0x00ff136c(puVar17 + 1,uVar8);
    *(undefined1 *)(puVar17 + 6) = 1;
  }
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x14,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    piVar23 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *piVar23 = 0;
    func_0x00ff136c(piVar23,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7d1c);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d20);
    piVar6 = (int *)*piVar23;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar6 != (int *)0x0) && (iVar16 = *piVar6, *piVar6 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar23);
    }
    if (iVar11 == 0) {
LAB_000e6258:
      *piVar23 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e6258;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar23 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar23 + 4) = iVar16;
      func_0x00fe6bfc(*piVar23 + 8,iVar11);
    }
    piVar9 = puVar18 + 1;
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cb0);
    *(undefined1 *)(puVar18 + 4) = 1;
    puVar18[3] = 0;
    puVar18[2] = 0;
    piVar6 = (int *)*piVar9;
    iVar11 = *(int *)(*(int *)(iVar10 + -0x7cac) + 4);
    if ((piVar6 != (int *)0x0) && (iVar16 = *piVar6, *piVar6 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar9);
    }
    if (iVar11 == 0) {
LAB_000e62d4:
      *piVar9 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e62d4;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar9 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar9 + 4) = iVar16;
      func_0x00fe6bfc(*piVar9 + 8,iVar11);
    }
    uVar15 = *(undefined4 *)(iVar10 + -0x7ca4);
    uVar8 = *(undefined4 *)(iVar10 + -0x7cfc);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7ca8);
    *(undefined1 *)(puVar18 + 4) = 1;
    puVar18[2] = uVar15;
    puVar18[3] = uVar8;
    piVar6 = (int *)*piVar23;
    iVar11 = *(int *)(*(int *)(iVar10 + -0x7c9c) + 4);
    if ((piVar6 != (int *)0x0) && (iVar16 = *piVar6, *piVar6 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar23);
    }
    if (iVar11 != 0) {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 != 0) {
        puVar20 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar23 = (int)puVar20;
        *puVar20 = 1;
        *(int *)(*piVar23 + 4) = iVar16;
        func_0x00fe6bfc(*piVar23 + 8,iVar11);
        goto LAB_000e6350;
      }
    }
    *piVar23 = 0;
  }
LAB_000e6350:
  puVar17[2] = puVar18;
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x10,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    puVar20 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    puVar19 = puVar18 + 3;
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *puVar20 = 0;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7cec);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cf0);
    puVar18[2] = 1;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7ce4);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7ce8);
    *puVar19 = 0;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    func_0x00ff136c(puVar19,*(undefined4 *)(iVar10 + -0x7ce0));
    uVar15 = *(undefined4 *)(iVar10 + -0x7cdc);
    uVar8 = *(undefined4 *)(iVar10 + -0x7d64);
    puVar18[2] = 0x32;
    *puVar18 = uVar15;
    func_0x00ff136c(puVar19,uVar8);
  }
  func_0x0021ea10(puVar17,puVar18);
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x10,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    puVar20 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    puVar19 = puVar18 + 3;
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *puVar20 = 0;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7cec);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cf0);
    puVar18[2] = 1;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7ce4);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7ce8);
    *puVar19 = 0;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    func_0x00ff136c(puVar19,*(undefined4 *)(iVar10 + -0x7ce0));
    uVar15 = *(undefined4 *)(iVar10 + -0x7cdc);
    uVar8 = *(undefined4 *)(iVar10 + -0x7d50);
    puVar18[2] = 100;
    *puVar18 = uVar15;
    func_0x00ff136c(puVar19,uVar8);
  }
  func_0x0021ea10(puVar17,puVar18);
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x10,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    piVar6 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *piVar6 = 0;
    iVar11 = *(int *)(iVar11 + 4);
    if (iVar11 == 0) {
      *piVar6 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) {
        *piVar6 = 0;
      }
      else {
        puVar20 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar20;
        *puVar20 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
      }
    }
    piVar23 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7cec);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cf0);
    puVar18[2] = 1;
    piVar6 = (int *)*piVar23;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar6 != (int *)0x0) && (iVar16 = *piVar6, *piVar6 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar23);
    }
    if (iVar11 == 0) {
LAB_000e6640:
      *piVar23 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e6640;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar23 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar23 + 4) = iVar16;
      func_0x00fe6bfc(*piVar23 + 8,iVar11);
    }
    piVar23 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7ccc);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cd8);
    puVar18[3] = (float)dVar25;
    piVar6 = (int *)*piVar23;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar6 != (int *)0x0) && (iVar16 = *piVar6, *piVar6 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar23);
    }
    if (iVar11 == 0) {
LAB_000e66ac:
      *piVar23 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e66ac;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar23 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar23 + 4) = iVar16;
      func_0x00fe6bfc(*piVar23 + 8,iVar11);
    }
    uVar15 = *(undefined4 *)(iVar10 + -0x7cc4);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cc8);
    puVar18[3] = uVar15;
    puVar18[2] = 1;
  }
  func_0x0021ea10(puVar17,puVar18);
  func_0x0021df68(puVar14,puVar17);
  puVar17 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x20,0x10);
  if (puVar17 != (undefined4 *)0x0) {
    uVar15 = *(undefined4 *)(iVar10 + -0x7edc);
    uVar8 = *(undefined4 *)(iVar10 + -0x7c98);
    *puVar17 = *(undefined4 *)(iVar10 + -0x7d30);
    puVar17[1] = 0;
    puVar17[2] = 0;
    puVar17[7] = 0;
    puVar17[4] = 0;
    puVar17[5] = 0;
    *(undefined1 *)(puVar17 + 6) = 0;
    puVar17[3] = uVar15;
    func_0x00ff136c(puVar17 + 1,uVar8);
    *(undefined1 *)(puVar17 + 6) = 1;
  }
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x14,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    piVar6 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *piVar6 = 0;
    iVar11 = *(int *)(iVar11 + 4);
    if (iVar11 == 0) {
      *piVar6 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) {
        *piVar6 = 0;
      }
      else {
        puVar20 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar20;
        *puVar20 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
      }
    }
    piVar9 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d1c);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d20);
    piVar23 = (int *)*piVar9;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar9);
    }
    if (iVar11 == 0) {
LAB_000e6870:
      *piVar9 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e6870;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar9 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar9 + 4) = iVar16;
      func_0x00fe6bfc(*piVar9 + 8,iVar11);
    }
    piVar9 = puVar18 + 1;
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cb0);
    *(undefined1 *)(puVar18 + 4) = 1;
    puVar18[3] = 0;
    puVar18[2] = 0;
    piVar23 = (int *)*piVar9;
    iVar11 = *(int *)(*(int *)(iVar10 + -0x7cac) + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar9);
    }
    if (iVar11 == 0) {
LAB_000e68ec:
      *piVar9 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e68ec;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar9 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar9 + 4) = iVar16;
      func_0x00fe6bfc(*piVar9 + 8,iVar11);
    }
    uVar15 = *(undefined4 *)(iVar10 + -0x7c90);
    uVar8 = *(undefined4 *)(iVar10 + -0x7d0c);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7c94);
    *(undefined1 *)(puVar18 + 4) = 1;
    puVar18[2] = uVar15;
    puVar18[3] = uVar8;
    piVar23 = (int *)*piVar6;
    iVar11 = *(int *)(*(int *)(iVar10 + -0x7c88) + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar6);
    }
    if (iVar11 != 0) {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 != 0) {
        puVar20 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar20;
        *puVar20 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
        goto LAB_000e6968;
      }
    }
    *piVar6 = 0;
  }
LAB_000e6968:
  puVar17[2] = puVar18;
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x10,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    piVar6 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *piVar6 = 0;
    iVar11 = *(int *)(iVar11 + 4);
    if (iVar11 == 0) {
      puVar20 = *(undefined4 **)(iVar10 + -0x7fb0);
      *piVar6 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) {
        puVar20 = *(undefined4 **)(iVar10 + -0x7fb0);
        *piVar6 = 0;
      }
      else {
        puVar20 = *(undefined4 **)(iVar10 + -0x7fb0);
        puVar19 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)*puVar20 + 0x18))
                            ((int *)*puVar20,iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar19;
        *puVar19 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
      }
    }
    piVar23 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7cec);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cf0);
    puVar18[2] = 1;
    piVar6 = (int *)*piVar23;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar6 != (int *)0x0) && (iVar16 = *piVar6, *piVar6 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar20 + 0x1c))((int *)*puVar20,*piVar23);
    }
    if (iVar11 == 0) {
LAB_000e6a6c:
      *piVar23 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e6a6c;
      puVar19 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)*puVar20 + 0x18))
                          ((int *)*puVar20,iVar16 + 0xc,0x10);
      *piVar23 = (int)puVar19;
      *puVar19 = 1;
      *(int *)(*piVar23 + 4) = iVar16;
      func_0x00fe6bfc(*piVar23 + 8,iVar11);
    }
    piVar23 = puVar18 + 3;
    piVar9 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7ce4);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7ce8);
    *piVar23 = 0;
    piVar6 = (int *)*piVar9;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar6 != (int *)0x0) && (iVar16 = *piVar6, *piVar6 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar20 + 0x1c))((int *)*puVar20,*piVar9);
    }
    if (iVar11 == 0) {
LAB_000e6ae4:
      *piVar9 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e6ae4;
      puVar19 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)*puVar20 + 0x18))
                          ((int *)*puVar20,iVar16 + 0xc,0x10);
      *piVar9 = (int)puVar19;
      *puVar19 = 1;
      *(int *)(*piVar9 + 4) = iVar16;
      func_0x00fe6bfc(*piVar9 + 8,iVar11);
    }
    piVar6 = (int *)*piVar23;
    if ((piVar6 != (int *)0x0) && (iVar11 = *piVar6, *piVar6 = iVar11 + -1, iVar11 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar20 + 0x1c))((int *)*puVar20,*piVar23);
    }
    puVar19 = (undefined4 *)
              (*(code *)**(undefined4 **)(*(int *)*puVar20 + 0x18))((int *)*puVar20,0x28,0x10);
    *piVar23 = (int)puVar19;
    puVar7 = *(undefined1 **)(iVar10 + -0x7ce0);
    *puVar19 = 1;
    *(undefined4 *)(*piVar23 + 4) = 0x1c;
    iVar11 = *piVar23;
    uVar1 = puVar7[1];
    uVar2 = puVar7[2];
    uVar3 = puVar7[3];
    *(undefined1 *)(iVar11 + 8) = *puVar7;
    *(undefined1 *)(iVar11 + 9) = uVar1;
    *(undefined1 *)(iVar11 + 10) = uVar2;
    *(undefined1 *)(iVar11 + 0xb) = uVar3;
    uVar1 = puVar7[5];
    uVar2 = puVar7[6];
    uVar3 = puVar7[7];
    *(undefined1 *)(iVar11 + 0xc) = puVar7[4];
    *(undefined1 *)(iVar11 + 0xd) = uVar1;
    *(undefined1 *)(iVar11 + 0xe) = uVar2;
    *(undefined1 *)(iVar11 + 0xf) = uVar3;
    uVar1 = puVar7[9];
    uVar2 = puVar7[10];
    uVar3 = puVar7[0xb];
    *(undefined1 *)(iVar11 + 0x10) = puVar7[8];
    *(undefined1 *)(iVar11 + 0x11) = uVar1;
    *(undefined1 *)(iVar11 + 0x12) = uVar2;
    *(undefined1 *)(iVar11 + 0x13) = uVar3;
    uVar1 = puVar7[0xd];
    uVar2 = puVar7[0xe];
    uVar3 = puVar7[0xf];
    *(undefined1 *)(iVar11 + 0x14) = puVar7[0xc];
    *(undefined1 *)(iVar11 + 0x15) = uVar1;
    *(undefined1 *)(iVar11 + 0x16) = uVar2;
    *(undefined1 *)(iVar11 + 0x17) = uVar3;
    uVar1 = puVar7[0x11];
    uVar2 = puVar7[0x12];
    uVar3 = puVar7[0x13];
    *(undefined1 *)(iVar11 + 0x18) = puVar7[0x10];
    *(undefined1 *)(iVar11 + 0x19) = uVar1;
    *(undefined1 *)(iVar11 + 0x1a) = uVar2;
    *(undefined1 *)(iVar11 + 0x1b) = uVar3;
    uVar1 = puVar7[0x15];
    uVar2 = puVar7[0x16];
    uVar3 = puVar7[0x17];
    *(undefined1 *)(iVar11 + 0x1c) = puVar7[0x14];
    *(undefined1 *)(iVar11 + 0x1d) = uVar1;
    *(undefined1 *)(iVar11 + 0x1e) = uVar2;
    *(undefined1 *)(iVar11 + 0x1f) = uVar3;
    uVar1 = puVar7[0x18];
    uVar2 = puVar7[0x1a];
    uVar3 = puVar7[0x1b];
    *(undefined1 *)(iVar11 + 0x21) = puVar7[0x19];
    *(undefined1 *)(iVar11 + 0x20) = uVar1;
    *(undefined1 *)(iVar11 + 0x22) = uVar2;
    *(undefined1 *)(iVar11 + 0x23) = uVar3;
    uVar15 = *(undefined4 *)(iVar10 + -0x7cdc);
    *(undefined1 *)(iVar11 + 0x24) = puVar7[0x1c];
    *puVar18 = uVar15;
    puVar18[2] = 0xffffffce;
    piVar6 = (int *)*piVar23;
    if ((piVar6 != (int *)0x0) && (iVar11 = *piVar6, *piVar6 = iVar11 + -1, iVar11 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)*puVar20 + 0x1c))((int *)*puVar20,*piVar23);
    }
    puVar20 = (undefined4 *)
              (*(code *)**(undefined4 **)(*(int *)*puVar20 + 0x18))((int *)*puVar20,0x1a,0x10);
    *piVar23 = (int)puVar20;
    puVar7 = *(undefined1 **)(iVar10 + -0x7d64);
    *puVar20 = 1;
    *(undefined4 *)(*piVar23 + 4) = 0xe;
    iVar11 = *piVar23;
    uVar1 = puVar7[1];
    uVar2 = puVar7[2];
    uVar3 = puVar7[3];
    *(undefined1 *)(iVar11 + 8) = *puVar7;
    *(undefined1 *)(iVar11 + 9) = uVar1;
    *(undefined1 *)(iVar11 + 10) = uVar2;
    *(undefined1 *)(iVar11 + 0xb) = uVar3;
    uVar1 = puVar7[5];
    uVar2 = puVar7[6];
    uVar3 = puVar7[7];
    *(undefined1 *)(iVar11 + 0xc) = puVar7[4];
    *(undefined1 *)(iVar11 + 0xd) = uVar1;
    *(undefined1 *)(iVar11 + 0xe) = uVar2;
    *(undefined1 *)(iVar11 + 0xf) = uVar3;
    uVar1 = puVar7[9];
    uVar2 = puVar7[10];
    uVar3 = puVar7[0xb];
    *(undefined1 *)(iVar11 + 0x10) = puVar7[8];
    *(undefined1 *)(iVar11 + 0x11) = uVar1;
    *(undefined1 *)(iVar11 + 0x12) = uVar2;
    *(undefined1 *)(iVar11 + 0x13) = uVar3;
    uVar1 = puVar7[0xe];
    uVar2 = puVar7[0xd];
    *(undefined1 *)(iVar11 + 0x14) = puVar7[0xc];
    *(undefined1 *)(iVar11 + 0x16) = uVar1;
    *(undefined1 *)(iVar11 + 0x15) = uVar2;
  }
  func_0x0021ea10(puVar17,puVar18);
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x10,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    piVar6 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *piVar6 = 0;
    iVar11 = *(int *)(iVar11 + 4);
    if (iVar11 == 0) {
      *piVar6 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) {
        *piVar6 = 0;
      }
      else {
        puVar20 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar20;
        *puVar20 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
      }
    }
    piVar9 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7cec);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cf0);
    puVar18[2] = 1;
    piVar23 = (int *)*piVar9;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar9);
    }
    if (iVar11 == 0) {
LAB_000e6e60:
      *piVar9 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e6e60;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar9 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar9 + 4) = iVar16;
      func_0x00fe6bfc(*piVar9 + 8,iVar11);
    }
    uVar15 = *(undefined4 *)(iVar10 + -0x7cc4);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cd8);
    puVar18[3] = uVar15;
    piVar23 = (int *)*piVar6;
    iVar11 = *(int *)(*(int *)(iVar10 + -0x7ccc) + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar6);
    }
    if (iVar11 == 0) {
LAB_000e6ec8:
      *piVar6 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e6ec8;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar6 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar6 + 4) = iVar16;
      func_0x00fe6bfc(*piVar6 + 8,iVar11);
    }
    puVar18[2] = 1;
  }
  func_0x0021ea10(puVar17,puVar18);
  func_0x0021df68(puVar14,puVar17);
  puVar17 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x20,0x10);
  if (puVar17 != (undefined4 *)0x0) {
    uVar15 = *(undefined4 *)(iVar10 + -0x7edc);
    uVar8 = *(undefined4 *)(iVar10 + -0x7c84);
    *puVar17 = *(undefined4 *)(iVar10 + -0x7d30);
    puVar17[1] = 0;
    puVar17[2] = 0;
    puVar17[7] = 0;
    puVar17[4] = 0;
    puVar17[5] = 0;
    *(undefined1 *)(puVar17 + 6) = 0;
    puVar17[3] = uVar15;
    func_0x00ff136c(puVar17 + 1,uVar8);
    *(undefined1 *)(puVar17 + 6) = 1;
  }
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x14,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    piVar6 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *piVar6 = 0;
    iVar11 = *(int *)(iVar11 + 4);
    if (iVar11 == 0) {
      *piVar6 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) {
        *piVar6 = 0;
      }
      else {
        puVar20 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar20;
        *puVar20 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
      }
    }
    piVar9 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d1c);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d20);
    piVar23 = (int *)*piVar9;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar9);
    }
    if (iVar11 == 0) {
LAB_000e707c:
      *piVar9 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e707c;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar9 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar9 + 4) = iVar16;
      func_0x00fe6bfc(*piVar9 + 8,iVar11);
    }
    piVar9 = puVar18 + 1;
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cb0);
    *(undefined1 *)(puVar18 + 4) = 1;
    puVar18[3] = 0;
    puVar18[2] = 0;
    piVar23 = (int *)*piVar9;
    iVar11 = *(int *)(*(int *)(iVar10 + -0x7cac) + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar9);
    }
    if (iVar11 == 0) {
LAB_000e70f8:
      *piVar9 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e70f8;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar9 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar9 + 4) = iVar16;
      func_0x00fe6bfc(*piVar9 + 8,iVar11);
    }
    uVar15 = *(undefined4 *)(iVar10 + -0x7c90);
    uVar8 = *(undefined4 *)(iVar10 + -0x7d0c);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7c94);
    *(undefined1 *)(puVar18 + 4) = 1;
    puVar18[2] = uVar15;
    puVar18[3] = uVar8;
    piVar23 = (int *)*piVar6;
    iVar11 = *(int *)(*(int *)(iVar10 + -0x7c88) + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar6);
    }
    if (iVar11 != 0) {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 != 0) {
        puVar20 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar20;
        *puVar20 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
        goto LAB_000e7174;
      }
    }
    *piVar6 = 0;
  }
LAB_000e7174:
  puVar17[2] = puVar18;
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x10,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    puVar20 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    puVar19 = puVar18 + 3;
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *puVar20 = 0;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7cec);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cf0);
    puVar18[2] = 1;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7ce4);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7ce8);
    *puVar19 = 0;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    func_0x00ff136c(puVar19,*(undefined4 *)(iVar10 + -0x7ce0));
    uVar15 = *(undefined4 *)(iVar10 + -0x7cdc);
    uVar8 = *(undefined4 *)(iVar10 + -0x7d64);
    puVar18[2] = 100;
    *puVar18 = uVar15;
    func_0x00ff136c(puVar19,uVar8);
  }
  func_0x0021ea10(puVar17,puVar18);
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x10,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    piVar6 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *piVar6 = 0;
    iVar11 = *(int *)(iVar11 + 4);
    if (iVar11 == 0) {
      *piVar6 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) {
        *piVar6 = 0;
      }
      else {
        puVar20 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar20;
        *puVar20 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
      }
    }
    piVar23 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7cec);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cf0);
    puVar18[2] = 1;
    piVar6 = (int *)*piVar23;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar6 != (int *)0x0) && (iVar16 = *piVar6, *piVar6 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar23);
    }
    if (iVar11 == 0) {
LAB_000e736c:
      *piVar23 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e736c;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar23 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar23 + 4) = iVar16;
      func_0x00fe6bfc(*piVar23 + 8,iVar11);
    }
    piVar23 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7ccc);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cd8);
    puVar18[3] = (float)dVar25;
    piVar6 = (int *)*piVar23;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar6 != (int *)0x0) && (iVar16 = *piVar6, *piVar6 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar23);
    }
    if (iVar11 == 0) {
LAB_000e73d8:
      *piVar23 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e73d8;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar23 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar23 + 4) = iVar16;
      func_0x00fe6bfc(*piVar23 + 8,iVar11);
    }
    uVar15 = *(undefined4 *)(iVar10 + -0x7cc4);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cc8);
    puVar18[3] = uVar15;
    puVar18[2] = 1;
  }
  func_0x0021ea10(puVar17,puVar18);
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x10,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    puVar20 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *puVar20 = 0;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7cec);
    uVar15 = *(undefined4 *)(iVar10 + -0x7cf0);
    puVar18[2] = 1;
    *puVar18 = uVar15;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7ccc);
    uVar15 = *(undefined4 *)(iVar10 + -0x7cc4);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cd8);
    puVar18[3] = uVar15;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    puVar18[2] = 1;
  }
  func_0x0021ea10(puVar17,puVar18);
  func_0x0021df68(puVar14,puVar17);
  puVar17 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x20,0x10);
  if (puVar17 != (undefined4 *)0x0) {
    uVar15 = *(undefined4 *)(iVar10 + -0x7edc);
    uVar8 = *(undefined4 *)(iVar10 + -0x7c80);
    *puVar17 = *(undefined4 *)(iVar10 + -0x7d30);
    puVar17[1] = 0;
    puVar17[2] = 0;
    puVar17[7] = 0;
    puVar17[4] = 0;
    puVar17[5] = 0;
    *(undefined1 *)(puVar17 + 6) = 0;
    puVar17[3] = uVar15;
    func_0x00ff136c(puVar17 + 1,uVar8);
    *(undefined1 *)(puVar17 + 6) = 1;
  }
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x18,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    piVar6 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *piVar6 = 0;
    iVar11 = *(int *)(iVar11 + 4);
    if (iVar11 == 0) {
      *piVar6 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) {
        *piVar6 = 0;
      }
      else {
        puVar20 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar20;
        *puVar20 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
      }
    }
    piVar9 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d1c);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d20);
    piVar23 = (int *)*piVar9;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar9);
    }
    if (iVar11 == 0) {
LAB_000e7668:
      *piVar9 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e7668;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar9 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar9 + 4) = iVar16;
      func_0x00fe6bfc(*piVar9 + 8,iVar11);
    }
    piVar9 = puVar18 + 1;
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d18);
    *(undefined1 *)(puVar18 + 5) = 1;
    puVar18[4] = 0;
    puVar18[2] = 0;
    puVar18[3] = 0;
    piVar23 = (int *)*piVar9;
    iVar11 = *(int *)(*(int *)(iVar10 + -0x7d14) + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar9);
    }
    if (iVar11 == 0) {
LAB_000e76e8:
      *piVar9 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e76e8;
      puVar20 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar9 = (int)puVar20;
      *puVar20 = 1;
      *(int *)(*piVar9 + 4) = iVar16;
      func_0x00fe6bfc(*piVar9 + 8,iVar11);
    }
    uVar15 = *(undefined4 *)(iVar10 + -0x7c78);
    uVar8 = *(undefined4 *)(iVar10 + -0x7c70);
    uVar4 = *(undefined4 *)(iVar10 + -0x7c68);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7c7c);
    *(undefined1 *)(puVar18 + 5) = 1;
    puVar18[2] = uVar15;
    puVar18[3] = uVar8;
    puVar18[4] = uVar4;
    piVar23 = (int *)*piVar6;
    iVar11 = *(int *)(*(int *)(iVar10 + -0x7c60) + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar6);
    }
    if (iVar11 != 0) {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 != 0) {
        puVar20 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar20;
        *puVar20 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
        goto LAB_000e776c;
      }
    }
    *piVar6 = 0;
  }
LAB_000e776c:
  puVar17[2] = puVar18;
  puVar18 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x10,0x10);
  if (puVar18 != (undefined4 *)0x0) {
    puVar20 = puVar18 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7d28);
    *puVar20 = 0;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7cec);
    uVar15 = *(undefined4 *)(iVar10 + -0x7cf0);
    puVar18[2] = 1;
    *puVar18 = uVar15;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7ccc);
    uVar15 = *(undefined4 *)(iVar10 + -0x7c5c);
    *puVar18 = *(undefined4 *)(iVar10 + -0x7cd8);
    puVar18[3] = uVar15;
    func_0x00ff136c(puVar20,*(undefined4 *)(iVar11 + 4));
    puVar18[2] = 1;
  }
  func_0x0021ea10(puVar17,puVar18);
  func_0x0021df68(puVar14,puVar17);
  puVar12 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar12 + 0x18))((int *)*puVar12,0x20,0x10);
  if (puVar12 != (undefined4 *)0x0) {
    uVar15 = *(undefined4 *)(iVar10 + -0x7edc);
    piVar23 = puVar12 + 1;
    *puVar12 = *(undefined4 *)(iVar10 + -0x7d30);
    *piVar23 = 0;
    puVar12[2] = 0;
    puVar12[3] = uVar15;
    puVar12[7] = 0;
    puVar12[4] = 0;
    puVar12[5] = 0;
    *(undefined1 *)(puVar12 + 6) = 0;
    piVar6 = (int *)*piVar23;
    if ((piVar6 == (int *)0x0) || (iVar11 = *piVar6, *piVar6 = iVar11 + -1, iVar11 + -1 != 0)) {
      puVar17 = *(undefined4 **)(iVar10 + -0x7fb0);
    }
    else {
      puVar17 = *(undefined4 **)(iVar10 + -0x7fb0);
      (*(code *)**(undefined4 **)(*(int *)*puVar17 + 0x1c))((int *)*puVar17,*piVar23);
    }
    puVar17 = (undefined4 *)
              (*(code *)**(undefined4 **)(*(int *)*puVar17 + 0x18))((int *)*puVar17,0x18,0x10);
    *piVar23 = (int)puVar17;
    puVar7 = *(undefined1 **)(iVar10 + -0x7c54);
    *puVar17 = 1;
    *(undefined4 *)(*piVar23 + 4) = 0xc;
    iVar11 = *piVar23;
    uVar1 = puVar7[1];
    uVar2 = puVar7[2];
    uVar3 = puVar7[3];
    *(undefined1 *)(iVar11 + 8) = *puVar7;
    *(undefined1 *)(iVar11 + 9) = uVar1;
    *(undefined1 *)(iVar11 + 10) = uVar2;
    *(undefined1 *)(iVar11 + 0xb) = uVar3;
    uVar1 = puVar7[5];
    uVar2 = puVar7[6];
    uVar3 = puVar7[7];
    *(undefined1 *)(iVar11 + 0xc) = puVar7[4];
    *(undefined1 *)(iVar11 + 0xd) = uVar1;
    *(undefined1 *)(iVar11 + 0xe) = uVar2;
    *(undefined1 *)(iVar11 + 0xf) = uVar3;
    uVar1 = puVar7[9];
    uVar2 = puVar7[10];
    uVar3 = puVar7[0xb];
    *(undefined1 *)(iVar11 + 0x10) = puVar7[8];
    *(undefined1 *)(iVar11 + 0x11) = uVar1;
    *(undefined1 *)(iVar11 + 0x12) = uVar2;
    *(undefined1 *)(iVar11 + 0x13) = uVar3;
    *(undefined1 *)(iVar11 + 0x14) = puVar7[0xc];
    *(undefined1 *)(puVar12 + 6) = 1;
  }
  puVar17 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x18,0x10);
  if (puVar17 != (undefined4 *)0x0) {
    piVar6 = puVar17 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar17 = *(undefined4 *)(iVar10 + -0x7d28);
    *piVar6 = 0;
    iVar11 = *(int *)(iVar11 + 4);
    if (iVar11 == 0) {
      *piVar6 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) {
        *piVar6 = 0;
      }
      else {
        puVar18 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar18;
        *puVar18 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
      }
    }
    piVar9 = puVar17 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d1c);
    *puVar17 = *(undefined4 *)(iVar10 + -0x7d20);
    piVar23 = (int *)*piVar9;
    iVar11 = *(int *)(iVar11 + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar9);
    }
    if (iVar11 == 0) {
LAB_000e7aa8:
      *piVar9 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e7aa8;
      puVar18 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar9 = (int)puVar18;
      *puVar18 = 1;
      *(int *)(*piVar9 + 4) = iVar16;
      func_0x00fe6bfc(*piVar9 + 8,iVar11);
    }
    piVar9 = puVar17 + 1;
    *puVar17 = *(undefined4 *)(iVar10 + -0x7d18);
    *(undefined1 *)(puVar17 + 5) = 1;
    puVar17[4] = 0;
    puVar17[2] = 0;
    puVar17[3] = 0;
    piVar23 = (int *)*piVar9;
    iVar11 = *(int *)(*(int *)(iVar10 + -0x7d14) + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar9);
    }
    if (iVar11 == 0) {
LAB_000e7b28:
      *piVar9 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e7b28;
      puVar18 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar9 = (int)puVar18;
      *puVar18 = 1;
      *(int *)(*piVar9 + 4) = iVar16;
      func_0x00fe6bfc(*piVar9 + 8,iVar11);
    }
    uVar15 = *(undefined4 *)(iVar10 + -0x7c4c);
    *puVar17 = *(undefined4 *)(iVar10 + -0x7c50);
    uVar8 = *(undefined4 *)(iVar10 + -0x7c44);
    *(undefined1 *)(puVar17 + 5) = 1;
    puVar17[2] = 0;
    puVar17[3] = uVar15;
    puVar17[4] = uVar8;
    piVar23 = (int *)*piVar6;
    iVar11 = *(int *)(*(int *)(iVar10 + -0x7c3c) + 4);
    if ((piVar23 != (int *)0x0) && (iVar16 = *piVar23, *piVar23 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar6);
    }
    if (iVar11 != 0) {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 != 0) {
        puVar18 = (undefined4 *)
                  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                            ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
        *piVar6 = (int)puVar18;
        *puVar18 = 1;
        *(int *)(*piVar6 + 4) = iVar16;
        func_0x00fe6bfc(*piVar6 + 8,iVar11);
        goto LAB_000e7bac;
      }
    }
    *piVar6 = 0;
  }
LAB_000e7bac:
  puVar12[2] = puVar17;
  puVar17 = (undefined4 *)
            (*(code *)**(undefined4 **)(*(int *)*puVar21 + 0x18))((int *)*puVar21,0x10,0x10);
  if (puVar17 != (undefined4 *)0x0) {
    piVar23 = puVar17 + 1;
    iVar11 = *(int *)(iVar10 + -0x7d24);
    *puVar17 = *(undefined4 *)(iVar10 + -0x7d28);
    *piVar23 = 0;
    func_0x00ff136c(piVar23,*(undefined4 *)(iVar11 + 4));
    iVar11 = *(int *)(iVar10 + -0x7cec);
    *puVar17 = *(undefined4 *)(iVar10 + -0x7cf0);
    puVar17[2] = 1;
    func_0x00ff136c(piVar23,*(undefined4 *)(iVar11 + 4));
    uVar15 = *(undefined4 *)(iVar10 + -0x7cd8);
    puVar17[3] = (float)dVar25;
    *puVar17 = uVar15;
    piVar6 = (int *)*piVar23;
    iVar11 = *(int *)(*(int *)(iVar10 + -0x7ccc) + 4);
    if ((piVar6 != (int *)0x0) && (iVar16 = *piVar6, *piVar6 = iVar16 + -1, iVar16 + -1 == 0)) {
      (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x1c))
                ((int *)**(undefined4 **)(iVar10 + -0x7fb0),*piVar23);
    }
    if (iVar11 == 0) {
LAB_000e7ca0:
      *piVar23 = 0;
    }
    else {
      iVar16 = func_0x00fe6c4c(iVar11);
      if (iVar16 == 0) goto LAB_000e7ca0;
      puVar21 = (undefined4 *)
                (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fb0) + 0x18))
                          ((int *)**(undefined4 **)(iVar10 + -0x7fb0),iVar16 + 0xc,0x10);
      *piVar23 = (int)puVar21;
      *puVar21 = 1;
      *(int *)(*piVar23 + 4) = iVar16;
      func_0x00fe6bfc(*piVar23 + 8,iVar11);
    }
    uVar15 = *(undefined4 *)(iVar10 + -0x7c5c);
    *puVar17 = *(undefined4 *)(iVar10 + -0x7c38);
    puVar17[3] = uVar15;
    puVar17[2] = 1;
  }
  func_0x0021ea10(puVar12,puVar17);
  func_0x0021df68(puVar14,puVar12);
  uVar15 = func_0x000b9e78(*piVar13,auStack_23c,0);
  func_0x008f820c(uVar15,puVar14);
  func_0x000ba110(*piVar13,*(undefined4 *)(iVar10 + -0x7c30),*(undefined4 *)(iVar10 + -0x7c2c));
  iVar11 = func_0x000b9e78(*piVar13,auStack_218,0);
  uVar15 = func_0x000b9e78(*piVar13,auStack_1f4,0);
  *(undefined4 *)(iVar11 + 0x48) = uVar15;
  uVar15 = func_0x000b9e78(*piVar13,auStack_1d0,0);
  func_0x008eca08(uVar15,1);
  uVar15 = func_0x000b9e78(*piVar13,auStack_284,0);
  func_0x008eb65c((double)*(float *)(iVar10 + -0x7c20),dVar24,uVar15,0,
                  *(undefined4 *)(iVar10 + -0x7c24));
  iVar11 = *piVar13;
  iVar16 = (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7fd4) + 0x18))
                     ((int *)**(undefined4 **)(iVar10 + -0x7fd4),0x28,0x10);
  if (iVar16 != 0) {
    func_0x008df28c(iVar16,*(undefined4 *)(iVar10 + -0x7c18),0x32);
  }
  func_0x000b941c(iVar11,iVar16);
  func_0x000ba110(*piVar13,*(undefined4 *)(iVar10 + -0x7c14),*(undefined4 *)(iVar10 + -0x7c10));
  func_0x0099a618();
LAB_000e8018:
  func_0x00c66efc(**(undefined4 **)(iVar10 + -0x7c0c),auStack_290);
  piVar13 = *(int **)(iVar10 + -0x7c04);
  func_0x00c31dc8((double)*(float *)(iVar10 + -0x7c00),(double)*(float *)(iVar10 + -0x7bf8),
                  (double)*(float *)(iVar10 + -0x7bf0),(double)*(float *)(iVar10 + -0x7be8),*piVar13
                 );
  func_0x00b3f4f0(auStack_28c);
  *(undefined1 *)(*piVar13 + 0x80) = 1;
  *(float *)(*piVar13 + 0x68) = (float)dVar25;
  (*(code *)**(undefined4 **)(*(int *)*piVar13 + 0x10))((int *)*piVar13,auStack_28c);
  iVar11 = func_0x00b3f7a4(auStack_28c,6,*(undefined4 *)(iVar10 + -0x7be0));
  if (iVar11 != 0) {
    func_0x00b335b0(iVar11,4);
  }
  iVar11 = func_0x00b3f7a4(auStack_28c,6,*(undefined4 *)(iVar10 + -0x7bdc));
  if (iVar11 != 0) {
    func_0x00b335b0(iVar11,0x14);
  }
  iVar11 = func_0x00b3f7a4(auStack_28c,0xc,*(undefined4 *)(iVar10 + -0x7bd8));
  if (iVar11 != 0) {
    func_0x00b3387c((double)*(float *)(iVar10 + -0x7bd4),iVar11);
  }
  iVar11 = func_0x00b3f7a4(auStack_28c,0xc,*(undefined4 *)(iVar10 + -0x7bcc));
  if (iVar11 != 0) {
    func_0x00b3387c((double)*(float *)(iVar10 + -0x7bc8),iVar11);
  }
  piVar13 = *(int **)(iVar10 + -0x7f70);
  iVar11 = *(int *)(*piVar13 + 0x1030);
  iVar16 = iVar11 + 8;
  if (iVar11 == 0) {
    iVar16 = *(int *)(iVar10 + -0x7ff4);
  }
  func_0x00fe6bbc(auStack_1a8,*(undefined4 *)(iVar10 + -0x7f68),iVar16);
  cVar22 = func_0x00b612a8(auStack_1a8);
  if (cVar22 != '\0') {
    *(undefined1 *)(param_1 + 0x18370) = 1;
  }
  iVar11 = *(int *)(*piVar13 + 0x1030);
  iVar16 = iVar11 + 8;
  if (iVar11 == 0) {
    iVar16 = *(int *)(iVar10 + -0x7ff4);
  }
  func_0x00fe6bbc(auStack_1a8,*(undefined4 *)(iVar10 + -0x7f6c),iVar16);
  cVar22 = func_0x00b612a8(auStack_1a8);
  if (cVar22 != '\0') {
    *(undefined1 *)(param_1 + 0x18371) = 1;
    *(undefined1 *)(param_1 + 0x18372) = 1;
  }
  (*(code *)**(undefined4 **)(*(int *)**(undefined4 **)(iVar10 + -0x7e90) + 0x28))
            ((int *)**(undefined4 **)(iVar10 + -0x7e90),*(undefined4 *)(iVar10 + -0x7bc0));
  piVar13 = *(int **)(iVar10 + -0x7f08);
  iVar11 = *piVar13;
  if ((*(char *)(iVar11 + 0x20) != '\0') || (**(char **)(iVar10 + -0x7e9c) != '\0')) {
    func_0x01399428(iVar11 + 8,0);
  }
  *(uint *)(iVar11 + 0x182dc) = *(uint *)(iVar11 + 0x182dc) & 0xfffffffd;
  if ((*(char *)(iVar11 + 0x20) != '\0') || (**(char **)(iVar10 + -0x7e9c) != '\0')) {
    func_0x01399448(iVar11 + 8);
  }
  iVar11 = *piVar13;
  if ((*(char *)(iVar11 + 0x20) != '\0') || (**(char **)(iVar10 + -0x7e9c) != '\0')) {
    func_0x01399428(iVar11 + 8,0);
  }
  *(uint *)(iVar11 + 0x182dc) = *(uint *)(iVar11 + 0x182dc) & 0xfffffffe;
  if ((*(char *)(iVar11 + 0x20) != '\0') || (**(char **)(iVar10 + -0x7e9c) != '\0')) {
    func_0x01399448(iVar11 + 8);
  }
  iVar11 = *piVar13;
  if ((*(char *)(iVar11 + 0x20) != '\0') || (**(char **)(iVar10 + -0x7e9c) != '\0')) {
    func_0x01399428(iVar11 + 8,0);
  }
  *(uint *)(iVar11 + 0x182dc) = *(uint *)(iVar11 + 0x182dc) & 0x7fffffff;
  if ((*(char *)(iVar11 + 0x20) != '\0') || (**(char **)(iVar10 + -0x7e9c) != '\0')) {
    func_0x01399448(iVar11 + 8);
  }
  iVar11 = *piVar13;
  if ((*(char *)(iVar11 + 0x20) != '\0') || (**(char **)(iVar10 + -0x7e9c) != '\0')) {
    func_0x01399428(iVar11 + 8,0);
  }
  *(uint *)(iVar11 + 0x182dc) = *(uint *)(iVar11 + 0x182dc) & 0xfffffff7;
  if ((*(char *)(iVar11 + 0x20) != '\0') || (**(char **)(iVar10 + -0x7e9c) != '\0')) {
    func_0x01399448(iVar11 + 8);
  }
  *(undefined4 *)(param_1 + 0x1836c) = 0;
  *(undefined4 *)(param_1 + 0x18368) = 0;
  func_0x00b3fb28(auStack_28c);
  return;
}


