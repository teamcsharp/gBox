"""universal-modder tools (#825): every op against fakes (temp folders, a fake session, fake ComfyUI, fake Blender, fake GitHub)."""
import io
import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from gbox import agent, filemods, registry, tools
from gbox import universal_modder as um
from gbox.config import Config
from gbox.registry import Ctx
from gbox.vendor import universal_modder as vendored
from gbox.vendor.universal_modder import comfy as um_comfy
from gbox.vendor.universal_modder import render3d as um_render3d
from gbox.vendor.universal_modder import scan as um_scan

GID = "0123456789abcdef"


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(um_scan, "all_games", lambda: [])          # never read this PC's real Steam / Epic / Xbox installs
    monkeypatch.setattr(um_scan, "win_folders", lambda: {})
    return Ctx(Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache"))


def run(name, inp, ctx):
    t = registry.REGISTRY[name]
    return t.Out.model_validate(t.fn(t.In.model_validate(inp), ctx)).model_dump(mode="json")["result"]


def png(w=40, h=30, bg=(255, 255, 255, 255), box=(10, 8, 20, 18), color=(220, 30, 30, 255)) -> bytes:
    im = Image.new("RGBA", (w, h), bg)
    im.paste(Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), color), box[:2])
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def unity_game(root: Path, anti_cheat=False) -> Path:
    files = {"Game.exe": b"MZ", "UnityPlayer.dll": b"x", "Game_Data/globalgamemanagers": b"\0\0 2021.3.16f1 \0",
             "Game_Data/Managed/Assembly-CSharp.dll": b"x", "Game_Data/app.info": b"Acme\nMy Game",
             "BepInEx/core/BepInEx.dll": b"x"}
    if anti_cheat:
        files["EasyAntiCheat/EasyAntiCheat_x64.dll"] = b"x"
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    return root


# ---------------------------------------------------------------------------------------------------------- vendoring

def test_vendored_copy_is_pinned_and_licensed():
    d = Path(vendored.__file__).parent
    assert vendored.COMMIT == "5ba8150e27b4f1bf17ae19dcecdb2341e467885a" and vendored.LICENSE == "MIT"
    assert "MIT License" in (d / "LICENSE").read_text(encoding="utf-8")
    assert (d / "blender" / "render_sprites.py").is_file() and (d / "playbooks" / "engines" / "unity.md").is_file()
    assert len(json.loads((d / "knowledge_index.json").read_text(encoding="utf-8"))) > 150
    for f in d.glob("*.py"):                       # no CLI, no GitHub pushes, no fal / win modules
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import) um[ .]", text, re.M) and "sys.exit(" not in text and '"gh", "pr"' not in text, f.name
    assert not (d / "fal.py").exists() and not (d / "win.py").exists()


def test_upstream_die_raises_instead_of_exiting():
    from gbox.vendor.universal_modder import common
    with pytest.raises(common.UmError):
        common.die("boom")


# ------------------------------------------------------------------------------------------------------------ um_scan

def test_scan_a_unity_folder_reports_engine_loader_saves_routes_and_playbook(ctx, tmp_path):
    game = unity_game(tmp_path / "My Game")
    r = run("um_scan", {"path": str(game)}, ctx)
    assert r["scanned"] and r["engine"]["key"] == "unity-mono" and r["engine"]["version"] == "2021.3.16f1"
    assert r["mod_loaders_installed"] == ["BepInEx"] and r["anti_cheat"] == []
    assert r["playbook"] == "unity.md" and "Unity" in r["playbook_text"]
    assert r["changed"] == [] and r["source"]["commit"] == vendored.COMMIT


def test_scan_warns_and_puts_safety_first_with_anti_cheat(ctx, tmp_path):
    r = run("um_scan", {"path": str(unity_game(tmp_path / "Shooter", anti_cheat=True)), "playbook": False}, ctx)
    assert r["anti_cheat"] == ["EasyAntiCheat"] and any("anti-cheat" in w for w in r["warnings"])
    assert r["next"][0].startswith("STOP") and "playbook_text" not in r


def test_scan_a_live_session_uses_the_install_folder_and_catalog_title(ctx, tmp_path, monkeypatch):
    game = unity_game(tmp_path / "steamapps" / "common" / "MyGame")
    monkeypatch.setitem(tools.SESSIONS, "w-1", (object(), {"_rom_path": str(game / "Game.exe"), "title": "Terraria"}))
    r = run("um_scan", {"session_id": "w-1"}, ctx)
    assert r["path"] == str(game) and r["name"] == "Terraria" and r["routes"][0]["why"] == "known game"


def test_scan_of_a_rom_image_session_explains_instead_of_scanning_the_library(ctx, tmp_path, monkeypatch):
    monkeypatch.setitem(tools.SESSIONS, "w-2", (object(), {"_rom_path": str(tmp_path / "roms" / "game.iso"), "title": "X"}))
    r = run("um_scan", {"session_id": "w-2"}, ctx)
    assert r["scanned"] is False and "ROM / disc image" in r["note"]
    with pytest.raises(ValueError, match="no live session"):
        run("um_scan", {"session_id": "nope"}, ctx)


def test_install_root_for_steam_unreal_and_plain_exes():
    assert um.install_root(Path("D:/S/steamapps/common/Foo/Foo/Binaries/Win64/Foo-Win64-Shipping.exe")) == Path("D:/S/steamapps/common/Foo")
    assert um.install_root(Path("D:/Games/Foo/Foo/Binaries/Win64/Foo.exe")) == Path("D:/Games/Foo")
    assert um.install_root(Path("D:/Games/Bar/bar.exe")) == Path("D:/Games/Bar")


def test_scan_list_returns_the_workers_installs(ctx, monkeypatch):
    monkeypatch.setattr(um_scan, "all_games", lambda: [{"store": "steam", "appid": "105600", "name": "Terraria", "path": "C:/T"}])
    r = run("um_scan", {"op": "list"}, ctx)
    assert r["count"] == 1 and r["games"][0]["name"] == "Terraria"
    with pytest.raises(ValueError, match="unknown op"):
        run("um_scan", {"op": "explode"}, ctx)


# -------------------------------------------------------------------------------------------------------------- um_kb

def test_kb_search_is_offline_and_ranks_the_game(ctx):
    r = run("um_kb", {"op": "search", "query": "terraria"}, ctx)
    assert r["hits"] and all("terraria" in (h["path"] + str(h["game"])).lower() for h in r["hits"][:3])
    assert run("um_kb", {"op": "search", "query": "x", "engine": "no-such-engine"}, ctx)["hits"] == []


def test_kb_show_fetches_the_pinned_note_once_then_caches(ctx, monkeypatch):
    import httpx
    calls = []

    def get(url, **kw):
        calls.append(url)
        return SimpleNamespace(text="---\ntitle: T\n---\n## Gotchas\n1. tModLoader hot reload\n", raise_for_status=lambda: None)
    monkeypatch.setattr(httpx, "get", get)
    path = "games/terraria/fal-arsenal-tmodloader.md"
    r = run("um_kb", {"op": "show", "path": path}, ctx)
    assert "hot reload" in r["text"] and calls == [um.RAW + path] and vendored.COMMIT in calls[0]
    run("um_kb", {"op": "show", "path": path}, ctx)
    assert len(calls) == 1                                          # second read: the cache
    hits = run("um_kb", {"op": "search", "query": "hot reload"}, ctx)["hits"]
    assert any(h["path"] == path for h in hits)                     # full text of fetched notes is searchable
    for bad in ("../../secrets.md", "games/not-in-index.md"):
        with pytest.raises(ValueError, match="not a note"):
            run("um_kb", {"op": "show", "path": bad}, ctx)


def test_kb_playbooks_safety_and_engines(ctx):
    assert "BepInEx" in run("um_kb", {"op": "playbook", "engine": "unity-mono"}, ctx)["text"]
    assert "anti-cheat" in run("um_kb", {"op": "safety"}, ctx)["text"].lower()
    assert run("um_kb", {"op": "engines"}, ctx)["engines"]["unreal"]["playbook"] == "unreal.md"
    with pytest.raises(ValueError, match="no playbook"):
        run("um_kb", {"op": "playbook", "playbook": "../../../etc/passwd"}, ctx)


# ---------------------------------------------------------------------------------------------------------- um_backup

def test_backup_create_list_diff_restore_and_undo(ctx, tmp_path):
    saves = tmp_path / "saves"
    saves.mkdir()
    (saves / "slot1.sav").write_bytes(b"original")
    c = run("um_backup", {"op": "create", "path": str(saves), "name": "mygame"}, ctx)
    assert c["files"] == 1 and c["undo"].startswith("um_backup op=delete name=mygame")
    assert Path(c["changed"][0][6:]).is_relative_to(Path(ctx.config.cache) / "universal_modder" / "backups")
    assert run("um_backup", {"op": "list"}, ctx)["snapshots"][0]["name"] == "mygame"
    (saves / "slot1.sav").write_bytes(b"broken by a mod")
    (saves / "new.sav").write_bytes(b"x")
    d = run("um_backup", {"op": "diff", "name": "mygame"}, ctx)
    assert d["modified"] == ["slot1.sav"] and d["added"] == ["new.sav"] and d["changed"] == []
    dry = run("um_backup", {"op": "restore", "name": "mygame", "clean": True}, ctx)
    assert dry["dry_run"] and dry["overwrite"] == ["slot1.sav"] and dry["delete"] == ["new.sav"]
    assert (saves / "slot1.sav").read_bytes() == b"broken by a mod"            # a dry run changes nothing
    done = run("um_backup", {"op": "restore", "name": "mygame", "clean": True, "confirm": True}, ctx)
    assert (saves / "slot1.sav").read_bytes() == b"original" and not (saves / "new.sav").exists()
    assert "mygame-pre-restore" in done["undo"]                                 # the restore itself can be undone
    pre = run("um_backup", {"op": "list", "name": "mygame-pre-restore"}, ctx)["snapshots"]
    assert pre and pre[0]["files"] == 2
    gone = run("um_backup", {"op": "delete", "name": "mygame", "snapshot": c["snapshot"]}, ctx)
    assert gone["deleted"] == c["snapshot"] and not run("um_backup", {"op": "list", "name": "mygame"}, ctx)["snapshots"]


def test_backup_restore_refuses_game_installs_and_foreign_snapshot_paths(ctx, tmp_path, monkeypatch):
    game = unity_game(tmp_path / "Game")
    run("um_backup", {"op": "create", "path": str(game / "Game_Data"), "name": "data"}, ctx)
    monkeypatch.setattr(um_scan, "all_games", lambda: [{"name": "Game", "path": str(game)}])
    with pytest.raises(ValueError, match="inside the game install"):
        run("um_backup", {"op": "restore", "name": "data", "confirm": True}, ctx)
    with pytest.raises(ValueError, match="file name"):
        run("um_backup", {"op": "restore", "name": "data", "snapshot": "../../x.zip"}, ctx)
    with pytest.raises(ValueError, match="name"):
        run("um_backup", {"op": "diff", "name": "../escape"}, ctx)


# --------------------------------------------------------------------------------------------- um_mod + publish check

def test_mod_stage_list_remove_and_launch_guard(ctx, tmp_path):
    src = tmp_path / "Missile.png"
    src.write_bytes(png())
    r = run("um_mod", {"op": "stage", "game_id": GID, "name": "fal-arsenal", "install_into": "Mods/FalArsenal",
                       "files": [{"dest": "Assets/Missile.png", "path": str(src)}]}, ctx)
    d = Path(r["dir"])
    assert d == Path(ctx.config.cache) / "mods" / GID / "fal-arsenal" and (d / "Assets" / "Missile.png").read_bytes() == src.read_bytes()
    meta = json.loads((d / ".gbox-mod.json").read_text())
    assert meta["kind"] == "universal_modder" and meta["launchable"] is False and "Assets/Missile.png" in meta["files"]
    assert "Mods/FalArsenal" in (d / "README.md").read_text() and "op=remove" in r["undo"]
    with pytest.raises(ValueError, match="overwrite=true"):
        run("um_mod", {"op": "stage", "game_id": GID, "name": "fal-arsenal", "files": [{"dest": "Assets/Missile.png", "path": str(src)}]}, ctx)
    with pytest.raises(ValueError, match="bad file path"):
        run("um_mod", {"op": "stage", "game_id": GID, "name": "fal-arsenal", "files": [{"dest": "../../evil.dll", "path": str(src)}]}, ctx)
    with pytest.raises(ValueError, match="staged file set"):
        filemods.launch_path(ctx.config, GID, tmp_path / "game.iso", "fal-arsenal")
    assert [m["name"] for m in run("um_mod", {"op": "list", "game_id": GID}, ctx)["mods"]] == ["fal-arsenal"]
    gone = run("um_mod", {"op": "remove", "game_id": GID, "name": "fal-arsenal"}, ctx)
    assert not d.exists() and (Path(gone["trash"]) / "Assets" / "Missile.png").is_file() and "move" in gone["undo"]


def test_mod_never_clobbers_another_gbox_mod(ctx, tmp_path):
    other = filemods.mod_dir(ctx.config, GID, "char-swap")
    other.mkdir(parents=True)
    (other / ".gbox-mod.json").write_text(json.dumps({"name": "char-swap", "image": "game.iso"}))
    src = tmp_path / "a.txt"
    src.write_text("x")
    with pytest.raises(ValueError, match="belongs to another gBox mod"):
        run("um_mod", {"op": "stage", "game_id": GID, "name": "char-swap", "files": [{"dest": "a.txt", "path": str(src)}]}, ctx)
    with pytest.raises(ValueError, match="not a universal-modder mod"):
        run("um_mod", {"op": "remove", "game_id": GID, "name": "char-swap"}, ctx)
    assert (other / ".gbox-mod.json").exists()


def test_publish_check_fails_copied_game_files_and_keys_passes_a_clean_mod(ctx, tmp_path):
    game = tmp_path / "Game"
    game.mkdir()
    (game / "data.pak").write_bytes(b"G" * 4096)
    mod = tmp_path / "MyMod"
    mod.mkdir()
    (mod / "data.pak").write_bytes(b"G" * 4096)
    (mod / "config.json").write_text('{"key": "sk-ant-' + "a" * 30 + '"}')
    r = run("um_publish_check", {"path": str(mod), "game_path": str(game)}, ctx)
    assert r["verdict"] == "FAIL" and any("verbatim" in f for f in r["fails"]) and any("Anthropic" in f for f in r["fails"])
    assert any("README" in w for w in r["warns"]) and r["changed"] == []
    src = tmp_path / "icon.png"
    src.write_bytes(png())
    run("um_mod", {"op": "stage", "game_id": GID, "name": "clean", "files": [{"dest": "icon.png", "path": str(src)}]}, ctx)
    ok = run("um_publish_check", {"mod": "clean", "game_id": GID, "game_path": str(game)}, ctx)
    assert ok["verdict"] == "PASS", ok


# ---------------------------------------------------------------------------------------------------------- um_sprite

def test_sprite_cutout_fit_info_and_artifacts(ctx, tmp_path):
    src = tmp_path / "art.png"
    src.write_bytes(png())
    r = run("um_sprite", {"op": "cutout", "path": str(src), "name": "missile"}, ctx)
    assert r["outputs"][0]["size"] == [10, 10] and ctx.artifacts[-1][0] == "missile.png"
    cut = Image.open(io.BytesIO(ctx.artifacts[-1][1]))
    assert cut.getpixel((0, 0))[3] == 255                                  # the red box survives, white is gone
    fitted = run("um_sprite", {"op": "fit", "path": str(src), "size": "16x8"}, ctx)
    assert fitted["outputs"][0]["size"] == [16, 8]
    info = run("um_sprite", {"op": "info", "path": str(src)}, ctx)["info"]
    assert info["size"] == [40, 30] and info["corner_color"] == [255, 255, 255]


@pytest.mark.parametrize("op,extra,n", [("pixelate", {"size": "8", "colors": 4, "outline": "#101010"}, 1),
                                        ("frames", {"n": 4, "kind": "squash"}, 4), ("team_mask", {"hue": "red"}, 2),
                                        ("seamless", {}, 1), ("tile_preview", {"tiles": 2}, 1), ("preview", {"scale": 2}, 1),
                                        ("slice", {"frame": "20x15"}, 4)])
def test_sprite_ops_produce_their_outputs(ctx, tmp_path, op, extra, n):
    src = tmp_path / "art.png"
    src.write_bytes(png())
    r = run("um_sprite", {"op": op, "path": str(src), **extra}, ctx)
    assert len(r["outputs"]) == n and all(len(o["sha256"]) == 64 for o in r["outputs"])


def test_sprite_sheet_palette_live_frame_crop_and_mod_staging(ctx, tmp_path, monkeypatch):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(png(8, 8, box=(0, 0, 4, 4)))
    b.write_bytes(png(8, 8, box=(4, 4, 8, 8)))
    sheet = run("um_sprite", {"op": "sheet", "inputs": [str(a), str(b)], "cols": 2}, ctx)
    assert sheet["frames"] == 2 and sheet["outputs"][0]["size"] == [16, 8]
    pal = run("um_sprite", {"op": "palette", "path": str(a), "ref": str(b)}, ctx)
    assert pal["palette"] >= 1
    frame = png(64, 48, box=(30, 20, 40, 30))
    monkeypatch.setitem(tools.SESSIONS, "w-1", (SimpleNamespace(get_frame=lambda: frame), {"title": "Live"}))
    r = run("um_sprite", {"op": "cutout", "session_id": "w-1", "crop": [25, 15, 20, 20], "name": "enemy",
                          "mod": "sprites", "game_id": GID, "dest": "Content/NPCs"}, ctx)
    assert r["outputs"][0]["size"] == [10, 10]
    staged = Path(r["staged"]["dir"]) / "Content" / "NPCs" / "enemy.png"
    assert staged.read_bytes() == ctx.artifacts[-1][1] and "op=remove" in r["undo"]


def test_sprite_limits_and_bad_input(ctx, tmp_path):
    big = tmp_path / "big.png"
    Image.new("RGBA", (2100, 2100)).save(big)
    with pytest.raises(ValueError, match="too big"):
        run("um_sprite", {"op": "cutout", "path": str(big)}, ctx)
    with pytest.raises(ValueError, match="unknown op"):
        run("um_sprite", {"op": "melt", "path": str(big)}, ctx)
    with pytest.raises(ValueError, match="size"):
        run("um_sprite", {"op": "fit", "path": str(big)}, ctx)
    with pytest.raises(ValueError, match="sha256"):
        run("um_sprite", {"op": "info", "artifact": "not-a-sha"}, ctx)


# ----------------------------------------------------------------------------------------------------------- um_comfy

class FakeComfy:
    def __init__(self):
        self.prompts = []

    def __call__(self, base, path, body=None, raw=False, timeout=60, missing_ok=False):
        assert base == "http://127.0.0.1:8188"
        if path == "/system_stats":
            return {"system": {"comfyui_version": "0.3.60", "pytorch_version": "2.8"}, "devices": [{"name": "cuda:0", "type": "cuda"}]}
        if path == "/models/checkpoints":
            return ["sd15.safetensors"]
        if path == "/prompt":
            self.prompts.append(body["prompt"])
            return {"prompt_id": "p1"}
        if path == "/history/p1":
            return {"p1": {"status": {"completed": True}, "outputs": {"9": {"images": [{"filename": "um_00001_.png", "type": "output"}]}}}}
        if path.startswith("/view?"):
            return png()
        raise AssertionError(path)


def test_comfy_status_image_sprite_and_run(ctx, monkeypatch):
    fake = FakeComfy()
    monkeypatch.setattr(um_comfy, "_req", fake)
    monkeypatch.delenv("COMFYUI_URL", raising=False)
    st = run("um_comfy", {"op": "status"}, ctx)
    assert st["checkpoints"] == ["sd15.safetensors"] and st["version"] == "0.3.60"
    r = run("um_comfy", {"op": "image", "prompt": "a red health potion", "sprite": True, "seed": 7}, ctx)
    assert r["checkpoint"] == "sd15.safetensors" and r["seed"] == 7 and r["size"] == [512, 512]
    assert [o["name"] for o in r["outputs"]] == ["a_red_health_potion.png", "a_red_health_potion_cut.png"]
    assert "plain flat white background" in fake.prompts[-1]["6"]["inputs"]["text"]
    assert Path(r["outputs"][0]["file"]).is_relative_to(Path(ctx.config.cache) / "universal_modder" / "comfy")
    wf = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}, "_meta": {"title": "Prompt"}},
          "9": {"class_type": "SaveImage", "inputs": {}}}
    r = run("um_comfy", {"op": "run", "workflow": wf, "set": ["Prompt.text=a blue potion", "9.seed:=42"], "name": "potion"}, ctx)
    assert fake.prompts[-1]["6"]["inputs"]["text"] == "a blue potion" and fake.prompts[-1]["9"]["inputs"]["seed"] == 42
    assert r["outputs"][0]["name"] == "potion.png"


def test_comfy_refuses_odd_urls_and_ui_workflows(ctx, monkeypatch):
    monkeypatch.setattr(um_comfy, "_req", FakeComfy())
    with pytest.raises(ValueError, match="http"):
        run("um_comfy", {"op": "status", "url": "file:///etc/passwd"}, ctx)
    with pytest.raises(ValueError, match="Export \\(API\\)"):
        run("um_comfy", {"op": "run", "workflow": {"nodes": [], "links": []}}, ctx)
    with pytest.raises(ValueError, match="prompt"):
        run("um_comfy", {"op": "image"}, ctx)


# -------------------------------------------------------------------------------------------------------- um_render3d

def fake_blender(calls):
    def run_(cmd, **kw):
        calls.append((cmd, kw))
        cfg = json.loads(Path(cmd[-1]).read_text())
        n = 0
        for anim, spec in cfg["anims"].items():
            for k in range(cfg["camera"]["headings"]):
                for f in range(spec["frames"]):
                    Image.new("RGBA", tuple(cfg["canvas"]), (k * 40, f * 40, 0, 255)).save(Path(cfg["out_dir"]) / f"{anim}_{k:02d}_{f:03d}.png")
                    n += 1
        return subprocess.CompletedProcess(cmd, 0, f"UM_RENDER_DONE {n} images -> {cfg['out_dir']}\n", "")
    return SimpleNamespace(run=run_, TimeoutExpired=subprocess.TimeoutExpired)


def test_render3d_frames_sheets_and_mod(ctx, tmp_path, monkeypatch):
    from gbox import blender_copy
    calls = []
    monkeypatch.setattr(blender_copy, "find_blender", lambda: "C:/Blender/blender.exe")
    monkeypatch.setattr(um_render3d, "subprocess", fake_blender(calls))
    glb = tmp_path / "drone.glb"
    glb.write_bytes(b"glTF")
    r = run("um_render3d", {"path": str(glb), "preset": "side", "canvas": "32x24", "anims": "idle:2:bob,walk:3:walk",
                            "mod": "drone", "game_id": GID, "dest": "Sprites"}, ctx)
    assert r["frames"] == 10 and [s["name"] for s in r["sheets"]] == ["drone_idle_sheet.png", "drone_walk_sheet.png"]
    walk = r["sheets"][1]
    assert (walk["headings"], walk["frames_per_heading"], walk["frame_size"]) == (2, 3, [32, 24])
    assert Image.open(io.BytesIO(ctx.artifacts[-1][1])).size == (96, 48)
    assert calls[0][0][0] == "C:/Blender/blender.exe" and calls[0][1]["timeout"] == 3300
    assert not Path(calls[0][0][-1]).exists()                      # the temp config is cleaned up
    assert (Path(r["staged"]["dir"]) / "Sprites" / "drone_walk_sheet.png").is_file()


def test_render3d_refuses_oversized_jobs_and_bad_presets(ctx, tmp_path, monkeypatch):
    from gbox import blender_copy
    monkeypatch.setattr(blender_copy, "find_blender", lambda: "blender")
    monkeypatch.setattr(um_render3d, "subprocess", fake_blender([]))
    glb = tmp_path / "m.glb"
    glb.write_bytes(b"glTF")
    with pytest.raises(ValueError, match="limit is 512"):
        run("um_render3d", {"path": str(glb), "preset": "aoe2", "headings": 64, "anims": "a:9"}, ctx)
    with pytest.raises(ValueError, match="preset"):
        run("um_render3d", {"path": str(glb), "preset": "fisheye"}, ctx)


# ------------------------------------------------------------------------------------------- registration + chat agent

UM_TOOLS = ["um_scan", "um_kb", "um_backup", "um_publish_check", "um_mod", "um_sprite", "um_comfy", "um_render3d"]


def test_tools_are_registered_for_workers_and_mcp():
    assert "universal_modder" in tools._load_tool_modules.__defaults__[0] and "universal_modder" not in tools.LOAD_ERRORS
    for name in UM_TOOLS:
        info = registry.REGISTRY[name].info()                  # what /api/registry (and so MCP list_tools) serves
        assert info.description and info.input_schema["type"] == "object", name
    assert registry.REGISTRY["um_scan"].permissions == ["read"]
    assert "file_mutation" in registry.REGISTRY["um_backup"].permissions


def test_agent_offers_every_um_tool_and_routes_jobs_to_the_right_worker():
    specs = {t["function"]["name"]: t["function"] for t in agent.tool_specs()}
    assert set(UM_TOOLS) <= set(specs) and "op" in specs["um_backup"]["parameters"]["properties"]
    assert "um_scan" in agent.SYSTEM and "never into the game install" in agent.SYSTEM
    assert not any(agent._modifies_game(n, {"op": "stage"}) for n in UM_TOOLS)   # none of them pokes the running game
    a = object.__new__(agent.Agent)
    sent = []

    def job(tool, inp, node=None, limit=900, worker=None):
        sent.append((tool, inp, node, worker))
        return {"state": "succeeded", "output": {"result": {"ok": tool}}}
    a._job = job
    assert a.um_scan(session_id="worker-abc123") == {"ok": "um_scan"}
    assert a.um_sprite(op="info", artifact="f" * 64, worker="pc2", seed=None) == {"ok": "um_sprite"}
    assert a.um_kb(op="search", query="terraria") == {"ok": "um_kb"}
    assert sent == [("um_scan", {"session_id": "worker-abc123"}, None, "worker"),
                    ("um_sprite", {"op": "info", "artifact": "f" * 64}, None, "pc2"),
                    ("um_kb", {"op": "search", "query": "terraria"}, "windows", None)]
    a._job = lambda *_a, **_k: {"state": "failed", "error": "no worker", "output": None}
    assert a.um_backup(op="list")["error"] == "no worker"
