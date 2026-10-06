# Blender bridge

Status: **written, not run.** Blender isn't installed on the build host.

Flow of `open_in_blender {package_dir}`:

1. Validate the UAP.
2. Convert it to glTF.
3. Run headless Blender with the bridge script:

   ```
   blender --background --factory-startup --python clients/blender/gbox_bridge.py -- model.gltf scene.blend report.json unit_scale
   ```

4. The script imports the file, scales root objects from game units to metres, tags each object with `gbox_source`, saves `scene.blend` and reports objects, vertex/bone counts and actions.
5. The control plane validates the counts against the UAP.

Not yet built: a live addon/socket bridge, reimport without duplication, and select/highlight.
