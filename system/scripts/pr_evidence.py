#!/usr/bin/env python3
"""Attach evidence pictures to a pull request (docs/pr-evidence.md).

  python system/scripts/pr_evidence.py --pr 296 --images a.png b.png --captions "Sonic as Snake" "Knuckles as soldiers" \
      --kinds "offline render" "offline render" --gh "ssh ehm_eckx@10.89.1.246 gh"

  python system/scripts/pr_evidence.py --pr 296 --manifest out/pr-296/manifest.json --gh "ssh ... gh"

1. Every image is checked (PNG / JPEG / WebP / GIF by its bytes: nothing else is ever committed), re-encoded when it
   is over --max-kb (PNG optimised, then JPEG, then scaled down), and named NN-<caption>.<ext>.
2. The images are committed to the orphan branch `pr-evidence` under pr-<N>/ with git plumbing (hash-object,
   mktree, commit-tree): no checkout, the working tree and index are never touched. Images already there for the PR
   are replaced; other PRs' folders are kept. Then `git push <remote> <commit>:refs/heads/pr-evidence`.
3. The PR body gets (or has replaced) an "Evidence" gallery between <!-- pr-evidence:start/end --> markers, each image
   captioned and marked "session screenshot", independently reviewed "in-game frame", "offline render" or "UI screenshot", linked as
   https://github.com/<repo>/blob/pr-evidence/pr-<N>/<file>?raw=true. The body is printed; with --gh it is also
   read from and written back to the PR (`<gh> pr view N -R repo --json body -q .body`, `<gh> pr edit N -R repo
   --body-file -`).

--dry-run: prepare and print, commit nothing, push nothing, edit nothing.  --no-push: commit locally only.
Pictures pulled from an evidence_capture job: --job <id> --api <url> --token-file <path> adds its frames and pairs.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

REPO = "teamcsharp/gBox"
BRANCH = "pr-evidence"
KINDS = ("session screenshot", "in-game frame", "offline render", "UI screenshot")
KIND_ALIASES = {"ingame": "in-game frame", "ingameframe": "in-game frame", "frame": "in-game frame",
                "game": "in-game frame", "offline": "offline render", "render": "offline render",
                "offlinerender": "offline render", "ui": "UI screenshot", "screenshot": "UI screenshot",
                "uiscreenshot": "UI screenshot", "sessionscreenshot": "session screenshot"}
START, END = "<!-- pr-evidence:start -->", "<!-- pr-evidence:end -->"
MAGIC = {b"\x89PNG\r\n\x1a\n": ".png", b"\xff\xd8\xff": ".jpg", b"GIF87a": ".gif", b"GIF89a": ".gif"}
MAX_KB = 1000


class EvidenceError(ValueError):
    pass


def kind_of(value: str | None, default: str = "offline render") -> str:
    v = (value or "").strip()
    if not v:
        return default
    for k in KINDS:
        if v.lower() == k.lower():
            return k
    k = KIND_ALIASES.get(re.sub(r"[^a-z]", "", v.lower()))
    if not k:
        raise EvidenceError(f"unknown evidence kind {value!r}: use one of {KINDS}")
    return k


def image_ext(data: bytes) -> str:
    """The image's real type from its bytes; anything that is not a picture is refused (never commit game data)."""
    for magic, ext in MAGIC.items():
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    raise EvidenceError("not a PNG / JPEG / GIF / WebP picture")


def slug(text: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:n].strip("-") or "image"


def shrink(data: bytes, max_kb: int = MAX_KB) -> tuple[bytes, str]:
    """Keep the picture under max_kb: as it is, else optimised PNG, else JPEG (q 88..60), else scaled down."""
    ext = image_ext(data)
    if len(data) <= max_kb * 1024:
        return data, ext
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.load()
    if ext == ".png":
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        if buf.tell() <= max_kb * 1024:
            return buf.getvalue(), ".png"
    rgb = im.convert("RGB")
    for scale in (1.0, 0.85, 0.7, 0.55, 0.4, 0.3):
        cur = rgb if scale == 1.0 else rgb.resize((max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))),
                                                  Image.LANCZOS)
        for q in (88, 80, 70, 60):
            buf = io.BytesIO()
            cur.save(buf, "JPEG", quality=q, optimize=True)
            if buf.tell() <= max_kb * 1024:
                return buf.getvalue(), ".jpg"
    raise EvidenceError(f"could not get the picture under {max_kb} KB")


def prepare(items: list[dict], max_kb: int = MAX_KB) -> list[dict]:
    """items [{path | data, caption, kind}] -> [{name, data, caption, kind}] (checked, shrunk, numbered)."""
    out, seen = [], set()
    for k, it in enumerate(items, 1):
        data = it.get("data")
        if data is None:
            p = Path(it["path"])
            if not p.is_file():
                raise EvidenceError(f"{p}: no such file")
            data = p.read_bytes()
        caption = (it.get("caption") or Path(it.get("path") or "image").stem).strip()
        try:
            data, ext = shrink(data, max_kb)
        except EvidenceError as e:
            raise EvidenceError(f"{it.get('path') or caption}: {e}") from None
        name = f"{k:02d}-{slug(caption)}{ext}"
        while name in seen:
            name = f"{k:02d}-{slug(caption)}-{len(seen)}{ext}"
        seen.add(name)
        out.append({"name": name, "data": data, "caption": caption, "kind": kind_of(it.get("kind"))})
    return out


def image_url(repo: str, pr: int, name: str, branch: str = BRANCH) -> str:
    return f"https://github.com/{repo}/blob/{branch}/pr-{pr}/{name}?raw=true"


def gallery(pr: int, images: list[dict], repo: str = REPO, branch: str = BRANCH, note: str = "") -> str:
    """The Evidence section (between markers so a rerun replaces it)."""
    lines = [START, "## Evidence", ""]
    if note:
        lines += [note.strip(), ""]
    counts = {k: sum(1 for i in images if i["kind"] == k) for k in KINDS}
    lines.append("Pictures: " + ", ".join(f"{n} {k}{'s' if n != 1 else ''}" for k, n in counts.items() if n)
                 + f" (stored on the `{branch}` branch under `pr-{pr}/`).")
    lines.append("")
    for k, im in enumerate(images, 1):
        cap = im["caption"].replace("\n", " ").strip()
        alt = re.sub(r"[\[\]\"<>]", "", cap)[:120]
        lines.append(f"**{k}. {cap}** _({im['kind']})_")
        lines.append("")
        lines.append(f'<img src="{image_url(repo, pr, im["name"], branch)}" alt="{alt}" width="720">')
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


def merge_body(body: str, section: str) -> str:
    """Put the Evidence section into the PR body: replaces an earlier one, else appended (before a trailing
    'Generated with' attribution line if there is one)."""
    body = body or ""
    if START in body and END in body:
        a, b = body.index(START), body.index(END) + len(END)
        return body[:a] + section + body[b:]
    m = re.search(r"\n(?:🤖 )?Generated with \[Claude Code\][^\n]*\s*$", body)
    if m:
        return body[:m.start()].rstrip() + "\n\n" + section + "\n" + body[m.start():]
    return (body.rstrip() + "\n\n" if body.strip() else "") + section + "\n"


# ------------------------------------------------------------------------------------------------ git plumbing

def _git(repo_dir: Path, *args: str, input: bytes | None = None, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(repo_dir), *args], input=input, capture_output=True)
    if check and r.returncode:
        raise EvidenceError(f"git {' '.join(args[:3])}: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout.decode(errors="replace").strip() if r.returncode == 0 else ""


def commit_images(repo_dir: Path, pr: int, images: list[dict], remote: str = "origin", branch: str = BRANCH,
                  push: bool = True, author: str = "") -> str:
    """Commit images to <branch>:pr-<N>/ without a checkout; push when asked. -> commit sha."""
    _git(repo_dir, "fetch", "--quiet", remote, f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}", check=False)
    parent = _git(repo_dir, "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}", check=False)
    root = {}
    if parent:
        for ln in _git(repo_dir, "ls-tree", parent).splitlines():
            meta, name = ln.split("\t", 1)
            root[name] = meta
    entries = []
    for im in images:
        blob = _git(repo_dir, "hash-object", "-w", "--stdin", input=im["data"])
        entries.append(f"100644 blob {blob}\t{im['name']}")
    sub = _git(repo_dir, "mktree", input=("\n".join(entries) + "\n").encode())
    root[f"pr-{pr}"] = f"040000 tree {sub}"
    if "README.md" not in root:
        readme = (f"# PR evidence\n\nScreenshots and renders attached to pull requests by system/scripts/pr_evidence.py "
                  f"(one folder per PR). Images only: never game data.\n").encode()
        root["README.md"] = "100644 blob " + _git(repo_dir, "hash-object", "-w", "--stdin", input=readme)
    tree = _git(repo_dir, "mktree", input=("\n".join(f"{m}\t{n}" for n, m in sorted(root.items())) + "\n").encode())
    msg = (f"Evidence for PR #{pr}: {len(images)} image(s)\n\n" + "\n".join(f"- {i['name']}: {i['caption'][:100]} "
                                                                          f"({i['kind']})" for i in images)
           + "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n")
    args = ["commit-tree", tree, "-F", "-"] + (["-p", parent] if parent else [])
    commit = _git(repo_dir, *args, input=msg.encode())
    _git(repo_dir, "update-ref", f"refs/heads/{branch}", commit)
    if push:
        _git(repo_dir, "push", remote, f"{commit}:refs/heads/{branch}")
    return commit


def _run_gh(gh: str, args: list[str], stdin: str | None = None) -> str:
    """Run `<gh prefix> args`. An ssh prefix sends one remote command line, so each argument is shell-quoted."""
    prefix = shlex.split(gh, posix=True)
    cmd = prefix + ([shlex.quote(x) for x in args] if prefix and Path(prefix[0]).stem == "ssh" else list(args))
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise EvidenceError(f"{' '.join(cmd[:4])} ...: {r.stderr.strip()[-500:]}")
    return r.stdout


def from_job(api: str, token: str, job: str) -> list[dict]:
    """An evidence_capture job's pictures (pairs first, then frames) as items with data."""
    import httpx
    h = {"Authorization": f"Bearer {token}"}
    j = httpx.get(f"{api}/api/jobs/{job}", headers=h, timeout=30).json()
    out = j.get("output") or {}
    items = []
    for p in out.get("pairs") or []:
        items.append({"sha": p["composite"], "caption": f"{p['label']}: stock vs {out.get('mod')} (gameplay unverified)", "kind": "session screenshot"})
    for f in out.get("frames") or []:
        if f.get("kind") in ("in-game frame", "session screenshot"):
            items.append({"sha": f["sha256"], "caption": f"{f['label']} ({f.get('run')}, {out.get('worker')}; gameplay unverified)",
                          "kind": "session screenshot"})
    for it in items:
        it["data"] = httpx.get(f"{api}/api/artifacts/{it.pop('sha')}", headers=h, timeout=60).content
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--images", nargs="*", default=[])
    ap.add_argument("--captions", nargs="*", default=[])
    ap.add_argument("--kinds", nargs="*", default=[], help=f"per image: {', '.join(KINDS)} (default offline render)")
    ap.add_argument("--manifest", action="append", default=[], help="a manifest.json {images: [{file, caption, kind}]}")
    ap.add_argument("--job", help="an evidence_capture job id: add its frames and pairs (needs --api, --token-file)")
    ap.add_argument("--api", default="http://10.89.1.246:8765")
    ap.add_argument("--token-file", default="")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--repo-dir", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--branch", default=BRANCH)
    ap.add_argument("--gh", default="", help='command prefix for gh, e.g. "ssh ehm_eckx@10.89.1.246 gh"')
    ap.add_argument("--body-file", default="", help="the PR's current body (instead of reading it with --gh)")
    ap.add_argument("--note", default="", help="a sentence above the gallery")
    ap.add_argument("--max-kb", type=int, default=MAX_KB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args(argv)
    if len(a.captions) > len(a.images) or len(a.kinds) > len(a.images):
        ap.error("more captions/kinds than images")
    items = [{"path": p, "caption": a.captions[k] if k < len(a.captions) else "",
              "kind": a.kinds[k] if k < len(a.kinds) else ""} for k, p in enumerate(a.images)]
    for mf in a.manifest:
        m = json.loads(Path(mf).read_text(encoding="utf-8"))
        for it in m.get("images", []):
            items.append({"path": str(Path(mf).parent / it["file"]), "caption": it.get("caption", ""),
                          "kind": it.get("kind", "")})
    if a.job:
        token = Path(a.token_file).read_text().strip() if a.token_file else ""
        items += from_job(a.api.rstrip("/"), token, a.job)
    if not items:
        ap.error("no images (--images, --manifest or --job)")
    try:
        images = prepare(items, a.max_kb)
        section = gallery(a.pr, images, a.repo, a.branch, a.note)
        if a.body_file:
            body = Path(a.body_file).read_text(encoding="utf-8")
        elif a.gh:
            body = _run_gh(a.gh, ["pr", "view", str(a.pr), "-R", a.repo, "--json", "body", "-q", ".body"])
        else:
            body = ""
        new_body = merge_body(body, section)
        for im in images:
            print(f"# {im['name']}: {len(im['data']) // 1024} KB, {im['kind']}", file=sys.stderr)
        if not a.dry_run:
            commit = commit_images(Path(a.repo_dir), a.pr, images, a.remote, a.branch, push=not a.no_push)
            print(f"# committed {commit[:10]} to {a.branch}" + ("" if a.no_push else f" and pushed to {a.remote}"),
                  file=sys.stderr)
            if a.gh and not a.no_push:
                _run_gh(a.gh, ["pr", "edit", str(a.pr), "-R", a.repo, "--body-file", "-"], stdin=new_body)
                print(f"# PR #{a.pr} body updated", file=sys.stderr)
        print(new_body)
    except EvidenceError as e:
        print(f"pr_evidence: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
