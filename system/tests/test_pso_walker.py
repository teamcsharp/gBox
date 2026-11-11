"""CP17: the walker's control loop against a simulated world - calibration, straight lines, corners, floors, failures."""
import pytest

from gbox.pso_walker import Walker

SPEED = 20.0            # world units per second of held stick


class World:
    """A fake player: `press` moves it along the stick's world direction, `read_position` reports (x, y, z)."""

    def __init__(self, forward=(0.0, -1.0), floor=1, floor_after=None, z_threshold=None):
        self.pos = [0.0, 0.0, 0.0]
        self.forward = list(forward)
        self.presses = []
        self.floor = floor
        self.floor_after = floor_after
        self.z_threshold = z_threshold
        self.stuck_after = None          # press count after which the player cannot move (a wall)

    def read_position(self):
        return tuple(self.pos)

    def read_floor(self):
        if self.floor_after is not None and self.z_threshold is not None and self.pos[2] < self.z_threshold:
            self.floor = self.floor_after
        return self.floor

    def press(self, keys, seconds):
        self.presses.append((tuple(keys), seconds))
        if self.stuck_after is not None and len(self.presses) > self.stuck_after:
            return
        fx, fz = self.forward
        rx, rz = -fz, fx
        dx = dz = 0.0
        for key in keys:
            if key == "up":
                dx, dz = dx + fx, dz + fz
            elif key == "down":
                dx, dz = dx - fx, dz - fz
            elif key == "right":
                dx, dz = dx + rx, dz + rz
            elif key == "left":
                dx, dz = dx - rx, dz - rz
        self.pos[0] += dx * SPEED * seconds
        self.pos[2] += dz * SPEED * seconds


def make(world: World, **kw) -> Walker:
    return Walker(world.read_position, world.press, **{"read_floor": world.read_floor, **kw})


def test_calibration_reads_forward_from_a_tap():
    world = World(forward=(1.0, 0.0))               # the stick's up means +x in this world
    walker = make(world)
    forward = walker.calibrate()
    assert forward == pytest.approx((1.0, 0.0), abs=1e-6)


def test_a_straight_walk_arrives_with_forward_taps():
    world = World()
    walker = make(world)
    result = walker.walk_to((0.0, -60.0))
    assert result["arrived"] is True
    assert world.presses and all(keys == ("up",) for keys, _ in world.presses)


def test_a_corner_turns_and_still_arrives():
    world = World()
    walker = make(world)
    result = walker.walk_to((40.0, -40.0))
    assert result["arrived"] is True
    uses_up = any("up" in keys for keys, _ in world.presses)
    uses_right = any("right" in keys for keys, _ in world.presses)
    assert uses_up and uses_right


def test_a_floor_change_stops_the_walk():
    world = World(floor=1, floor_after=2, z_threshold=-30.0)
    walker = make(world)
    result = walker.walk_to((0.0, -90.0))
    assert result["arrived"] is False
    assert "floor changed" in result["why"]
    assert result["floor"] == 2


def test_an_unreachable_target_gives_up():
    world = World()
    world.stuck_after = 2                                # it moves once (calibration), then it is against a wall
    walker = make(world, max_legs=5)
    result = walker.walk_to((1000.0, 1000.0))
    assert result["arrived"] is False
    assert "gave up" in result["why"]


def test_a_failed_calibration_is_reported():
    world = World()
    world.read_position = lambda: (5.0, 0.0, 5.0)     # static: pressing up changes nothing
    walker = Walker(world.read_position, world.press, read_floor=world.read_floor)
    result = walker.walk_to((100.0, 100.0))
    assert result["arrived"] is False
    assert "calibration failed" in result["why"]
