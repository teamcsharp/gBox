"""gbox.pso_kbwalk.greedy_walk: walking without a camera model, by re-measuring each key's last effect."""
import math

from gbox import pso_kbwalk as B


class Camera:
    """A world where each key's world direction DRIFTS, as it does when the camera follows the character."""

    def __init__(self, start=(0.0, 0.0), speed=30.0, drift=0.06):
        self.pos = list(start)
        self.speed = speed
        self.drift = drift
        self.angle = 0.0                 # the camera's rotation, which changes as the character moves
        self.holds = []

    def read(self):
        return tuple(self.pos)

    def direction(self, key):
        base = {"up": 0.0, "down": math.pi, "left": math.pi / 2, "right": -math.pi / 2}[key]
        a = base + self.angle
        return (math.cos(a), math.sin(a))

    def hold(self, keys, seconds):
        keys = [keys] if isinstance(keys, str) else list(keys)
        self.holds.append((tuple(keys), round(seconds, 3)))
        for k in keys:
            dx, dz = self.direction(k)
            self.pos[0] += dx * self.speed * seconds
            self.pos[1] += dz * self.speed * seconds
        self.angle += self.drift        # the camera rotated a little while the character moved


def test_a_walk_arrives_although_every_key_drifts():
    cam = Camera(start=(0.0, 0.0))
    out = B.greedy_walk(cam.read, cam.hold, (90.0, 40.0), tolerance=7.0, max_steps=30)
    assert out["ok"] is True, out
    assert B.distance(out["end"], (90.0, 40.0)) <= 7.0


def test_it_learns_a_key_that_only_works_after_it_is_tried():
    """The bootstrap press is what makes the first choice possible; nothing is assumed before measuring."""
    cam = Camera(start=(10.0, 10.0))
    out = B.greedy_walk(cam.read, cam.hold, (-40.0, 10.0), tolerance=7.0, max_steps=25)
    assert out["ok"] is True
    assert len(cam.holds) >= 5                  # four bootstrap presses plus steps


def test_a_dead_binding_is_reported_not_looped():
    class Dead(Camera):
        def hold(self, keys, seconds):
            self.holds.append((tuple([keys]) if isinstance(keys, str) else tuple(keys), round(seconds, 3)))

    dead = Dead()
    out = B.greedy_walk(dead.read, dead.hold, (50.0, 0.0), max_steps=5)
    assert out["ok"] is False and "no key moved" in out["why"]


def test_a_blocked_key_loses_trust_and_another_is_tried():
    class Wall(Camera):
        """`up` is blocked; the walker must notice and use something else."""

        def hold(self, keys, seconds):
            keys = [keys] if isinstance(keys, str) else list(keys)
            if keys == ["up"]:
                self.holds.append((("up",), round(seconds, 3)))
                return
            super().hold(keys, seconds)

    wall = Wall(start=(0.0, 0.0))
    out = B.greedy_walk(wall.read, wall.hold, (0.0, 40.0), tolerance=9.0, max_steps=12)
    tried = {k for keys, _s in wall.holds for k in keys}
    assert "up" in tried and len(tried) > 1            # it did not keep hammering the blocked key
    assert len(out["steps"]) <= 12                     # and it stayed inside its step budget
    assert "why" in out
