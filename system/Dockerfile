# Control plane (+ optional worker) for Linux hosts such as the NVIDIA DGX Spark (arm64; python:3.12-slim is multi-arch).
# Emulators/GPU/debuggers usually run on the host as separate workers: `gbox worker --server http://<host>:8765`.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY gbox ./gbox
COPY clients ./clients
COPY adapters ./adapters
RUN pip install --no-cache-dir .
# Mount config at /config/gbox.toml and persistent state at /data (set data_dir = "/data" in the toml).
ENV GBOX_CONFIG=/config/gbox.toml
EXPOSE 8765
CMD ["python", "-m", "gbox", "serve"]
