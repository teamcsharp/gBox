"""A firing commitment measured independently of input requests.

Native cooldown re-arms are a lower bound on firearm discharges, not hits or
projectile counts. Missing observations never complete a burst.
"""
class Burst:
    def __init__(self, stats, goal=20, timeout=4.0):
        self.stats, self.goal, self.timeout = stats, goal, timeout
        self.identity = None
        self.started = None
        self.seen = self.requests = 0
        self.retry_at = 0.0

    def observe(self, identity, now, discharge=False):
        if identity != self.identity:
            self.end('life_or_round_changed')
            self.identity = identity
            self.retry_at = 0.0
        if discharge and self.started is not None:
            self.seen += 1
            self.stats['fire_burst_observed_discharges'] = self.seen
            self.stats['fire_burst_remaining'] = max(0, self.goal - self.seen)
            if self.seen >= self.goal:
                self.end('complete')
        self.active(now)

    def active(self, now):
        if self.started is not None and now - self.started >= self.timeout:
            self.end('discharge_confirmation_timeout')
            self.retry_at = now + 1.0
        return self.started is not None

    def begin(self, now):
        if not self.active(now) and now >= self.retry_at:
            self.started, self.seen, self.requests = now, 0, 0
            self.stats.update(fire_burst_goal=self.goal, fire_burst_remaining=self.goal,
                              fire_burst_observed_discharges=0, fire_burst_requests=0,
                              fire_burst_state='firing', fire_burst_evidence='native_cooldown_rearm_lower_bound')

    def requested(self):
        if self.started is not None:
            self.requests += 1
            self.stats['fire_burst_requests'] = self.requests

    def end(self, reason):
        if self.started is None:
            return
        self.stats['fire_burst_state'] = reason
        key = 'fire_bursts_completed' if reason == 'complete' else 'fire_bursts_interrupted'
        self.stats[key] = self.stats.get(key, 0) + 1
        self.started = None
