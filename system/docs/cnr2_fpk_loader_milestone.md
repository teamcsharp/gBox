# CNR2 FPK loader - milestone report

CNR2 FPK loader milestone (PARTIAL). Fixed the Wii DOL header parser in gbox/cnr2_dol.py: the previous field offsets were wrong, which made main.dol look like a non-DOL/encrypted blob. Verified against /home/ehm_eckx/gBox_alt/gbox-cache/modbase/00063327fc44eced/disc/DATA/sys/main.dol: valid Wii DOL, size 0x2ea060, self-consistent header (text0 @0x100, sections contiguous through data7, ending exactly at EOF). Probe: '%s.fpk' at 0x802ade88 has 56 code xrefs inside functions 0x80031028-0x80031a64; 'fpack/chr/%s/' at 0x802b044a has no direct lis/addi code xref and no data-section pointer. Tests: 24 passed, 4 skipped. NOT YET PROVEN: the loader's checksum verification and the stored==size raw-member acceptance branch, so gbox/cnr2.py raw-storage path is UNCHANGED and no raw storage was added to gameplay. Next: Ghidra script job on worker 3ebc340808d448a2 (project from job bf70d769f0c341b1) to decompile 0x80031028-0x80031a64 and read the checksum compare + stored==size branch.

## Changed files
- system/gbox/cnr2_dol.py - correct DOL header offsets + PPC xref probe
- system/tests/test_cnr2_dol.py - fix needle-length assertion
- system/docs/cnr2_fpk_loader_milestone.md - this report
