import ast
from pathlib import Path

root = Path(__file__).resolve().parents[2]
scratch = root / '.work/re5-live'
path = root / 'system/gbox/mercs/titles/re5_ps3.py'
local = path.read_text()
remote = (scratch / 'gbox_mercs_titles_re5_ps3.py.remote').read_text()

def methods(text):
    cls = next(n for n in ast.parse(text).body if isinstance(n, ast.ClassDef) and n.name == 'Bot')
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}

lm, rm = methods(local), methods(remote)
lines = local.splitlines(keepends=True)
extra = []
for name in ('_follow', '_traverse', '_recover_nav', '_block_route', '_remember_traversal_prompt'):
    node = rm[name]
    code = ''.join(remote.splitlines(keepends=True)[node.lineno-1:node.end_lineno])
    if name == '_follow':
        code = code.replace('stage_prompt, now) -> dict:', 'stage_prompt, now, learn=True) -> dict:')
        code = code.replace('self._following_route = True', 'self._following_route, self._route_learn = True, learn')
        code = code.replace('self.nav_learning.begin_route(mesh, pos, tgt["pos"])', 'self.nav_learning.begin_route(mesh if learn else None, pos, tgt["pos"])')
    code = code.replace('self.nav_learning.finish_route(', 'self._nav_finish(')
    if name in lm:
        ln = lm[name]
        lines[ln.lineno-1] = code + '\n'
        for i in range(ln.lineno, ln.end_lineno):
            lines[i] = ''
    else:
        extra.append(code)
local = ''.join(lines)
local = local.replace('    def _nav_finish(self, outcome):', '\n\n'.join(extra) + '\n\n    def _nav_finish(self, outcome):')
local = local.replace('        self.route_midpoints, self.route_stall, self.route_walk_at = False, None, None', '        self.route_midpoints, self.route_stall, self.route_walk_at = False, None, None\n        self.route_effort, self.route_best, self.route_command_at = 0.0, math.inf, None\n        self.traversal_started, self.traversal_pressed = None\n        self.blocked_links, self.route_failures = set(), {}\n        self.nav_last_good, self.nav_recovery = None, None', 1)
local = local.replace('        priority_prompt = snap.get("prompt")', '        if snap.get("stage_prompt"):\n            self._remember_traversal_prompt(now)\n        priority_prompt = snap.get("prompt")', 1)
local = local.replace('        mesh = snap.get("nav")\n        geometry', '        mesh = snap.get("nav")\n        if mesh is not None and mesh.find(p["pos"], floor_only=True, height_slack=60.) is not None:\n            self.nav_last_good = tuple(p["pos"])\n        geometry', 1)
local = local.replace('            self.unstick_until, self.stuck_since = 0.0, None', '            self.route_command_at = None\n            self.unstick_until, self.stuck_since = 0.0, None', 1)
local = local.replace('                self.bonus_skip.clear()', '                self.blocked_links.clear()\n                self.route_failures.clear()\n                self.nav_last_good = self.nav_recovery = None\n                self.bonus_skip.clear()', 1)
local = local.replace('        mesh = snap.get("nav")\n        if mesh is not None and self.avoid', '''        mesh = snap.get("nav")
        if mesh is not None and not close_foes:
            if mesh.find(p["pos"], floor_only=True, height_slack=60.) is None:
                if self.traversal_pressed is not None and self.route and isinstance(self.route[0], re5_nav.Traversal):
                    return self._traverse(p, {"ptr": self.route_for, "pos": self.route[-1]}, mesh,
                                          self.route[0], snap.get("stage_prompt"), now)
                return self._recover_nav(p, mesh, now)
            if self.nav_recovery is not None:
                self.stats["nav_recoveries"] = self.stats.get("nav_recoveries", 0) + 1
                self.route, self.route_len, self.route_at = None, None, -math.inf
            self.nav_recovery = None
        if mesh is not None and self.avoid''', 1)
ast.parse(local)
path.write_text(local)
navpath = root / 'system/gbox/mercs/titles/re5_nav.py'
navlocal = navpath.read_text()
navremote = (scratch / 'gbox_mercs_titles_re5_nav.py.remote').read_text()
cls = next(n for n in ast.parse(navlocal).body if isinstance(n, ast.ClassDef) and n.name == 'NavMesh')
node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'elevated')
code = ''.join(navlocal.splitlines(keepends=True)[node.lineno-1:node.end_lineno])
navremote = navremote.replace('    def floor_segment(self, start, goal)', code + '\n\n    def floor_segment(self, start, goal)', 1)
navpath.write_text(navremote)
print('Combined live traversal recovery with local bot improvements')
