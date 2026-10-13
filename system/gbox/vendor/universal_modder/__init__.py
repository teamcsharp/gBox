"""universal-modder, vendored (MIT, see LICENSE in this folder).

Upstream: https://github.com/rehan-remade/universal-modder
Pinned:   commit 5ba8150e27b4f1bf17ae19dcecdb2341e467885a (main, read 2026-10-12), package version 0.2.0

What is here (upstream path -> this folder), line endings normalised to LF:
  um/common.py                 -> common.py     die() raises UmError (no sys.exit in a worker); data_dir() honours HOME
  um/scan.py                   -> scan.py       CLI removed; PowerShell probe runs without a console window
  um/backup.py                 -> backup.py     CLI removed
  um/publish.py                -> publish.py    check() split into lint() (returns findings) + check(); CLI removed
  um/kb.py                     -> kb.py         only note parsing + search kept (no GitHub sync, note writing or PRs)
  um/sprite.py                 -> sprite.py     CLI removed
  um/comfy.py                  -> comfy.py      CLI removed
  um/render3d.py               -> render3d.py   render() takes blender / timeout / max_images; temp config deleted; CLI removed
  um/blender/render_sprites.py -> blender/render_sprites.py   unchanged (runs inside Blender)
  knowledge/index.json         -> knowledge_index.json         unchanged (field-note metadata, for offline search)
  skills/mod-any-game/references/safety.md and engines/*.md -> playbooks/   unchanged
Imports `from um.common` became `from .common`. Every change is marked with a "gBox:" comment.

Not vendored, and why (docs/universal_modder.md has the full list): um/fal.py (paid cloud API, uploads local files,
needs FAL_KEY), um/win.py + um/ps1 (input injection, process kill, launch, registry writes and an ffmpeg download:
gBox's own session tools cover screenshots, input and process control), um/video.py (showcase-video editor; gBox
has its own recording), um/cli.py, the agent skills/plugins, examples/ and the full knowledge/ notes (fetched on demand,
pinned to the commit above).

gBox's tools around this live in gbox/universal_modder.py.
"""

UPSTREAM = "https://github.com/rehan-remade/universal-modder"
COMMIT = "5ba8150e27b4f1bf17ae19dcecdb2341e467885a"
VERSION = "0.2.0"
LICENSE = "MIT"
