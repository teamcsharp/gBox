

def test_a_tool_error_carries_reas_own_message_and_the_next_step():
    """2026-10-19: Hermes saw only 'inspect the preserved result artifact' for a PS2 ELF REA cannot open."""
    import json as _json
    from gbox import rea_tool as T
    elf = {"isError": True, "structuredContent": {"error": {"code": "target_unavailable", "message":
           "Cannot open artifact: unsupported ELF architecture. Check that the path exists"}}}
    text = T.tool_error_text(elf)
    assert "unsupported ELF architecture" in text and "MIPS:LE:32:R5900" in text and text.startswith("REA target_unavailable")
    none_open = {"isError": True, "content": [{"type": "text", "text": _json.dumps(
        {"error": {"code": "target_unavailable", "message": "No app is open. Ask the user which app to investigate"}})}]}
    assert "rea_open_binary" in T.tool_error_text(none_open)
    assert T.tool_error_text({"isError": True}) == "REA reported a tool error; inspect the preserved result artifact"
