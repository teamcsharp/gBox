"""gbox.pso_kbwalk push-through: crossing a doorway instead of standing next to it."""
from gbox import pso_kbwalk as B


class DoorRoom:
    """A room where a doorway at x=-(60) is only crossed if the walk *passes* it; stopping on it stays put."""

    def __init__(self, start=(0.0, 0.0), speed=30.0, door_x=-60.0, room=10, next_room=20):
        self.pos = list(start)
        self.speed = speed
        self.door_x = door_x
        self.room = room
        self.next_room = next_room
        self.holds = []

    def read(self):
        return tuple(self.pos)

    def hold(self, keys, seconds):
        keys = [keys] if isinstance(keys, str) else list(keys)
        self.holds.append((tuple(keys), round(seconds, 3)))
        for k in keys:
            if k == "up":
                self.pos[0] -= self.speed * seconds
            elif k == "down":
                self.pos[0] += self.speed * seconds
            elif k == "left":
                self.pos[1] += self.speed * seconds
            elif k == "right":
                self.pos[1] -= self.speed * seconds
        # the doorway only moves you once you are clearly past its coordinate
        if self.pos[0] < self.door_x - 6:
            self.room = self.next_room


def test_without_push_through_a_door_is_missed_when_the_walk_stops_on_it():
    room = DoorRoom()
    out = B.greedy_walk(room.read, room.hold, (room.door_x, 0.0), tolerance=4.0, max_steps=12)
    assert out["ok"] is True                      # it "arrived" -- at the door's coordinate
    assert room.room == 10                        # and did not go through


def test_overshoot_keeps_walking_past_the_target_and_crosses():
    """A door that the walk *reaches* needs an overshoot: stopping on the coordinate is standing beside it."""
    room = DoorRoom()
    out = B.greedy_walk(room.read, room.hold, (room.door_x, 0.0), tolerance=4.0, max_steps=20,
                        overshoot=40.0)
    assert room.room == 20, out
    assert any("overshoot_to" in step for step in out["steps"])


def test_push_through_gives_up_after_its_budget():
    """A wall that never yields must not turn into an endless walk."""
    class Wall(DoorRoom):
        def hold(self, keys, seconds):
            self.holds.append((("up",), round(seconds, 3)))

    wall = Wall()
    out = B.greedy_walk(wall.read, wall.hold, (-60.0, 0.0), max_steps=6, push_through=True, pushes=2)
    assert out["ok"] is False and "no key moved" in out["why"]
