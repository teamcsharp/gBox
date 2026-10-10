from pathlib import Path

from gbox.audio_volume import apply_volume, belongs_to_gbox


class Process:
    def __init__(self, pid, executable, parents=()):
        self.pid = pid
        self._executable = executable
        self._parents = parents

    def parents(self):
        return self._parents

    def exe(self):
        return str(self._executable)


class Volume:
    def __init__(self, level=1.0):
        self.level = level
        self.set_to = []

    def GetMasterVolume(self):
        return self.level

    def SetMasterVolume(self, level, _context):
        self.level = level
        self.set_to.append(level)


class Session:
    def __init__(self, process):
        self.Process = process
        self.SimpleAudioVolume = Volume()


def test_volume_applies_only_to_gbox_sessions_and_new_games(tmp_path: Path):
    runtime = tmp_path / "gBox" / "runtime"
    owner = Process(10, tmp_path / "gBox.exe")
    renderer = Session(Process(11, tmp_path / "electron.exe", [owner]))
    game = Session(Process(12, runtime / "retroarch.exe"))
    unrelated = Session(Process(13, tmp_path / "other" / "retroarch.exe"))
    sessions = [renderer, game, unrelated, Session(None)]

    assert belongs_to_gbox(renderer.Process, owner.pid, runtime)
    assert belongs_to_gbox(game.Process, owner.pid, runtime)
    assert not belongs_to_gbox(unrelated.Process, owner.pid, runtime)
    assert apply_volume(0.3, owner.pid, runtime, sessions) == 2
    assert renderer.SimpleAudioVolume.set_to == [0.3]
    assert game.SimpleAudioVolume.set_to == [0.3]
    assert unrelated.SimpleAudioVolume.set_to == []

    launched_later = Session(Process(14, runtime / "dolphin.exe"))
    assert apply_volume(0.3, owner.pid, runtime, sessions + [launched_later]) == 3
    assert renderer.SimpleAudioVolume.set_to == [0.3]
    assert launched_later.SimpleAudioVolume.set_to == [0.3]
