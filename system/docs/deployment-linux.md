# Linux deployment — NVIDIA DGX Spark

Target: DGX Spark (GB10 Grace-Blackwell, **aarch64/arm64**, DGX OS = Ubuntu 24.04-based, 128 GB unified memory).
Status: **not yet deployed or tested on the Spark.** The steps below are the intended path.

Source deployment is manual: run `scripts/deploy_main.sh --deploy` after requesting an update, or add
`--no-restart` to copy files while deferring activation. Without `--deploy`, the script performs no fetch,
file transfer or restart, including pending restarts. Replace installed copies of the old script and remove
their cron entries; a repository change alone cannot disable an older installed deployment job.

"Rebuild & relaunch <PC>" in the desktop app (the PiP right-click menu and the Tasks PC panel; `POST
/api/workers/{name}/rebuild`, tool `rebuild_node`, `gbox/node_rebuild.py`) does not bypass this gate: on the Spark it
reports the deployed main commit and whether runtime code waits for a restart, reinstalls the venv's packages, runs
`gbox setup` as a self-check and then restarts `gbox.service` only after the same idle check the deploy uses (a busy
Spark defers; `force` restarts anyway). The requesting app shows the console (`GET /api/jobs/{jid}/console`) and waits
for the worker to come back.

## Control plane (bare metal)

```sh
sudo apt install -y python3-venv ffmpeg
python3 -m venv ~/gbox-venv && . ~/gbox-venv/bin/activate
pip install -e /path/to/gBox          # pure-Python deps; all have arm64 wheels
gbox init                             # set api_host = "0.0.0.0" for LAN access, plus library_paths
gbox serve --worker
```

systemd unit (`/etc/systemd/system/gbox.service`):

```ini
[Unit]
Description=gBox control plane
After=network-online.target remote-fs.target
[Service]
User=gbox
WorkingDirectory=/srv/gbox
Environment=GBOX_CONFIG=/srv/gbox/gbox.toml
ExecStart=/home/gbox/gbox-venv/bin/gbox serve --worker
Restart=on-failure
[Install]
WantedBy=multi-user.target
```

## Container

```sh
docker build -t gbox .     # python:3.12-slim is multi-arch, so this builds natively on arm64
docker run -d -v /srv/gbox:/config -v /srv/gbox-data:/data -p 8765:8765 gbox
```

In `/srv/gbox/gbox.toml`, set `data_dir = "/data"` and `api_host = "0.0.0.0"`. Emulators and GPU-heavy tools stay on the host as a separate `gbox worker`.

## NAS

Mount it read-only and point `library_paths` at the mount. For example, in `/etc/fstab`:

```
//nas/games  /mnt/games  cifs  ro,credentials=/etc/gbox-smb.cred,uid=gbox  0 0
```

NFS works the same way. The path is still to be supplied by the operator.

## Spark-specific notes (verify on hardware)

- **arm64:** x86-only emulators and tools won't run natively. RetroArch and Flycast have aarch64 Linux builds. Ghidra is Java (install JDK 21 for arm64). Check whether an arm64 Linux Blender build exists for the version you pick; otherwise run Blender on the Windows node.
- **Local LLMs:** the 128 GB unified memory makes the Spark the natural `llm_endpoints` host (Ollama or vLLM with the OpenAI-compatible API). Windows nodes then point their `llm_endpoints` at `http://<spark>:11434/v1`.
- **Headless display:** `get_frame` uses `x11grab` on `:0`. A headless Spark needs Xvfb (`Xvfb :0 &`) or a real session for emulator video.
- **PC/Steam games** run on the Windows node, not the Spark.
