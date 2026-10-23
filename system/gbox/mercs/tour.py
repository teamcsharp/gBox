"""Title-independent time-bonus tour over measured, directed travel costs.

No coordinates or links are inferred here. Missing paths stay unreachable. A bounded
beam search prefers collecting more bonuses while remaining inside the measured clock;
it accounts for time gained at each pickup instead of taking only the closest pickup.
"""
import math


class GoalCommitment:
    """Keep a checkpoint through combat and tour recalculation, with a bounded progress lease.

    The caller supplies currently reachable identifiers. A missing, collected or explicitly
    failed goal releases immediately. Distance is a measured route length for the *held*
    goal, not the newly proposed goal's distance. Combat pauses the progress lease.
    """
    def __init__(self, *, patience_s=12., improvement=80.):
        self.patience_s, self.improvement = patience_s, improvement
        self.goal = None
        self.best = math.inf
        self.progress_at = self.observed_at = None

    def reset(self):
        self.goal, self.best = None, math.inf
        self.progress_at = self.observed_at = None

    def pause(self, now):
        """Account for an observed frame owned by combat, an item or mandatory QTE."""
        if not math.isfinite(now):
            return
        if self.goal is not None and self.progress_at is not None and self.observed_at is not None:
            self.progress_at += max(0., now - self.observed_at)
        self.observed_at = now

    def choose(self, proposed, available_ids, now, distance=None, *, failed=False, advancing=True):
        available = set(available_ids)
        if not math.isfinite(now):
            return self.goal if self.goal in available else None
        if self.goal not in available or failed:
            self.reset()
        if self.goal is not None:
            # Time spent fighting, healing or in a QTE is not walking without progress.
            if not advancing and self.observed_at is not None and self.progress_at is not None:
                self.progress_at += max(0., now - self.observed_at)
            if distance is not None and math.isfinite(distance) and distance >= 0 \
                    and distance < self.best - self.improvement:
                self.best, self.progress_at = distance, now
            if advancing and self.progress_at is not None and now - self.progress_at >= self.patience_s:
                self.reset()
        if self.goal is None and proposed in available:
            self.goal, self.progress_at, self.best = proposed, now, math.inf
        self.observed_at = now
        return self.goal


def plan(goals, travel, start_cost, seconds, speed, *, width=32, pickup_s=.8):
    goals = tuple(goals)[:12]
    if not goals or not math.isfinite(seconds) or seconds <= 0 or not math.isfinite(speed) or speed <= 0:
        return []
    width = max(1, min(256, int(width)))
    # State: remaining time, total distance, indices in collection order.
    beam = [(seconds, 0., ())]
    best = beam[0]
    for _ in goals:
        candidates = []
        for budget, distance, path in beam:
            for i, goal in enumerate(goals):
                if i in path: continue
                d = start_cost(goal) if not path else travel(goals[path[-1]], goal)
                if d is None or not math.isfinite(d) or d < 0: continue
                arrival = budget - d/speed - pickup_s
                if arrival <= 1: continue
                gain = goal.get("seconds", 0)
                gain = gain if isinstance(gain, (int,float)) and math.isfinite(gain) and gain >= 0 else 0
                candidates.append((arrival + gain, distance+d, path+(i,)))
        if not candidates: break
        # Merge equivalent end/mask states before pruning.
        unique = {}
        for state in candidates:
            key=(frozenset(state[2]),state[2][-1])
            if key not in unique or state[0] > unique[key][0]: unique[key]=state
        beam=sorted(unique.values(),key=lambda s:(-s[0],s[1]))[:width]
        best=min(beam,key=lambda s:s[1])
    return [goals[i] for i in best[2]]
