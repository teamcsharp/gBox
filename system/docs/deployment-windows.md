# Windows deployment

Tested on Windows 11, Python 3.11.

- **Standalone:** `pip install -e .`, then `gbox init`, then `gbox serve --worker`. Everything runs locally.
- **Node for the DGX Spark control plane:** `set GBOX_TOKEN=<token>` then `gbox worker --server http://<spark>:8765 --name win-node`. The node advertises Windows-only tools such as Steam launch, gdigrab frame capture and Blender.
- **Desktop app node (the usual Windows PC):** the gBox desktop app (`clients/desktop`, started from `gBox.exe`) runs this PC's worker itself. On launch `main.js` starts `python -P -m gbox.desktop_local --config <checkout>\gbox.toml --port 18765 --name <PC>` from `%LOCALAPPDATA%\gbox\venv`: a local control plane that hosts the worker in-process (Settings → "Start the Windows worker with the app") and pairs it with the Spark through the desktop bridge (`gbox/desktop_bridge.py`). There is no Windows service or scheduled task; the worker lives and dies with the app. When the Spark lists this PC offline for more than a minute, the app shows a quiet "Relaunch worker" badge (also under the PC's chip in the status bar): it asks the local service to stop while idle and starts it again with its worker; games keep running. Quitting and starting gBox does the same by hand. A session whose PC is offline is listed with that banner only; the app never opens, docks or reloads it.
- **Rebuild & relaunch from another gBox instance:** the PiP right-click menu and the Tasks PC panel offer "⟳ Rebuild & relaunch <PC>" for every online PC (`POST /api/workers/{name}/rebuild` queues the `rebuild_node` tool there; `gbox/node_rebuild.py`). On that PC it pulls a git checkout (a share copy has nothing to pull), reinstalls the bootstrap's pip packages and, when `clients/desktop/package.json` changed, the desktop app's npm packages, runs `gbox setup` as a self-check, then asks the desktop app over the worker's authenticated pipe to keep its games' moments and relaunch (the worker restarts with it). Refused while the operator plays a non-bot game there unless forced; bot sessions are saved and closed first. The requesting app shows the console (`GET /api/jobs/{jid}/console`), a loading bar and "Back online" when the worker returns.
- **Remote LLM:** add an `[[llm_endpoints]]` entry pointing at the Spark.
- **Streaming/control:** Sunshine (already installed on the dev box) plus Moonlight is the intended remote view/input path. It isn't wired into gBox yet.
- **Packaged exe:** not built yet. PyInstaller is available. Untested candidate command:

  ```
  pyinstaller -n gbox --add-data "clients;clients" --add-data "adapters;adapters" gbox/__main__.py
  ```
