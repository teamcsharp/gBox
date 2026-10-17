"""Clickable multiple-choice questionnaires in the chat (#69): the agent asks via ask_user, the UI shows
options the operator clicks, and the picked answer arrives as the next user message."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import gbox.agent as agent_mod
from gbox.agent import SYSTEM, ChatHub, tool_specs


class APIStub:
    """httpx-shaped stub for the read-only endpoints Agent.run touches before the first LLM call."""
    def get(self, path, params=None, **kw):
        return SimpleNamespace(json=lambda: [])   # /api/kb/search and /api/recipes both answer with arrays

    def post(self, path, **kw):
        raise AssertionError(f"unexpected API write in this test: {path}")


def fake_agent(model="gpt-oss:20b"):
    a = object.__new__(agent_mod.Agent)
    a.llm_url, a.model, a.searx, a.vision = "http://llm", model, "http://searx", None
    a.api = APIStub()   # type: ignore[assignment]
    a.snapshots = {}
    a.game = None
    a.launched = []
    return a


def llm_reply(tool_calls):
    return {"choices": [{"message": {"content": "", "tool_calls": tool_calls}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2}}


def ask_user_call(options, question="Which one?", call_id="call_1"):
    return {"id": call_id, "type": "function",
            "function": {"name": "ask_user", "arguments": json.dumps({"question": question, "options": options})}}


@pytest.fixture
def scripted(monkeypatch):
    def set_reply(tool_calls):
        monkeypatch.setattr(agent_mod.httpx, "post",
                            lambda *a, **k: SimpleNamespace(json=lambda: llm_reply(tool_calls)))
    return set_reply


def drive(agent, text):
    events, messages = [], [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]
    res = agent.run(messages, events.append, {})
    return res, events, messages


def drive_messages(agent, messages):
    """Run another turn on the SAME history, as ChatHub does when the operator clicks an option."""
    events = []
    res = agent.run(messages, events.append, {})
    return res, events, messages


def test_tool_spec_and_system_prompt_commit_to_clickable_questionnaires():
    spec = next(t["function"] for t in tool_specs() if t["function"]["name"] == "ask_user")
    assert spec["parameters"]["required"] == ["question", "options"]
    assert "click" in spec["description"]
    assert "call ask_user with" in SYSTEM and "the operator clicks one" in SYSTEM


def test_choices_event_emitted_with_cleaned_deduplicated_options(scripted):
    agent = fake_agent()
    scripted([ask_user_call([" Pikmin ", "Pikmin", "", " Zelda "])])
    res, events, messages = drive(agent, "Make my character bigger.")
    choices = [e for e in events if e["type"] == "choices"]
    assert len(choices) == 1
    assert choices[0]["question"] == "Which one?"
    assert choices[0]["options"] == ["Pikmin", "Zelda"]          # stripped, deduped, blanks dropped
    assert res["usage"]["out"] == 2
    assert messages[-1]["role"] == "tool"
    assert messages[-1]["content"] == "asked; the operator's choice is the next message"


def test_questionnaire_without_usable_options_falls_back_to_plain_text(scripted):
    agent = fake_agent()
    scripted([ask_user_call(["", "   ", None], question="Which save slot?")])
    _, events, messages = drive(agent, "Load my save.")
    assert not [e for e in events if e["type"] == "choices"]      # no empty button box
    texts = [e for e in events if e["type"] == "assistant"]
    assert texts and texts[-1]["text"] == "Which save slot?"
    assert messages[-1]["role"] == "tool" and "no clickable options" in messages[-1]["content"]


def test_more_than_eight_options_are_capped(scripted):
    agent = fake_agent()
    scripted([ask_user_call([f"option {i}" for i in range(12)])])
    _, events, _ = drive(agent, "Which one?")
    choices = [e for e in events if e["type"] == "choices"]
    assert len(choices[0]["options"]) == 8


def test_clicked_answer_is_explained_to_the_model_on_the_next_turn(scripted, monkeypatch):
    agent = fake_agent()
    scripted([ask_user_call(["Phantasy Star Online", "Zelda: Ocarina of Time"],
                            question="Which game are you playing?")])
    _, events, messages = drive(agent, "Make me stronger.")
    assert any(e["type"] == "choices" for e in events)

    sent = []
    monkeypatch.setattr(agent_mod.httpx, "post", lambda *a, **k: sent.append(k.get("json") or {}) or
        SimpleNamespace(json=lambda: {"choices": [{"message": {"content": "Phantasy Star Online: boost ATP then."}}],
                                      "usage": {"prompt_tokens": 5, "completion_tokens": 2}}))
    messages.append({"role": "user", "content": "Phantasy Star Online"})          # the click
    res, events2, messages = drive_messages(agent, messages)
    tools = [m for m in messages if m["role"] == "tool"]
    assert tools[-1]["content"] == "the operator answered: Phantasy Star Online"  # ask_user literally returns the pick
    assert messages[-2]["content"] == 'My answer to the question "Which game are you playing?": Phantasy Star Online. Go ahead with this.'
    assert all(t["function"]["name"] != "ask_user" for t in sent[-1]["tools"])   # no re-asking on the answer turn
    assert [e["text"] for e in events2 if e["type"] == "assistant"][-1] == "Phantasy Star Online: boost ATP then."
    assert res["tools"] == {}


def test_free_text_after_fallback_questionnaire_becomes_the_answer_too(scripted, monkeypatch):
    agent = fake_agent()
    scripted([ask_user_call(["   "], question="Which save slot?")])               # fallback: plain text, no options
    _, events, messages = drive(agent, "Load my save.")
    assert any(e["type"] == "assistant" for e in events) and not [e for e in events if e["type"] == "choices"]
    monkeypatch.setattr(agent_mod.httpx, "post", lambda *a, **k: SimpleNamespace(json=lambda:
        {"choices": [{"message": {"content": "Loading slot 3."}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}))
    messages.append({"role": "user", "content": "Use slot 3."})
    drive_messages(agent, messages)
    tools = [m for m in messages if m["role"] == "tool"]
    assert tools[-1]["content"] == "the operator answered: Use slot 3."
    assert messages[-2]["content"] == 'My answer to the question "Which save slot?": Use slot 3. Go ahead with this.'


def test_normal_turn_after_answer_gets_no_rewrite_or_note(scripted, monkeypatch):
    agent = fake_agent()
    scripted([])
    monkeypatch.setattr(agent_mod.httpx, "post", lambda *a, **k: SimpleNamespace(json=lambda:
        {"choices": [{"message": {"content": "done."}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}))
    _, _, messages = drive(agent, "Thanks!")
    assert not [m for m in messages if m["role"] == "system" and "their answer" in m["content"]]
    assert not [m for m in messages if m["role"] == "tool" and str(m["content"]).startswith("the operator answered")]
    assert all(str(m.get("content", "")).find("Go ahead with this.") < 0 for m in messages if m["role"] == "user")


def test_hallucinated_ask_user_is_not_honoured_on_the_answer_turn(scripted, monkeypatch):
    agent = fake_agent()
    scripted([ask_user_call(["Phantasy Star Online"], question="Which game are you playing?")])
    _, _, messages = drive(agent, "Make me stronger.")
    messages.append({"role": "user", "content": "Phantasy Star Online"})
    n = [0]
    def fake_post(*a, **k):
        n[0] += 1
        if n[0] == 1:   # a weak model may still emit ask_user although the tool was withheld this turn
            return SimpleNamespace(json=lambda: llm_reply([ask_user_call(["Again?"], question="Which game?", call_id="c2")]))
        return SimpleNamespace(json=lambda: {"choices": [{"message": {"content": "Boosting PSO ATP now."}}],
                                             "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    monkeypatch.setattr(agent_mod.httpx, "post", fake_post)
    _, events2, messages = drive_messages(agent, messages)
    assert not [e for e in events2 if e["type"] == "choices"]      # no second questionnaire
    assert [e["text"] for e in events2 if e["type"] == "assistant"][-1] == "Boosting PSO ATP now."
    assert any(m["role"] == "tool" and "not available in this turn" in m["content"] for m in messages)


def test_chat_hub_persists_questionnaire_and_frees_the_conversation():
    class Store:
        def __init__(self):
            self.chat = {"id": "chat", "events": [], "messages": [], "busy": True, "model": None, "queue": []}
        def get(self, kind, identifier):
            return self.chat
        def put(self, kind, identifier, value):
            self.chat = value

    class QuestionnaireAgent:
        def run(self, messages, emit, context):
            emit({"type": "choices", "question": "Which game?", "options": ["Pikmin", "Zelda"]})
            return {"usage": {"in": 3, "out": 1}, "tools": {"ask_user": 1}}

    actions = []
    hub = ChatHub(Store(), lambda _: QuestionnaireAgent())
    hub._gap_report = lambda *_: None   # type: ignore[method-assign]
    hub._turn("chat", "Make me stronger.", {}, lambda op, body: actions.append((op, body)) or "request")
    events = hub.get("chat")["events"]
    assert any(e["type"] == "choices" and e["options"] == ["Pikmin", "Zelda"] for e in events)
    assert hub.get("chat")["busy"] is False                          # the click can be sent right away
    statuses = [body for op, body in actions if op == "status"]
    assert statuses[-1]["status"] == "done"


def test_desktop_client_renders_clickable_options_and_sends_the_pick():
    src = Path(__file__).resolve().parents[1] / "clients" / "desktop" / "index.html"
    html = src.read_text(encoding="utf-8")
    assert 'e.type === "choices"' in html and 'choicesHtml(' in html
    assert 'button data-pick=' in html                                  # each option is a button
    assert 'chatSend(b.dataset.pick)' in html                           # clicking sends the option text
    assert 'classList.add("done")' in html                              # answered questionnaires lock
    assert '[?:]\\s*' in html                                           # plain-text trailing-list fallback exists
