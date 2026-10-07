# Windows deployment

Tested on Windows 11, Python 3.11.

- **Standalone:** `pip install -e .`, then `gbox init`, then `gbox serve --worker`. Everything runs locally.
- **Node for the DGX Spark control plane:** `set GBOX_TOKEN=<token>` then `gbox worker --server http://<spark>:8765 --name win-node`. The node advertises Windows-only tools such as Steam launch, gdigrab frame capture and Blender.
- **Remote LLM:** add an `[[llm_endpoints]]` entry pointing at the Spark.
- **Streaming/control:** Sunshine (already installed on the dev box) plus Moonlight is the intended remote view/input path. It isn't wired into gBox yet.
- **Packaged exe:** not built yet. PyInstaller is available. Untested candidate command:

  ```
  pyinstaller -n gbox --add-data "clients;clients" --add-data "adapters;adapters" gbox/__main__.py
  ```
