# Fast-forward recovery

The session header's fast-forward button highlights when gBox detects fast-forward. Clicking always requests normal speed through the audited live session RPC (`normal_speed`), never a toggle. It remains available for recovery when speed telemetry is unavailable. Adapters without fast-forward support hide the button.

The worker shares UI/agent and controller-ramp state. Clearing speed suppresses the current Select+R2 chord until released, including stale streamed button state. A new deliberate chord works again. Late UI reads cannot overwrite a completed off command; failures keep the indicator and allow retry.

RetroArch with `GET_OPTION fast_forward` reports the emulator's actual mode and uses verified `SET_OPTION fast_forward off`. Legacy versions report gBox's tracked state, which cannot detect native hotkey changes or a lost toggle. Their recovery briefly pauses, sends a fast-forward hold edge while paused, waits for the release, and restores the previous pause state. This clears a stale toggle without resetting or reloading the game. A hold pulse while playing is insufficient: legacy RetroArch toggles on both edges. See the official [legacy runloop](https://github.com/libretro/RetroArch/blob/v1.20.0/runloop.c) and [current command implementation](https://github.com/libretro/RetroArch/blob/master/command.c).

Dolphin releases its gBox speed-limit hotkey even when the cached state says off, and checks that Windows accepted the release. Its indicator reflects gBox's held hotkey, not speed settings changed independently in Dolphin.

Validation: `pytest tests/test_fast_forward_control.py tests/test_rewind.py tests/test_session_pause_rpc.py`; `node --test tests/test_session_speed.cjs tests/test_session_pause.cjs`. Isolated headless Edge verification exercises the actual header control, off RPC, success/error rendering, and unsupported/unknown status. Worker changes take effect after a worker restart; do not restart a worker while it owns a running game.
