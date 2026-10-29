"""Acceptance through a real Dify HTTP server, its sandbox and real LLM plugin.

Requires an initialized Dify stack, configured model, game and PowerContext.
No node handler is called directly and no API response is mocked.
"""

import hashlib
import json
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "deploy"))
from console import Console

OUT = ROOT / "evidence/dify"
OUT.mkdir(parents=True, exist_ok=True)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))


def check_run(console, app_id, name, action, player, conversation=None, ai=True):
    events = console.run(app_id, action, player, conversation)
    save(
        name + ".json",
        {
            "app_id": app_id,
            "request": {
                "query": action,
                "inputs": {"player": player},
                "conversation_id": conversation,
            },
            "events": events,
        },
    )
    errors = [e for e in events if e.get("event") == "error"]
    assert not errors, errors
    finished = [e["data"] for e in events if e.get("event") == "workflow_finished"]
    assert len(finished) == 1 and finished[0]["status"] == "succeeded", finished
    nodes = {
        e["data"]["node_id"]: e["data"]
        for e in events
        if e.get("event") == "node_finished"
    }
    expected = (
        ["start", "encode", "http", "parse", "narrate", "answer"]
        if ai
        else ["start", "encode", "http", "parse", "answer"]
    )
    assert set(nodes) == set(expected), (list(nodes), expected)
    assert all(node["status"] == "succeeded" for node in nodes.values()), nodes
    assert nodes["http"]["outputs"]["status_code"] == 200
    state = json.loads(nodes["http"]["outputs"]["body"])
    if ai:
        assert nodes["narrate"]["outputs"]["text"].strip(), "LLM returned no text"
    conversation_ids = [
        e["conversation_id"] for e in events if e.get("conversation_id")
    ]
    assert conversation_ids, "Dify conversation ID missing"
    run_id = finished[0].get("id") or finished[0].get("workflow_run_id")
    summary = {
        "file": name + ".json",
        "action": action,
        "workflow_run_id": run_id,
        "conversation_id": conversation_ids[-1],
        "nodes": {k: v["status"] for k, v in nodes.items()},
        "state": state["state"],
        "notebook": state["notebook"],
    }
    if ai:
        summary["llm_output"] = nodes["narrate"]["outputs"]["text"]
    print(action, "→", finished[0]["status"], len(nodes), "nodes", flush=True)
    return state, conversation_ids[-1], summary


if __name__ == "__main__":
    c = Console().login()
    imports = {}
    for file in ["time-loop-no-model.yml", "time-loop.yml"]:
        result = c.import_app(ROOT / file)
        imports[file] = {
            "response": result,
            "sha256": hashlib.sha256((ROOT / file).read_bytes()).hexdigest(),
        }
    save("imports.json", imports)
    app_id = imports["time-loop.yml"]["response"]["app_id"]
    no_model_id = imports["time-loop-no-model.yml"]["response"]["app_id"]
    runs = []
    _, _, brief = check_run(
        c, no_model_id, "00-no-model", "开始", secrets.token_hex(16), ai=False
    )
    runs.append(brief)
    player = secrets.token_hex(16)
    conversation = None
    for index, action in enumerate(
        [
            "开始",
            "看收据",
            "听广播",
            "重来",
            "状态",
            "买牛奶",
            "拉电闸",
            "递牛奶",
            "开门",
        ],
        1,
    ):
        # Deliberately drop all Dify conversation history before checking memory reuse.
        if action == "状态":
            old_conversation = conversation
            conversation = None
        result, conversation, brief = check_run(
            c, app_id, f"{index:02d}-ai", action, player, conversation
        )
        runs.append(brief)
        if action == "开始":
            assert result["notebook"] == []
        if action == "听广播":
            assert len(result["notebook"]) == 2
        if action == "状态":
            assert len(result["notebook"]) == 2 and conversation != old_conversation
            assert result["powercontext"]["status"] == "ready"
        if action == "开门":
            assert result["won"] and "真结局" in result["event"]
    outsider = secrets.token_hex(16)
    state, other_conversation, brief = check_run(
        c, app_id, "10-isolation", "开始", outsider
    )
    assert state["notebook"] == []
    runs.append(brief)
    state, _, brief = check_run(
        c, app_id, "11-bad-ending", "开门", outsider, other_conversation
    )
    assert (
        not state["won"] and state["state"]["loop"] == 2 and "坏结局" in state["event"]
    )
    runs.append(brief)
    published = c.call(
        "POST",
        "/apps/" + app_id + "/workflows/publish",
        json={
            "marked_name": "Verified game",
            "marked_comment": "Real Dify, sandbox, PowerContext and LLM acceptance",
        },
    )
    save("publication.json", published)
    summary = {
        "result": "PASS",
        "verification": "real Dify 1.13.0 Console HTTP import and Chatflow execution",
        "dify_runtime_verified": True,
        "llm_verified": True,
        "mock_services": False,
        "provider": "langgenius/openai_api_compatible/openai_api_compatible",
        "model": "deepseek-flash",
        "app_id": app_id,
        "checks": [
            "both DSL files imported",
            "all nodes succeeded",
            "real LLM returned dialogue",
            "PowerContext recall consumed by HTTP node",
            "new Dify conversation reused memory",
            "player isolation",
            "true ending",
            "bad ending",
            "workflow published",
        ],
        "imports": imports,
        "runs": runs,
    }
    save("summary.json", summary)
    (ROOT / ".runtime/verified-apps.json").write_text(
        json.dumps({"ai": app_id, "no_model": no_model_id})
    )
    print("PASS: Dify import, all nodes, real LLM and game acceptance", flush=True)
