"""scripts/pr_evidence.py: pictures only, under ~1 MB, on the orphan pr-evidence branch (git plumbing, no checkout),
and an idempotent captioned "Evidence" gallery in the PR body."""
import importlib.util
import io
import random
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pr_evidence.py"
spec = importlib.util.spec_from_file_location("pr_evidence", SCRIPT)
PE = importlib.util.module_from_spec(spec)
sys.modules["pr_evidence"] = PE
spec.loader.exec_module(PE)


def png(size=(40, 30), noise=False) -> bytes:
    from PIL import Image
    im = Image.new("RGB", size, (30, 120, 220))
    if noise:
        rnd = random.Random(1)
        im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(size[0] * size[1])])
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_only_pictures_are_accepted():
    assert PE.image_ext(png()) == ".png"
    with pytest.raises(PE.EvidenceError, match="not a PNG"):
        PE.image_ext(b"SEGA SEGAKATANA game data")
    with pytest.raises(PE.EvidenceError, match="not a PNG"):
        PE.prepare([{"data": b"\x00" * 100, "caption": "disc.bin"}])


def test_big_pictures_are_shrunk_under_the_limit():
    big = png((900, 700), noise=True)
    assert len(big) > 1000 * 1024
    data, ext = PE.shrink(big, 300)
    assert len(data) <= 300 * 1024 and ext == ".jpg" and PE.image_ext(data) == ".jpg"
    small = png()
    assert PE.shrink(small) == (small, ".png")


def test_kinds_and_names():
    assert PE.kind_of("in-game") == "in-game frame" and PE.kind_of("Offline Render") == "offline render"
    assert PE.kind_of("ui") == "UI screenshot" and PE.kind_of("") == "offline render"
    with pytest.raises(PE.EvidenceError):
        PE.kind_of("photoshop")
    ims = PE.prepare([{"data": png(), "caption": "Sonic as Snake!", "kind": "offline"},
                      {"data": png(), "caption": "Sonic as Snake!", "kind": "in-game frame"}])
    assert [i["name"] for i in ims] == ["01-sonic-as-snake.png", "02-sonic-as-snake.png"]


def test_gallery_body_links_captions_and_marks_every_image():
    ims = PE.prepare([{"data": png(), "caption": "Knuckles as every soldier", "kind": "offline render"},
                      {"data": png(), "caption": "vr_sud03 restarted", "kind": "in-game"}])
    sec = PE.gallery(296, ims, note="Rendered offline; the in-game frame comes from evidence_capture.")
    assert sec.startswith(PE.START) and sec.endswith(PE.END) and "## Evidence" in sec
    assert "https://github.com/teamcsharp/gBox/blob/pr-evidence/pr-296/01-knuckles-as-every-soldier.png?raw=true" in sec
    assert "**1. Knuckles as every soldier** _(offline render)_" in sec
    assert "**2. vr_sud03 restarted** _(in-game frame)_" in sec
    assert "1 in-game frame, 1 offline render" in sec or "1 offline render" in sec
    body = "Summary\n\nDetails\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)"
    merged = PE.merge_body(body, sec)
    assert merged.index("## Evidence") < merged.index("Generated with") and merged.startswith("Summary")
    again = PE.merge_body(merged, PE.gallery(296, ims[:1]))
    assert again.count(PE.START) == 1 and "vr_sud03" not in again and "Generated with" in again
    assert PE.merge_body("", sec).strip() == sec


def test_commit_uses_an_orphan_branch_and_leaves_the_worktree_alone(tmp_path):
    def git(*a, cwd):
        return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    git("init", "--bare", "-q", str(remote), cwd=tmp_path)
    git("init", "-q", str(work), cwd=tmp_path)
    for k, v in (("user.name", "t"), ("user.email", "t@example.com")):
        git("config", k, v, cwd=work)
    (work / "code.py").write_text("print(1)\n")
    git("add", ".", cwd=work)
    git("commit", "-qm", "main", cwd=work)
    git("remote", "add", "origin", str(remote), cwd=work)
    head = git("rev-parse", "HEAD", cwd=work)
    c1 = PE.commit_images(work, 296, PE.prepare([{"data": png(), "caption": "a"}]))
    c2 = PE.commit_images(work, 301, PE.prepare([{"data": png(), "caption": "b"}, {"data": png(), "caption": "c"}]))
    c3 = PE.commit_images(work, 296, PE.prepare([{"data": png(), "caption": "a2"}]))
    files = git("ls-tree", "-r", "--name-only", c3, cwd=remote).splitlines()
    assert files == ["README.md", "pr-296/01-a2.png", "pr-301/01-b.png", "pr-301/02-c.png"]
    assert git("rev-parse", "pr-evidence", cwd=remote) == c3
    assert git("rev-list", "--max-parents=0", c3, cwd=remote) == c1           # orphan: its own root, not main's
    assert git("rev-parse", "HEAD", cwd=work) == head and git("status", "--porcelain", cwd=work) == ""
    assert "Co-Authored-By: Claude" in git("log", "-1", "--format=%B", c2, cwd=remote)


def test_main_dry_run_prints_the_body_and_ssh_gh_arguments_are_quoted(tmp_path, capsys, monkeypatch):
    f = tmp_path / "shot.png"
    f.write_bytes(png())
    body = tmp_path / "body.md"
    body.write_text("Old body")
    assert PE.main(["--pr", "7", "--images", str(f), "--captions", "the shot", "--kinds", "ui", "--dry-run",
                    "--body-file", str(body)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Old body") and "pr-7/01-the-shot.png?raw=true" in out and "(UI screenshot)" in out
    seen = {}

    class R:
        returncode, stdout, stderr = 0, "body", ""

    def fake_run(cmd, **kw):
        seen["cmd"], seen["input"] = cmd, kw.get("input")
        return R()
    monkeypatch.setattr(PE.subprocess, "run", fake_run)
    PE._run_gh("ssh ehm_eckx@10.89.1.246 gh", ["pr", "edit", "7", "-R", "teamcsharp/gBox", "--body-file", "-"], "B o d y")
    assert seen["cmd"][:3] == ["ssh", "ehm_eckx@10.89.1.246", "gh"] and seen["input"] == "B o d y"
    PE._run_gh("ssh host gh", ["pr", "view", "7", "-q", ".body x"])
    assert seen["cmd"][-1] == "'.body x'"
    PE._run_gh("gh", ["pr", "view", "7", "-q", ".body x"])
    assert seen["cmd"] == ["gh", "pr", "view", "7", "-q", ".body x"]


@pytest.mark.parametrize('kind',['session screenshot','in-game frame'])
def test_automatic_job_screenshots_are_retained_without_promoting_them_to_verified_gameplay(monkeypatch,kind):
    import httpx
    from types import SimpleNamespace
    payload={'output':{'mod':'fixture-mod','worker':'fixture-worker',
        'frames':[{'kind':kind,'sha256':'frame','label':'capture','run':'mod'},
                  {'kind':'scene capture (GLB)','sha256':'model','label':'scene'}],
        'pairs':[{'kind':kind,'composite':'pair','label':'compare'}]}}
    requested=[]
    def get(url,**kwargs):
        requested.append(url)
        return SimpleNamespace(json=lambda:payload,content=png())
    monkeypatch.setattr(httpx,'get',get)
    items=PE.from_job('https://fixture.invalid','fixture-token','capture-job')
    assert len(items)==2 and requested==['https://fixture.invalid/api/jobs/capture-job',
        'https://fixture.invalid/api/artifacts/pair','https://fixture.invalid/api/artifacts/frame']
    assert all(it['kind']=='session screenshot' and 'gameplay unverified' in it['caption'] for it in items)
    images=PE.prepare(items)
    gallery=PE.gallery(1,images)
    assert '2 session screenshots' in gallery and 'in-game frame' not in gallery
