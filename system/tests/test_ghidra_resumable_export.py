"""Durable native-decompiler outcomes, independent of a local Ghidra installation."""
import hashlib
import json
from types import SimpleNamespace as NS

import pytest

from gbox import ghidra_bridge_server as S


def function(address):
    return NS(getEntryPoint=lambda: address, getName=lambda *args: "fn_" + address,
              getBody=lambda: NS(getNumAddresses=lambda: 16), getReturnType=lambda: "void",
              getParameterCount=lambda: 0, isThunk=lambda: False)


class Exporter(S.Bridge):
    def __init__(self, root):
        super().__init__()
        self.source = root / "game.elf"
        self.source.write_bytes(b"analyzed executable")
        self.rows = [function("00001000"), function("00002000"), function("00003000")]
        self.program = NS(getFunctionManager=lambda: NS(getFunctions=lambda forward: iter(self.rows),
            getFunctionContaining=lambda a: None), getReferenceManager=lambda: NS(getReferencesTo=lambda a: []),
            getListing=lambda: NS(getDefinedData=lambda *args: iter(())))
        self.calls, self.fail = [], {}

    def info(self):
        return {"executable_path": str(self.source), "executable_sha256": hashlib.sha256(b"analyzed executable").hexdigest()}

    def decompile(self, target, **kwargs):
        addr = target.removeprefix("0x")
        self.calls.append(addr)
        if isinstance(self.fail.get(addr), BaseException):
            raise self.fail[addr]
        return {"decompiled": "void f(void) {}", "signature": "void f(void)", "calling_convention": "default",
                "callers": [], "callees": [], **self.fail.get(addr, {})}

    def xrefs_from(self, target, limit):
        assert limit == 0, "exports request the complete data-reference list"
        return {"data_refs": [], "truncated": False}


def read(root, name="_manifest.json"):
    return json.loads((root / name).read_text())


def test_batches_resume_without_truncating_inventory_or_repeating_success(tmp_path):
    b, out = Exporter(tmp_path), tmp_path / "export"
    first = b.export(out, limit=1)
    assert first["discovered"] == 3 and first["success"] == 1 and first["pending"] == 2
    assert not first["complete"]
    second = b.export(out, limit=2)
    assert second["all_success"] and second["success"] == 3
    assert b.calls == ["00001000", "00002000", "00003000"]
    assert len(read(out, "_index.json")) == 3
    assert b.export(out)["attempted_this_batch"] == 0


def test_errors_and_timeouts_never_become_success_and_retry_is_explicit(tmp_path):
    b, out = Exporter(tmp_path), tmp_path / "export"
    b.fail = {"00001000": {"decompiled": None, "error": "no output"}, "00002000": {"timed_out": True}}
    result = b.export(out)
    assert result["complete"] and not result["all_success"]
    assert (result["error"], result["timeout"], result["success"]) == (1, 1, 1)
    assert set(read(out, "_index.json")) == {"00003000"}
    assert b.export(out)["attempted_this_batch"] == 0
    b.fail.clear()
    assert b.export(out, retry_failed=True)["all_success"]
    assert read(out)["outcomes"]["00001000"]["attempts"] == 2


def test_process_loss_recovers_running_function_and_clears_old_completion(tmp_path):
    b, out = Exporter(tmp_path), tmp_path / "export"
    b.fail["00001000"] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        b.export(out)
    manifest = read(out)
    assert manifest["outcomes"]["00001000"]["state"] == "running"
    assert not manifest["summary"]["complete"]
    b.fail.clear()
    assert b.export(out)["all_success"]


@pytest.mark.parametrize("damage", ["delete", "corrupt"])
def test_missing_or_corrupt_function_is_reexported(tmp_path, damage):
    b, out = Exporter(tmp_path), tmp_path / "export"
    b.export(out)
    target = out / "00001000.json"
    target.unlink() if damage == "delete" else target.write_text("corrupt")
    result = b.export(out)
    assert result["all_success"] and result["attempted_this_batch"] == 1
    assert b.calls.count("00001000") == 2


def test_changed_binary_inventory_and_legacy_export_are_not_adopted(tmp_path):
    b, out = Exporter(tmp_path), tmp_path / "export"
    b.export(out)
    original = (out / "_manifest.json").read_bytes()
    b.source.write_bytes(b"different executable")
    with pytest.raises(ValueError, match="do not match"):
        b.export(out)
    assert (out / "_manifest.json").read_bytes() == original
    b.source.write_bytes(b"analyzed executable")
    b.rows.append(function("00004000"))
    with pytest.raises(ValueError, match="inventory changed"):
        b.export(out)
    (out / "_manifest.json").unlink()
    with pytest.raises(ValueError, match="no matching manifest"):
        b.export(out)


def test_pending_functions_are_attempted_before_retrying_failures(tmp_path):
    b, out = Exporter(tmp_path), tmp_path / "export"
    b.fail["00001000"] = RuntimeError("persistent failure")
    b.export(out, limit=1)
    b.export(out, limit=2, retry_failed=True)
    assert b.calls == ["00001000", "00002000", "00003000"]


def test_an_unanalyzed_program_cannot_report_complete(tmp_path):
    b = Exporter(tmp_path)
    b.rows.clear()
    with pytest.raises(ValueError, match="no functions"):
        b.export(tmp_path / "export")
