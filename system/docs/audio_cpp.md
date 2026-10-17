# audio.cpp: local speech service (#816)

gBox can run [audio.cpp](https://github.com/mirek190/audio.cpp) as a second speech assistant on any gBox machine.
It handles text-to-speech and dictation when the Pine Box Voice Director is busy or down. You can also make it the
default assistant. Code: `gbox/audio_cpp.py` (service, client, worker tool) and `gbox/speech.py` (routing).

## What it is

| | |
|---|---|
| Upstream | github.com/mirek190/audio.cpp (a fork of 0xShug0/audio.cpp), branch `release-0.1` |
| Reviewed at | `73c5554950896ce36864b6da2fb3e129c429a8a7` (2026-10-10, "Document PocketTTS French packages and clean up model table") |
| Licence | Apache-2.0, "Copyright 2026 ShugoAI LLC". Models carry their own licences (upstream `docs/model_licenses.md`). Kokoro-82M is Apache-2.0 and Qwen3-ASR is Apache-2.0. Some community packages are CC-BY-NC, so check before you add them to `[audio_cpp] models`. |
| Binary | `audiocpp_server`, a C++/ggml HTTP server with an OpenAI-style API. Backends: CUDA (fastest), Vulkan, CPU, Metal. |
| Used routes | `GET /health`, `POST /v1/audio/speech` (JSON in, WAV out), `POST /v1/audio/transcriptions` (multipart WAV in, `{"text"}` out), `GET /v1/audio/voices?model=` |

gBox does not bundle or build audio.cpp. It finds the binary, writes the binary's config, starts the binary and keeps
it alive. If the binary is missing, nothing changes: `/api/tts` and `/api/stt` take the Voice Director path exactly as
before.

## Build and install (not run by gBox; do this once per machine)

Windows (Visual Studio Build Tools 2022 with the C++ workload, CMake, Ninja and the CUDA Toolkit):

```powershell
git clone https://github.com/mirek190/audio.cpp C:\_tools\audio.cpp
cd C:\_tools\audio.cpp
.\scripts\build_windows.ps1 -Preset windows-cuda-release -Target audiocpp_server -Jobs 16
# models: the native manager needs -NativeModelManager (or use: python tools\model_manager_v2.py install <package>)
.\scripts\build_windows.ps1 -Preset windows-cuda-release -NativeModelManager -Target audiocpp_model_manager -Jobs 16
.\build\windows-cuda-release\bin\audiocpp_model_manager.exe install kokoro_82m_q8_0     --models-dir D:\gBox\runtime\audio_cpp\models
.\build\windows-cuda-release\bin\audiocpp_model_manager.exe install qwen3_asr_0_6b_q8_0 --models-dir D:\gBox\runtime\audio_cpp\models
```

Use `-Preset windows-vulkan-release` for a non-NVIDIA GPU and `windows-cpu-release` when there is no GPU.

Linux (for example the Spark: CUDA and CMake):

```bash
git clone https://github.com/mirek190/audio.cpp ~/audio.cpp && cd ~/audio.cpp
cmake -S . -B build -DENGINE_ENABLE_CUDA=ON -DAUDIOCPP_BUILD_NATIVE_MODEL_MANAGER=ON
cmake --build build --parallel --target audiocpp_server audiocpp_model_manager
build/bin/audiocpp_model_manager install kokoro_82m_q8_0     --models-dir <runtime>/audio_cpp/models
build/bin/audiocpp_model_manager install qwen3_asr_0_6b_q8_0 --models-dir <runtime>/audio_cpp/models
```

Packages install into `Kokoro-82M-GGUF/kokoro-82m-q8_0.gguf` and `Qwen3-ASR-0.6B-GGUF/qwen3-asr-0.6b-q8_0.gguf`
under the models folder. gBox finds both on its own. The 1.7B ASR package (`qwen3_asr_1_7b_q8_0`) is also found, and
gBox prefers it when both are installed.

## Configuration (`gbox.toml`, or the per-machine `gbox.local-<host>.toml`)

```toml
[voice]
default_assistant = "director"   # or "audio_cpp": audio.cpp answers first
fallback = true                  # the other assistant takes a request when the default is busy or down
director_slots = 1               # Director requests (per kind: tts / stt) served at once; more go to audio.cpp in parallel
down_cooldown_s = 20             # after a Director failure, requests skip it for this long

[audio_cpp]
enabled = true
# binary = "C:/_tools/audio.cpp/build/windows-cuda-release/bin/audiocpp_server.exe"   # unset = discovered
# search = ["D:/builds/audio.cpp"]   # extra folders searched for the binary
# url = "http://10.0.0.5:8790"       # use a server gBox does not manage (start/stop do nothing)
port = 8790
gpu = true                       # cuda; gpu = false for cpu
# backend = "vulkan"             # explicit backend wins over gpu
# models_dir = "D:/gBox/runtime/audio_cpp/models"   # default <runtime>/audio_cpp/models
tts_family = "kokoro_tts"
tts_voice = "af_heart"
stt_family = "qwen3_asr"
stt_language = "en"
# tts_model / stt_model = explicit paths (relative = under models_dir)
# models = [{ id = "pocket", family = "pocket_tts", path = "...", task = "tts" }]   # extra server.json entries
busy_timeout_ms = 20000          # audio.cpp answers 503 instead of queueing longer; gBox then uses the other assistant
autostart = true                 # start with the worker and the control plane when the binary is on this machine
```

When `binary` is not set, gBox looks for `audiocpp_server` on PATH, then under `<runtime>/audio_cpp`, `~/audio.cpp`
and `C:/_tools/audio.cpp` (Windows), in `bin/`, `build/bin/` and `build/<preset>/bin/`. Release builds are preferred.
audio.cpp runs with its checkout (the folder with `model_specs/`) as its working folder.

gBox writes `<runtime>/audio_cpp/server.json` and starts `audiocpp_server [args] --config server.json`. The server's
output goes to `<runtime>/audio_cpp/server.log`. A supervisor restarts the server if it exits, with a backoff from 5 s
up to 5 min. If another gBox process on the same machine already serves the port (for example `serve` and `worker` as
separate processes), gBox adopts that server and never stops it.

## Routing

`/api/tts` and `/api/stt` call `speech.route_tts` and `speech.route_stt`:

1. If audio.cpp is unavailable (no binary, no models or disabled), the request takes the old Director path unchanged:
   the Director, then Piper for speech, and Wyoming whisper for dictation.
2. Otherwise the default assistant goes first. The default is the runtime setting from `PUT /api/voice/default`, or
   else `[voice] default_assistant`.
3. If the Director is the default and all of its `director_slots` are taken, a new request goes to audio.cpp in
   parallel and does not queue. The same happens for every request during the Director's failure cooldown.
4. If audio.cpp is the default, a cold start is awaited for up to `start_timeout_s`. If audio.cpp answers 503 or is
   down, the Director takes the request.
5. For speech, Piper is still the last resort.

Voices: `audio_cpp:<voice>` always goes to audio.cpp. `kokoro:<voice>` maps to the same Kokoro voice in audio.cpp. A
cloned XTTS voice (`xtts:vl_…`) uses audio.cpp's `tts_voice` when audio.cpp has to take the request. When audio.cpp is
available, `/api/voice/voices` adds an "audio.cpp · local" group, and the clients' voice pickers show it unchanged.

## API and tool

- `GET /api/voice/assistants`: the default, the fallback rule, the Director endpoints, the audio.cpp status and the
  routing counters (`served`, `last`, `active`, `down`).
- `PUT /api/voice/default {"assistant": "audio_cpp" | "director" | null}`: sets the default at runtime (stored in the
  gBox DB; `null` returns to gbox.toml). Returns 409 when audio.cpp can't serve on this machine.
- `GET /api/audio_cpp/status`, `POST /api/audio_cpp/start`, `POST /api/audio_cpp/stop`: control the control plane's own server.
- `/api/stt` now also returns `"assistant"`. `/api/tts` still reports the speaker in `x-gbox-tts-engine` (`audio_cpp`
  when audio.cpp spoke).
- The `audio_cpp` worker tool (typed, audited job) runs on any worker that has the binary:
  `op=status | start | stop | speak (text, voice, speed → speech.wav artifact) | transcribe (audio_b64 | audio_path, language)`.
  A worker without the binary lists the tool under `unavailable` and gives the reason.

## Live check (run by hand on a machine with the binary and models)

```bash
python -m gbox submit audio_cpp '{"op":"start"}'                                  # status.healthy == true
python -m gbox submit audio_cpp '{"op":"speak","text":"gBox speech check","voice":"af_heart"}'   # artifact speech.wav
curl -s -H "authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/voice/assistants   # audio_cpp.available/healthy
curl -s -X PUT -H "authorization: Bearer $TOKEN" -H "content-type: application/json" \
     -d '{"assistant":"audio_cpp"}' http://127.0.0.1:8765/api/voice/default
curl -s -H "authorization: Bearer $TOKEN" -H "content-type: application/json" \
     -d '{"text":"Hello from audio dot cpp"}' -D - -o check.wav http://127.0.0.1:8765/api/tts   # x-gbox-tts-engine: audio_cpp
curl -s -H "authorization: Bearer $TOKEN" --data-binary @check.wav http://127.0.0.1:8765/api/stt   # {"text": "...", "assistant": "audio_cpp"}
```

Set the default back with `{"assistant": null}`. To check the busy fallback, keep the default as `director`, start a
long XTTS reply, and send a second `/api/tts` while it plays. The second request reports `x-gbox-tts-engine:
audio_cpp`, and `routing.served` counts both.

Tests use a fake `audiocpp_server` (`tests/fake_audiocpp_server.py`): `python -m pytest tests/test_audio_cpp.py -q`.
