"""Round 118: per-branch inventory - what each branch itself changed, and how much of it main already has.

`git diff main <branch>` counts main's newer files as deletions, which is wrong for a merge. The right measure is against the
merge base: the branch's own changes. For each of those files, comparing main's copy with the branch's copy says whether the
work is already in main or still to apply.
"""
import subprocess

REPO = r"C:\_tools\gBox\.tmp\main-repo"
BRANCHES = [
    "ds-pso-cp02-gold-set-20261110",
    "ds-pso-cp03-labelling-20261110",
    "ds-pso-cp06-evt-opcodes-20261110",
    "ds-pso-cp06-nrel-20261110",
    "ds-pso-cp07-model-walk-20261110",
    "ds-pso-cp07-object-loader-20261110",
    "ds-pso-cp07-scene-loader-20261110",
    "ds-pso-cp08-room-pieces-20261110",
    "ds-pso-cp09-save-data-20261110",
    "ds-pso-cp10-forest1-20261110",
    "ds-pso-cp12-rigged-swap-20261110",
    "ds-pso-cp13-library-donors-20261110",
    "ds-pso-cp15-room-inventory-20261110",
    "ds-pso-cp16-stick-20261110",
    "ds-pso-cp17-walk-graph-20261110",
    "ds-pso-editor-views-20261110",
]


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def main():
    print(f"{'branch':44s} {'own':>4s} {'in main':>7s} {'to apply':>8s}  files still to apply")
    for branch in BRANCHES:
        ref = f"origin/{branch}"
        base = git("merge-base", "origin/main", ref).stdout.strip()
        if not base:
            print(f"{branch:44s} (no merge base)")
            continue
        changed = [f for f in git("diff", "--name-only", base, ref).stdout.splitlines() if f]
        same, missing = 0, []
        for path in changed:
            if git("diff", "--quiet", "origin/main", ref, "--", path).returncode == 0:
                same += 1
            else:
                missing.append(path)
        short = ", ".join(p.replace("system/", "") for p in missing[:3])
        print(f"{branch:44s} {len(changed):4d} {same:7d} {len(missing):8d}  {short}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
