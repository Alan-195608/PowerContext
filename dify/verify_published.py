"""Verify the published app through Dify's production /v1/chat-messages API."""

import json
from pathlib import Path
import secrets
import sys
import httpx

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "deploy"))
from console import Console

c = Console().login()
app = json.loads((ROOT / ".runtime/verified-apps.json").read_text())["ai"]
key = c.call("POST", "/apps/" + app + "/api-keys", json={})["token"]
private = ROOT / ".runtime/service-api-key.json"
private.write_text(json.dumps({"app_id": app, "key": key}))
private.chmod(0o600)
player = secrets.token_hex(16)
conversation = None
runs = []
with httpx.Client(timeout=120, trust_env=False) as client:
    for index, query in enumerate(["开始", "看收据", "状态"]):
        old = conversation
        if query == "状态":
            conversation = None
        body = {
            "inputs": {"player": player},
            "query": query,
            "response_mode": "streaming",
            "user": "published-app-verifier",
        }
        if conversation:
            body["conversation_id"] = conversation
        events = []
        with client.stream(
            "POST",
            c.url + "/v1/chat-messages",
            headers={"Authorization": "Bearer " + key},
            json=body,
        ) as r:
            if r.status_code != 200:
                r.read()
                raise RuntimeError(str(r.status_code) + ": " + r.text[:1000])
            for line in r.iter_lines():
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    if raw and raw != "[DONE]":
                        events.append(json.loads(raw))
        assert not [e for e in events if e.get("event") == "error"]
        finished = [e["data"] for e in events if e.get("event") == "workflow_finished"]
        assert len(finished) == 1 and finished[0]["status"] == "succeeded", finished
        conversation = next(
            e["conversation_id"] for e in events if e.get("conversation_id")
        )
        answer = "".join(
            e.get("answer", "") for e in events if e.get("event") == "message"
        )
        assert answer.strip()
        if query == "状态":
            assert conversation != old
            assert "收据背面写着" in answer
        result = {"endpoint": "/v1/chat-messages", "request": body, "events": events}
        (ROOT / f"evidence/dify/production-{index:02d}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
        runs.append(
            {
                "query": query,
                "conversation_id": conversation,
                "workflow_run_id": finished[0].get("id"),
                "answer": answer,
                "status": finished[0]["status"],
            }
        )
        print("Published API", query, "→ succeeded", flush=True)
(ROOT / "evidence/dify/production-summary.json").write_text(
    json.dumps(
        {"result": "PASS", "app_id": app, "mock_services": False, "runs": runs},
        ensure_ascii=False,
        indent=2,
    )
)
