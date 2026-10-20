"""#2410 gBrain milestone 1: GoldenEye 007's AI command set read from the n64decomp/007 aicommands.def."""
from gbox.bond_ai import commands as A

SNIPPET = """
#if 0
_AI_CMD(GONEXT,
    (BYTE(LABEL)),
    {})
#endif
/* #define CMDNAME GOTO_NEXT */
#define CMDNAME GotoNext
#define DESCRIPTION \\
/*******************************************************************************
* Skips all commands between this command and LABEL
* @param     LABEL: 8bit Integer/enum ID of label to Go To
*******************************************************************************/
#define PARAMS BYTE(LABEL)
_AI_CMD({ break; })
_AI_CMD_POLYMORPH(,
                  BREAK,
                  (LABEL),
                  (LABEL))
#undef CMDNAME
#define CMDNAME SetChrAiList
#define DESCRIPTION \\
/* Set Chr's AI list */
#define PARAMS BYTE(CHR_NUM), \\
               DBYTE(AI_LIST_ID) /*list*/
_AI_CMD({ break; })
#define CMDNAME PRINT
#define DESCRIPTION \\
/* debug text */
#define PARAMS /*NONE*/
_AI_DEBUG({ break; })
#define CMDNAME Wide
#define DESCRIPTION \\
/* every width */
#define PARAMS BYTE(A), DBYTE(B), TBYTE(C), QBYTE(D)
_AI_CMD({ break; })
"""


def test_parse_skips_disabled_blocks_and_counts_debug_commands():
    cmds = A.parse(SNIPPET)
    assert [(c["opcode"], c["name"]) for c in cmds] == [(0, "GotoNext"), (1, "SetChrAiList"), (2, "PRINT"), (3, "Wide")]
    assert cmds[0]["aliases"] == ["BREAK"] and cmds[0]["params"] == [{"name": "LABEL", "bytes": 1}]
    assert cmds[0]["description"].startswith("Skips all commands") and "@param" in cmds[0]["description"]
    assert [p["bytes"] for p in cmds[1]["params"]] == [1, 2] and cmds[1]["length"] == 4
    assert cmds[2].get("debug") is True and cmds[2]["length"] == 1
    assert cmds[3]["length"] == 1 + 1 + 2 + 3 + 4


def test_committed_table_matches_goldeneye_opcode_range():
    t = A.load()
    cs = t["commands"]
    assert t["count"] == len(cs) == 253                    # GoldenEye's AI opcodes run 0x00..0xFC
    assert [c["opcode"] for c in cs] == list(range(253))
    names = A.by_opcode()
    assert names[0x00]["name"] == "GotoNext" and names[0x02]["name"] == "Label" and names[0x04]["name"] == "EndList"
    assert names[0xAD]["name"] == "PRINT" and names[0xAD].get("debug")
    assert names[0xFC]["name"] == "ObjectRocketLaunch"
    for c in cs:
        assert c["length"] == 1 + sum(p["bytes"] for p in c["params"])           # PRINT's text comes on top
        assert all(1 <= p["bytes"] <= 4 for p in c["params"]) and c["description"]
    assert len({c["name"] for c in cs}) == 253


def test_print_is_variable_length_text():
    assert A.by_opcode()[0xAD].get("variable") == "nul_terminated_text"


def test_ai_list_decoder_walks_commands_and_print_text():
    import struct
    from gbox.bond_ai import ailists as L
    t = A.by_opcode()
    lst = bytes([0x00, 0x05]) + bytes([0xAD]) + b"run" + bytes(1) + bytes([0x05, 0x01, 0x00, 0x07]) + bytes([0x04])
    setup = bytearray(40)
    struct.pack_into(">10I", setup, 0, 0, 0, 0, 0, 0, 40, 0, 0, 0, 0)
    setup += struct.pack(">II", 56, 0x401) + struct.pack(">II", 0, 0) + lst
    out = L.ai_lists(bytes(setup), t)
    assert [(x["id"], x["kind"]) for x in out] == [(0x401, "character")]
    cmds = out[0]["commands"]
    assert [c["name"] for c in cmds] == ["GotoNext", "PRINT", "SetChrAiList", "EndList"]
    assert cmds[1]["args"] == {"TEXT": "run"} and cmds[2]["args"] == {"CHR_NUM": 1, "AI_LIST_ID": 7}
    assert "SetChrAiList(CHR_NUM=1, AI_LIST_ID=7)" in L.text(out[0])
    try:
        L.decode_list(bytes([0x00, 0x05, 0xFD]), 0, t)
        raise AssertionError("an unknown opcode must stop the decoder")
    except L.DecodeError as e:
        assert "0xfd" in str(e)


def test_owned_goldeneye_rom_decodes_every_ai_list():
    """On the Spark: every AI list of the owned PAL ROM's 34 setup files decodes to its EndList (662 lists)."""
    from pathlib import Path
    from gbox.bond_ai import ailists as L
    rom = Path.home() / "gbox-cache/eecd1708cb2b8d14/rom.z64"
    if not rom.is_file():
        import pytest
        pytest.skip("owned GoldenEye ROM is not cached here")
    levels = L.rom_levels(rom)
    assert len(levels) == 34 and sum(len(v) for v in levels.values()) == 662
    assert all(lst["commands"][-1]["name"] == "EndList" for v in levels.values() for lst in v)
