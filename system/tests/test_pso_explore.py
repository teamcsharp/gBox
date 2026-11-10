"""gbox.pso_explore: grid probing for archway exits, on a model city."""
from gbox import pso_explore as X


class City:
    """A room where walking past a given coordinate moves you to another room, like Pioneer 2's archways."""

    def __init__(self, start=(0.0, 0.0), room=10, exit_at=(-60.0, 0.0), next_room=20):
        self.pos = list(start)
        self.room = room
        self.exit_at = exit_at
        self.next_room = next_room
        self.walks = []

    def read(self):
        return tuple(self.pos)

    def room_of(self):
        return self.room

    def hold(self, keys, seconds):
        keys = [keys] if isinstance(keys, str) else list(keys)
        self.walks.append(tuple(keys))
        # any key moves 10 units per second in the direction it names, for this model
        for k in keys:
            if k == "up":
                self.pos[0] -= 10 * seconds
            elif k == "down":
                self.pos[0] += 10 * seconds
            elif k == "left":
                self.pos[1] += 10 * seconds
            elif k == "right":
                self.pos[1] -= 10 * seconds

    def check(self):
        if abs(self.pos[0] - self.exit_at[0]) < 12 and abs(self.pos[1] - self.exit_at[1]) < 12:
            self.room = self.next_room


def test_the_grid_is_ordered_nearest_first():
    pts = X.grid((0.0, 0.0), spacing=50.0, rings=2)
    assert len(pts) == 16
    d = [p[0] ** 2 + p[1] ** 2 for p in pts]
    assert d == sorted(d)


def test_the_probe_finds_an_archway_and_stops_there():
    city = City(exit_at=(-60.0, 0.0))

    def walk_to(read_pos, hold, target, tolerance=8.0, max_steps=10):
        for _ in range(max_steps):
            p = read_pos()
            dx, dz = target[0] - p[0], target[1] - p[1]
            if (dx * dx + dz * dz) ** 0.5 <= tolerance:
                return {"ok": True, "why": "arrived", "end": p}
            key = "up" if dx < 0 else "down"
            hold(key, 1.5)
            city.check()
        return {"ok": False, "why": "gave up", "end": read_pos()}

    out = X.probe(city.read, city.hold, city.room_of, X.grid((0.0, 0.0), spacing=50.0),
                  walk_to=walk_to, tolerance=8.0, max_steps=6)
    assert out["ok"] is True and out["start_room"] == 10
    assert out["transitions"][0]["room_after"] == 20
    assert out["transitions"][-1]["to"][0] < 0            # the exit was on the -x side


def test_a_probe_that_finds_nothing_says_so_without_raising():
    city = City(exit_at=(999.0, 999.0))

    def walk_to(read_pos, hold, target, tolerance=8.0, max_steps=4):
        hold("up", 0.2)
        return {"ok": False, "why": "blocked", "end": read_pos()}

    out = X.probe(city.read, city.hold, city.room_of, X.grid((0.0, 0.0), spacing=40.0, rings=1),
                  walk_to=walk_to)
    assert out["ok"] is False and "no exit" in out["why"]
    assert len(out["visited"]) == len(X.grid((0.0, 0.0), spacing=40.0, rings=1))


def test_every_visited_point_records_the_room_it_ended_in():
    city = City(exit_at=(999.0, 999.0))

    def walk_to(read_pos, hold, target, tolerance=8.0, max_steps=2):
        return {"ok": True, "why": "arrived", "end": read_pos()}

    out = X.probe(city.read, city.hold, city.room_of, [(10.0, 10.0), (20.0, 20.0)], walk_to=walk_to)
    assert [v["room_after"] for v in out["visited"]] == [10, 10]
    assert all(v["room_before"] == 10 for v in out["visited"])
