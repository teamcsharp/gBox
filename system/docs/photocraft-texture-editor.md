# PhotoCraft images and model textures

GBox embeds the local web build of [PhotoCraft](https://github.com/storytold/photocraft) in a popup. PhotoCraft provides the 2D image and layered project editor. GBox supplies the adjacent 3D preview and UV-aware texture painter, saved texture revisions on Spark, and export to a separate model asset for mod mapping.

## Edit an image or model texture

Open the PhotoCraft action for an image or collection model. For a model, choose its **Color map** and click **Open texture**. The popup loads the actual collection model and the selected base-color image. Its material list identifies surfaces that share that image; editing a shared image affects all of those surfaces.

In the 3D / UV pane:

1. Enable **Paint on model** to paint the mesh using its real texture coordinates. Turn it off to orbit the model.
2. Choose a color, radius and opacity. **Erase to original**, **Mask: hide edit**, and **Mask: reveal edit** adjust how the edited texture blends with its original.
3. Use the 2D texture canvas and **UV wire** to locate the painted area. **Show original**, **Undo**, and **Redo** help compare the result.

Brush strokes update the GBox model preview immediately. **Send current texture to PhotoCraft** opens the current flattened texture in the 2D editor for its image editing tools.

PhotoCraft does not expose its document pixels continuously to GBox. After editing there, choose **File → Export → Quick Export as PNG**. GBox captures that export and updates the selected image / 3D texture preview. If the exported filename no longer identifies the selected texture, review the selection and click **Use exported PNG on this texture** to assign it explicitly. The PNG must retain the original texture's dimensions.

This is GBox painting a model beside PhotoCraft; it does not add a native 3D editor inside the upstream PhotoCraft application.

## Save and reopen

**Save texture / project** writes an immutable texture revision to Spark. The original image and model remain available. Save does not modify a running game or overwrite its ROM.

To retain PhotoCraft's editable layers, export a **PSD** or **.pcraft** project from PhotoCraft, then click **Save texture / project**. A PNG export alone is a flattened image. When reopening **Saved projects**, GBox loads the stored layered project when one was saved, otherwise its saved PNG. Recent project IDs are remembered in that browser; the saved data itself resides on Spark.

**Download PNG** downloads the flattened texture. **Download layered project** is available after a PSD / .pcraft export was captured or saved. The server stores layered projects as opaque files; it does not execute or unpack them. The GBox 3D brush's undo stack and separate interactive mask are local editing state; saving its flattened PNG does not turn those controls into PhotoCraft layers.

Close or Escape exits the popup. GBox asks before discarding unsaved texture edits or a captured layered project.

## Use the edited texture in a mod

For a collection model, choose **Save as mod-mapping asset**. GBox saves the edited maps and combines their selected revisions into one new GLB donor in the model library. It retains the original geometry, UVs, skeleton and embedded animation data, and changes the selected base-color bindings. Normal, data and unselected color maps remain bound to their original images. Existing selfie tags carry into the new asset.

**Map edited asset** opens the existing mod mapping workflow with that new donor. Building or applying it still requires a writer for the exact target game, platform and revision. An editable collection GLB is not evidence that a game's native texture archive, palette, compression or resident GPU texture can be rewritten directly. This popup does not issue raw memory writes, replace arbitrary native files, or claim a build was verified in gameplay.

PSO's verified live face editor and DOA2's native face recipe editor remain separate native workflows. This integration does not bypass their inspection, native codec, preview, and apply / build checks. Use a supported donor-to-game writer, or export the edited PNG for the appropriate native workflow.

## Limits and storage

| Resource | Limit |
| --- | --- |
| Flattened texture | PNG, up to 16 MiB, 4096 pixels per edge and 16 megapixels |
| Saved texture dimensions | Must exactly match the original image |
| Source image | PNG, JPEG or WebP; normalized to RGBA PNG |
| Layered project export | PSD or .pcraft, up to 32 MiB |
| Source / edited GLB | Up to 64 MiB |
| Saved draft | Up to 256 revisions and 256 MiB of unique referenced artifacts |
| Maps combined into one donor | Up to 128, from the same unchanged source model |

If a draft reaches its revision or byte limit, earlier work remains intact. Download the project or export the asset, then open another draft. GBox does not silently remove saved revisions to make room. These are per-draft bounds rather than a quota for all library and build storage.

The initial model-image workflow targets readable standard glTF base-color images. It does not edit normal, roughness or other data maps, reconstruct geometry, or provide a general native-ROM hex / texture writer. Unsupported compressed image formats need conversion through an appropriate asset workflow first. Reopening a model that changed after inspection requires a fresh draft before donor export.

## Install the pinned local runtime

Run from the server's `system` directory using its Python environment:

```sh
python scripts/install_photocraft.py
```

For the Spark environment, for example:

```sh
.venv-linux-aarch64/bin/python scripts/install_photocraft.py
```

If the server uses a different data directory, provide `--data-dir /path/to/data`. To install from a previously downloaded release archive, use `--archive /path/to/photocraft-web-0.9.0.zip`. The same verification applies to a local archive.

The integration pins **PhotoCraft v0.9.0**, upstream commit `c699e3cda69f4852b43c0b191ab0091aaeff9d6a`. Its official web archive is **11,467,035 bytes** (about 11.5 MB / 10.9 MiB). The installer verifies its SHA-256, the complete file list, and each extracted file against [the runtime manifest](../gbox/photocraft_runtime.json). It copies only that exact file list into `gbox-data/photocraft/runtime/v0.9.0`, using atomic file replacement after verification. It does not build Rust, install global packages or restart services. PhotoCraft is dual-licensed **MIT OR Apache-2.0**; both upstream license files are installed with the runtime.

The installer contacts GitHub to download the runtime once. Images, models and projects are processed by the local browser and authenticated GBox server; this integration does not upload them to an external image editing service. Saved revisions and exported donors use the configured GBox data / character library locations.

The browser needs WebAssembly and WebGPU or WebGL2. Upstream automatically falls back to WebGL2 where WebGPU is unavailable, including a plain-HTTP LAN connection. If the pinned runtime is missing or fails verification, the popup reports it unavailable instead of loading a different remote editor.

## API summary

Application endpoints require the normal GBox authentication token. Editing sessions are bound to the authenticated actor label and exact saved source / revision.

| Method and route | Purpose |
| --- | --- |
| `GET /api/photocraft/status` | Verify the installed pinned runtime and return its local URLs |
| `GET /api/characters/{slug}/photocraft/maps` | List editable base-color image indices, dimensions and exact material bindings |
| `POST /api/photocraft/sessions` | Open one collection image, image artifact or uploaded PNG |
| `GET /api/photocraft/sessions/{id}` | Reopen a draft with its originals and revision / project URLs |
| `POST /api/photocraft/sessions/{id}/revisions` | Save a PNG and optional opaque project, with `expected_revision` conflict checks |
| `POST /api/photocraft/sessions/{id}/donor` | Export one exact reviewed revision as a separate model donor |
| `POST /api/photocraft/donors` | Combine exact revisions of multiple images from the same model |
| `GET /photocraft/runtime/{filename}` | Serve only allowlisted, hash-verified vendor runtime / license files |

The public runtime route contains vendor files only. User images, projects and model artifacts remain behind authenticated API routes. Browser requests cannot supply filesystem paths, commands or native memory addresses through these editing endpoints.
