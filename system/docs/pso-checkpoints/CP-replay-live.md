CP imitation on the live path: replaying the operator's recorded play through the keyboard input

The learned mission (gbox.pso_learn_play) is a pad-level timeline - 3447 steps, 1793 presses, 1654 waits, 658 seconds of recorded
pacing, top keys down/right/x/a/left/up. win_send_keys maps those same pad names to Dolphin's keyboard bindings, so replaying it
through the working input path is faithful at the input level: "a" is the A button the adapter itself would send.

Measured: 500 steps, 438 events, 87 s at 0.5x, with captures every 60 s. The character moved and acted in Forest 1.

The honest caveat: the timeline was recorded from a different game state (the operator was in Pioneer 2 at Lv 1), so replaying it in
Forest 1 cannot reproduce their journey - the presses land on whatever context the game is in now. What works and is verified is the
pipeline: mission file -> pad-level press/wait -> Dolphin keyboard bindings -> the game reacts. To actually imitate the play, the
replay has to start from the same state and the same place, which is why the route mission (navigate) and the learned bursts
(imitate.learn) exist as separate artifacts rather than one press stream.
