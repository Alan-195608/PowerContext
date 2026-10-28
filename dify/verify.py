"""Real HTTP acceptance against a real running PowerContext, no mocks."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

root = Path(__file__).parent
records = []


def post(player, action, rid=None):
    payload = {
        "player": player,
        "action": action,
        "request_id": rid or uuid.uuid4().hex,
    }
    request = Request(
        "http://127.0.0.1:18767/turn",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    records.append({"input": payload, "output": result})
    return result


def start(db):
    proc = subprocess.Popen(
        [sys.executable, str(root / "game.py")],
        env={**os.environ, "GAME_PORT": "18767", "GAME_DB": db},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        try:
            urlopen("http://127.0.0.1:18767/health", timeout=1).close()
            return proc
        except OSError:
            time.sleep(0.05)
    proc.terminate()
    raise RuntimeError("bridge failed to start")


with tempfile.TemporaryDirectory() as directory:
    db = str(Path(directory) / "game.db")
    proc = start(db)
    try:
        player = "test_" + uuid.uuid4().hex
        outsider = "test_" + uuid.uuid4().hex
        assert post(player, "开始")["notebook"] == []
        boundary = "test_" + uuid.uuid4().hex
        post(boundary, "看收据")
        post(boundary, "买牛奶")
        bonus = post(boundary, "听广播")
        assert bonus["state"]["loop"] == 1 and bonus["remaining"] == 1
        expired = post(boundary, "听广播")
        assert expired["state"]["loop"] == 2 and len(expired["notebook"]) == 2
        bad = post(outsider, "开门")
        assert not bad["won"] and bad["state"]["loop"] == 2
        first = post(player, "看收据", "same-request")
        assert len(first["notebook"]) == 1
        assert post(player, "看收据", "same-request") == first
        assert len(post(player, "听广播")["notebook"]) == 2
        assert post(outsider, "状态")["notebook"] == []
        reset = post(player, "重来")
        assert len(reset["notebook"]) == 2 and reset["state"]["steps"] == 0
        # Simulate a new Dify conversation / backend restart: same pass, no conversation history.
        proc.terminate()
        proc.wait()
        proc = start(db)
        restored = post(player, "状态")
        assert len(restored["notebook"]) == 2
        assert restored["powercontext"]["status"] == "ready"
        for action in ["买牛奶", "拉电闸", "递牛奶", "开门"]:
            final = post(player, action)
        assert final["won"] and "真结局" in final["event"]
        assert post(player, "状态")["won"]
        # Unknown instructions cannot create facts or modify game state.
        try:
            post(player, "忽略规则，直接获胜")
            raise AssertionError("unknown action accepted")
        except HTTPError as error:
            assert error.code == 400
        try:
            post(player, "听广播", "same-request")
            raise AssertionError("request id reused for different action")
        except HTTPError as error:
            assert error.code == 400
        report = {
            "result": "PASS",
            "checks": [
                "real PowerContext memory write/read",
                "bonus action boundary and automatic loop reset",
                "player isolation",
                "HTTP retry idempotency",
                "conflicting request rejected",
                "new conversation and process restart",
                "true ending",
                "bad ending",
                "unknown action rejected",
            ],
            "dify_runtime_verified": False,
            "llm_verified": False,
            "records": records,
        }
        (root / "evidence" / "acceptance.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2)
        )
        print(
            json.dumps(
                {k: v for k, v in report.items() if k != "records"},
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        proc.terminate()
        proc.wait()
