# Metal Gear Online / SaveMGO

The PS3 library scanner recognizes the owned portable package at
`\\10.89.1.125\QuickSwap2\Emulation\PS3\SaveMGO.zip` as **Metal Gear Online**.
Its identity stays tied to the `ps3` library and relative archive path, so Windows
PCs and the Spark catalogue refer to the same title.
The search index includes the alias **MGO**, so `metal gear`, `metal gear online`
and `mgo` find this same entry in Library and Home.

Play selects a Windows worker and uses the package's custom `rpcs3.exe`, with
`--no-gui` and `dev_hdd0/game/NPMG00010/USRDIR/EBOOT.BIN`, from its portable home.
The companion `NPMG00020` game data and bundled firmware/configuration stay with
that executable. Generic RPCS3 provisioning, updates, graphics/pad rewrites and
RenderDoc injection are bypassed. The existing `E:\_downloads\SaveMGO` copy is
left untouched.

On first use each PC hashes the complete archive, checks/extracts its files into
an unpublished local staging directory and atomically publishes a receipt-backed
home under `<runtime>/savemgo/<source fingerprint>`. The roughly 8.85 GB expansion
requires that much free disk plus a safety margin. Reading a NAS archive can take
several minutes. Later launches reuse the local home, rehash the runner and DLLs,
check critical game/firmware identity and validate cached bulk-file metadata.
Changed bulk files are rehashed. Changes to the source archive require a rescan.

Each PC retains its own mutable configuration, shader cache and user data. A
process-lifetime lease prevents two games sharing the same writable home on one
PC. Runtime homes on UNC shares or mapped network drives are rejected. No account
settings, saved games or credentials are included in asset extraction reports.
Normal native controller handling stays with the supplied emulator. Memory writes,
save-state rewind and draw-call capture are not advertised for this custom fork.

## Asset window

Right-click a title and choose its asset window. SaveMGO supports explicit
inspection and native resource export on a selected Windows PC. This prepares the
verified local source without starting a game. Sources are restricted to game
resources under `dev_hdd0/game/NPMG00020/USRDIR`; the boot executable alone does not
contain the game's assets.

The reader authenticates the encrypted DAR/QAR archives with their logical stage
paths and lists/exports native model, animation and texture members. Native MDN,
MTAR, TXN, SLOT and GEOM files remain native formats. Export does **not** imply
decoded GLB models, PNG textures, portable environments, working target-game
writers or tested cast replacements. The window reports these separately.
Music resources can be exported in their original BGM/DBM format. Optional music
decoding uses an already installed `vgmstream-cli`; it never downloads a decoder.

Selected exports receive a manifest and SHA-256 hashes in a separate immutable
bundle. Small bundles have a job-artifact ZIP download; large bundles stay on the
selected PC. Opening the window alone queues no extraction and uploads no game
data. Other titles keep their existing character extraction path; reader support
must be verified per format.

## Format references

- [Solideye](https://github.com/Jayveer/Solideye), MIT: MGS4/MGO2 archive layout,
  logical stage names and archive encryption/checksums.
- [MGS MDN Noesis plugin](https://github.com/Jayveer/MGS-MDN-Noesis): native model
  and animation tooling; this integration does not bundle Noesis or claim its
  conversions have been validated here.
- [vgmstream](https://github.com/vgmstream/vgmstream): MTA2 music decoding.

No game assets, firmware, emulator binaries, archive content keys tied to an
account, or personal configurations are distributed in this repository.
