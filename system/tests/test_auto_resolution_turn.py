from gbox.agent import ChatHub


class MemoryStore:
    def __init__(self):
        self.docs = {}

    def get(self, kind, key):
        return self.docs.get((kind, key))

    def put(self, kind, key, value):
        self.docs[(kind, key)] = value


class Agent:
    launched = []

    def run(self, messages, emit, context):
        emit({"type": "assistant", "text": "Writer still needs implementation."})
        return {"usage": {"in": 12, "out": 5}, "tools": {"characters": 1}}


def test_auto_resolution_reuses_its_report_and_keeps_unverified_work_open():
    store = MemoryStore()
    hub = ChatHub(store, lambda model: Agent())
    chat = hub.get("chat1")
    chat["messages"].append({"role": "user", "content": "Fix swap"})
    store.put("chat", "chat1", chat)
    calls = []

    def api_requests(op, body):
        calls.append((op, body))
        if op == "get":
            return {"id": "report1"}

    hub._turn("chat1", "Fix swap", {"request_id": "report1", "resolve_auto_report": True}, api_requests)
    assert not any(op == "create" for op, _ in calls)
    assert any(op == "metrics" and body["id"] == "report1" and body["tokens_in"] == 12 for op, body in calls)
    assert any(op == "reply" and "needs implementation" in body["text"] for op, body in calls)
    assert not any(op == "status" and body["status"] == "done" for op, body in calls)
