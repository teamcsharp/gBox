"""Put every operator prompt from the Claude Code transcripts into the gBox inbox (oldest first, with metrics).

Idempotent: the server skips prompts already in the inbox (matched by text), drops harness noise (task notifications)
and renumbers requests oldest-first. Run any time; the Stop hook keeps new prompts flowing through agent_ledger.py.
"""
import datetime as dt
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prompt_history as ph                                        # noqa: E402

SERVER = "http://10.89.1.246:8765"


def ts(iso: str) -> float:
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def main():
    tok = Path("//10.89.1.246/ehm_eckx/gBox/system/gbox-data/api_token").read_text().strip()
    items = []
    for p in ph.transcript_prompts():
        t = ts(p["ts"])
        items.append({"text": p["text"], "created": t, "completed": t + p["secs"], "source": "chat",
                      "metrics": {"tokens_in": p["tokens_in"], "tokens_out": p["tokens_out"], "duration_s": round(p["secs"], 1),
                                  "model": (p["models"] or [None])[0], "files_changed": p["file_list"], "turns": 1}})
    r = httpx.post(f"{SERVER}/api/requests/import", json=items, headers={"authorization": f"Bearer {tok}"}, timeout=120)
    r.raise_for_status()
    print(f"{len(items)} transcript prompts -> {r.json()}")


if __name__ == "__main__":
    main()
