# Game-only Picture-in-picture

Choose **Picture-in-picture** in a running game's menu, or use the PiP button in the GBox title bar. GBox shrinks its existing window to an always-on-top emulation display and hides the library, navigation, side panels, chat bar and title controls.

Drag a window edge or corner to resize it. The game retains its aspect ratio. Move the pointer to the top edge to reveal a small drag strip and **Full app** button. Double-click the game, or click **Full app**, to restore GBox's prior size, position and window state.

This applies to local native windows, the GPU compositor and streamed sessions. It keeps the selected session and controller target, rather than starting a second emulator or changing the game state. A session ending restores the application; a temporary API outage leaves the presentation intact.

Local games retain their existing rendering and input backend. Streamed games use the same authenticated MJPEG session feed with reconnect handling, and adopt the received frame's proportions. During an intermediate resize the frame is fitted with letterboxing instead of stretching.

The legacy small panel used while browsing away from a game remains a separate browsing behavior. The explicit **Picture-in-picture** action always selects the game-only application window.

Changes to the desktop main process require an idle GBox refresh. Activation waits while an emulator, recording, conversation or worker task is active; no running game is closed to apply this interface change.
