# RE4 VR (Quest/Oculus): deconstruction state

Source: `\\10.89.1.125\QuickSwap2\Emulation\Occulus\Resident Evil 4 VR (occulus).zip`, mounted read-only on the Spark as
`/mnt/gbox/quickswap2/Emulation/Occulus/Resident Evil 4 VR (occulus).zip`. Measured 2026-11-06.

## What the archive is

| entry | size | what it is |
|---|---|---|
| `com.Armature.VR4/VR4-Android-Shipping-arm64.apk` | 56,831,952 | the UE4 **Android arm64** shell: `lib/arm64-v8a/libUE4.so`, `libOVRPlugin.so`, `libovraudio64.so`, `classes.dex`, `assets/UE4CommandLine.txt` (`../../../VR4/VR4.uproject`) |
| `com.Armature.VR4/main.203.com.Armature.VR4.obb` | 4,278,854,071 | the game's content, a **plain zip** |
| `com.Armature.VR4/patch.203.com.Armature.VR4.obb` | 4,233,911,336 | a patch-level copy of the same layout |

9 files, 8.6 GB uncompressed. It is a **Quest (Android) VR** title, not a PC build.

## The content inside the main OBB

The OBB is a zip of the shipped UE4 project: **81 entries**, 80 under `VR4/Content`.

```
47 × .bk2   Bink movies (Mercs_Basics_*, Mercs_PM_Ada/Hunk/Krauser/Leon/Overview …)
18 × .pak   UE4 chunked paks
11 × .uasset + 4 × .mp4
```

The paks are Android dynamic-delivery chunks (ETC2 textures):

```
pakchunk0optional-Android_ETC2.pak   2,446,567,768   the bulk of the content
pakchunk1-Android_ETC2.pak              56,860,746
pakchunk1optional-Android_ETC2.pak     145,272,968
... chunks 2..8 plus optional variants
```

## It opens with gBox's own reader

`gbox.ue_pak.open_pak` reads them as they are (no tooling to install):

```
pakchunk1: 475 entries — 211 .uexp, 121 .umap, 90 .uasset, 53 .ubulk
  VR4/Content/Levels/BIO4/1st/r100/r100.umap
  VR4/Content/Levels/BIO4/1st/r100/r100_Cabin.umap
  VR4/Content/Levels/BIO4/1st/r100/r100_Exterior.umap
  ...
```

The original RE4 level names survive (`BIO4/1st/r100` is the village), so the asset tree is navigable by the same names
the other editions use.

## How far "made to work in the system" can go

* **Deconstructed / inventoried: yes.** The paks list and extract with existing code, and the same pipeline the goal asks
  for (inventory → view → replace) applies to UE4 assets here.
* **Played in MercMode on the Spark: no, not as it stands.** It is an arm64 **Android** app that needs `libOVRPlugin` and
  an OpenXR headset; the Spark is arm64 Linux with no Android userspace and no headset. Even with an Android runtime it
  is a VR title with no flat mode, so there is no picture an autoplay bot could read or steer. This is a different class
  of problem from RE4 Switch (which boots and plays under Citron).

## Next steps if it is pursued

1. Extract `pakchunk0optional` and inventory the character/mesh assets by path (the same listing that worked on chunk 1).
2. Decide the target: mod-pak asset replacement (a `.pak` override is how UE4 mods work — no full rebuild), which is
   reachable for *assets*, separately from the runtime question.
3. The runtime question (Android + OpenXR on the Spark) is its own project and should be decided before any of this is
   promised to play in MercMode.
