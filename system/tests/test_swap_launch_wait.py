"""session_swap must outwait its replacement launch child so a launch that hits its own tool
timeout is always observed in a terminal state, never misreported as "launch_game failed: running".

#1731: a session_swap of Dead or Alive 2 - Limited Edition (Japan) waited exactly as long as the
child launch_game's own timeout (900 s). The child was killed by its TimeoutError a beat after the
parent's wait expired, so the parent read the job as still "running" and reported
"launch_game failed: running" instead of the real cause.
"""
from gbox import server
from gbox.registry import REGISTRY


def test_launch_game_registered_with_a_timeout():
    assert "launch_game" in REGISTRY
    assert REGISTRY["launch_game"].timeout_s > 0


def test_swap_launch_wait_exceeds_child_timeout():
    child = REGISTRY["launch_game"]
    assert server.SWAP_LAUNCH_MARGIN_S > 0
    # A bare wait (recovery launches) still outlasts the child's own timeout.
    assert server.swap_launch_wait_s() > child.timeout_s
    # The full swap wait covers the queue window on top of the child timeout.
    assert server.swap_launch_wait_s(server.SWAP_LAUNCH_QUEUE_S) > child.timeout_s + server.SWAP_LAUNCH_QUEUE_S


def test_swap_launch_wait_margin_covers_poll_interval():
    # The margin is comfortably larger than _run_job's 0.5 s poll interval, so the terminal
    # transition is always caught within at least a couple of polls.
    assert server.SWAP_LAUNCH_MARGIN_S >= 1.0
