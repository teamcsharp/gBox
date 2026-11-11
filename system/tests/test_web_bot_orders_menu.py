"""#3871: the web client's session right-click menu offers a 'Tell the bot…' dropdown fed by the directive commands."""
from pathlib import Path

from gbox.mercs import directives

HTML = (Path(__file__).resolve().parents[1] / "clients" / "web" / "index.html").read_text(encoding="utf-8")


def test_menu_has_dropdown_wired_to_directive_endpoint():
    assert 'class="botorders"' in HTML
    assert "/directive`, { command: cmd }" in HTML
    assert "webBotOrdersFill(sid, bo)" in HTML


def test_fight_command_exists_and_posts():
    assert "fight" in directives.COMMANDS and "hunt" in directives.COMMANDS
    row = directives.post("t3871-sid", "fight", source="test")
    assert directives.latest("t3871-sid")["command"] == "fight" and row
