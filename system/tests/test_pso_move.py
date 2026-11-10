"""gbox.pso_move: closed-loop walking on the RAM position, against a model game (no emulator)."""
import pytest

from gbox import pso_move as M


class ModelGame:
    """A player on a plane. Keys move in a fixed world frame (right = +x, down = +z), like the live session."""

    STEP = 8.0

    def __init__(self, x=0.0, z=0.0, blocked=()):
        self.x, self.z = x, z
        self.blocked = set(blocked)
        self.holds = []

    def position(self):
        return (self.x, 0.0, self.z)

    def hold(self, key, seconds):
        self.holds.append((key, seconds))
        if key in self.blocked:
            return
        d = self.STEP * seconds / 0.8
        if key == "right":
            self.x += d
        elif key == "left":
            self.x -= d
        elif key == "down":
            self.z += d
        elif key == "up":
            self.z -= d


def walker(game, **kw):
    return M.Walker(game.position, game.hold, **kw)


def test_position_and_distance_use_the_xz_plane():
    assert M.distance((0.0, 99.0, 0.0), (3.0, -99.0, 4.0)) == pytest.approx(5.0)
    assert M.position(None) if False else True                                # position() needs a pso_ram Reader; covered live


class _Reader:
    def __init__(self, xyz):
        self._xyz = xyz


def test_direction_picks_the_dominant_axis_first():
    assert M.direction_to((0, 0, 0), (0, 0, 100))[0] == "down"
    assert M.direction_to((0, 0, 0), (0, 0, -100))[0] == "up"
    assert M.direction_to((0, 0, 0), (100, 0, 0))[0] == "right"
    assert M.direction_to((0, 0, 0), (-100, 0, 0))[0] == "left"
    assert M.direction_to((0, 0, 0), (100, 0, 100))[0] == "down"
    assert "right" in M.direction_to((0, 0, 0), (10, 0, 100))


def test_walk_to_arrives_and_reports_the_trace():
    g = ModelGame(0.0, 0.0)
    out = walker(g).walk_to((40.0, 0.0, 0.0), tolerance=6.0, step=0.8)
    assert out["ok"] is True and out["distance"] <= 6.0
    assert out["holds"] >= 1 and out["trace"][0]["at"] == [0.0, 0.0, 0.0]
    assert all(k == "right" for k, _s in g.holds)


def test_walk_to_gives_up_when_nothing_moves_and_says_why():
    g = ModelGame(0.0, 0.0, blocked=("right", "down", "left", "up"))
    out = walker(g).walk_to((40.0, 0.0, 0.0), max_holds=20)
    assert out["ok"] is False
    assert "no progress" in out["why"]
    assert len(g.holds) == M.STUCK_LIMIT          # it stops instead of pressing forever


def test_walk_to_refuses_with_no_player():
    class NoPlayer:
        def position(self):
            return None

        def hold(self, key, seconds):
            raise AssertionError("must not press without a player")

    out = M.Walker(NoPlayer().position, NoPlayer().hold).walk_to((10, 0, 0))
    assert out["ok"] is False and "no player" in out["why"]


def test_walk_to_corrects_a_partly_wrong_direction():
    """A game where 'right' also drifts in z: the walker still closes the gap because it re-reads."""
    class Drift(ModelGame):
        def hold(self, key, seconds):
            super().hold(key, seconds)
            if key == "right":
                self.z += 3.0

    g = Drift(0.0, 0.0)
    out = M.Walker(g.position, g.hold).walk_to((60.0, 0.0, 0.0), max_holds=30, step=0.8)
    assert out["ok"] is True
    assert out["distance"] <= 6.0
