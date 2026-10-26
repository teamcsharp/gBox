# Windows deployment

Tested on Windows 11, Python 3.11.

- **Standalone:** `pip install -e .`, then `gbox init`, then `gbox serve --worker`. Everything runs locally.
- **Node for the DGX Spark control plane:** `set GBOX_TOKEN=<token>` then `gbox worker --server http://<spark>:8765 --name win-node`. The node advertises Windows-only tools such as Steam launch, gdigrab frame capture and Blender.
- **Rebuild & relaunch from another gBox instance:** the PiP right-click menu and the Tasks PC panel offer "⟳ Rebuild & relaunch <PC>" for every online PC (`POST /api/workers/{name}/rebuild` queues the `rebuild_node` tool there; `gbox/node_rebuild.py`). On that PC it pulls a git checkout (a share copy has nothing to pull), reinstalls the bootstrap's pip packages and, when `clients/desktop/package.json` changed, the desktop app's npm packages, runs `gbox setup` as a self-check, then asks the desktop app over the worker's authenticated pipe to keep its games' moments and relaunch (the worker restarts with it). Refused while the operator plays a non-bot game there unless forced; bot sessions are saved and closed first. The requesting app shows the console (`GET /api/jobs/{jid}/console`), a loading bar and "Back online" when the worker returns.
- **Remote LLM:** add an `[[llm_endpoints]]` entry pointing at the Spark.
- **Streaming/control:** Sunshine (already installed on the dev box) plus Moonlight is the intended remote view/input path. It isn't wired into gBox yet.
- **Packaged exe:** not built yet. PyInstaller is available. Untested candidate command:

  ```
  pyinstaller -n gbox --add-data "clients;clients" --add-data "adapters;adapters" gbox/__main__.py
  ```
