"""时间循环便利店：PowerContext 持久记忆 + 确定性游戏裁判。"""

import hashlib
import json
import os
import re
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
DB = Path(os.environ.get("GAME_DB", ROOT / ".runtime/game.sqlite3"))
PC = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:18765").rstrip("/")
LOCK = threading.Lock()
CLUES = {
    "看收据": ("receipt", "收据背面写着：断电后，把热牛奶递给店员。"),
    "听广播": ("radio", "广播反复说：不要开门！先拉下电闸，门外的雨才会停。"),
}
ACTIONS = ["看收据", "听广播", "买牛奶", "拉电闸", "递牛奶", "开门"]


def pc_post(path, payload):
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("POWERCONTEXT_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(
        PC + path, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    with urlopen(req, timeout=20) as res:
        return json.load(res)


def recall(scope):
    return pc_post(
        "/v1/context/prepare",
        {"scope_id": scope, "query": "loopclue", "max_bytes": 8000},
    )


def turn(player, action, request_id):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", player):
        raise ValueError("玩家通行证需为 8–80 位字母、数字、下划线或短横线。")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", request_id):
        raise ValueError("request_id 格式错误。")
    action = action.strip()
    if action not in ACTIONS + ["开始", "状态", "重来"]:
        raise ValueError("未知行动。可用：开始、状态、重来、" + "、".join(ACTIONS))
    DB.parent.mkdir(parents=True, exist_ok=True)
    with LOCK, sqlite3.connect(DB) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS players (id TEXT PRIMARY KEY, state TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS replies (player TEXT, id TEXT, action TEXT, body TEXT, PRIMARY KEY(player,id))"
        )
        cached = db.execute(
            "SELECT action,body FROM replies WHERE player=? AND id=?",
            (player, request_id),
        ).fetchone()
        if cached:
            if cached[0] != action:
                raise ValueError("同一 request_id 不可用于不同操作。")
            return json.loads(cached[1])
        row = db.execute("SELECT state FROM players WHERE id=?", (player,)).fetchone()
        if row:
            s = json.loads(row[0])
        else:
            scope = pc_post(
                "/v1/scopes",
                {
                    "title": "便利店玩家 "
                    + hashlib.sha256(player.encode()).hexdigest()[:12],
                    "summary": "Time loop game discoveries; explicit player discoveries only.",
                    "idempotency_key": "dify-loop-"
                    + hashlib.sha256(player.encode()).hexdigest(),
                },
            )["scope_id"]
            s = dict(
                scope=scope,
                loop=1,
                steps=0,
                milk=False,
                power=True,
                trusted=False,
                won=False,
            )
        before = recall(s["scope"])
        memory = before.get("content") or ""
        event = "23:57。雨把街道折成一张收据。店员说：“欢迎回来，第一次来的客人。”"
        if action == "重来":
            s.update(
                loop=s["loop"] + 1,
                steps=0,
                milk=False,
                power=True,
                trusted=False,
                won=False,
            )
            event = "货架恢复原状。你仍记得上一轮发现的秘密。"
        elif action == "状态":
            event = "你翻开跨轮笔记。查看记忆不会消耗行动。"
        elif s["won"] and action != "开始":
            event = "你已经走出便利店。输入“重来”可重玩，笔记仍保留。"
        elif action in ACTIONS:
            if action in CLUES:
                code, event = CLUES[action]
                marker = "loopclue_" + code
                if marker not in memory:
                    pc_post(
                        "/v1/memory/remember",
                        {
                            "scope_id": s["scope"],
                            "kind": "fact",
                            "text": "loopclue " + marker + " " + event,
                            "reason": "玩家执行观察动作后发现的游戏线索；保留到后续循环。",
                        },
                    )
                    memory = recall(s["scope"]).get("content") or ""
                    if "loopclue_receipt" in memory and "loopclue_radio" in memory:
                        event += "\n两条记忆拼合，钟表退后一分钟：每轮现在有四次行动。"
            elif action == "买牛奶":
                s["milk"] = True
                event = "你拿到一瓶热牛奶。瓶底标价：一个昨天。"
            elif action == "拉电闸":
                if "loopclue_radio" in memory:
                    s["power"] = False
                    event = "你按广播留下的线索拉下电闸。雨声停了。"
                else:
                    event = "电闸贴着陌生符号。先听听广播，也许能找到操作线索。"
            elif action == "递牛奶":
                if s["milk"] and not s["power"] and "loopclue_receipt" in memory:
                    s.update(milk=False, trusted=True)
                    event = "店员接过热牛奶，眼睛恢复人类的颜色：“你终于记住了。”"
                else:
                    event = "店员摇头。你需要牛奶、正确的时机，以及收据上的线索。"
            elif action == "开门":
                if s["trusted"]:
                    s["won"] = True
                    event = "【真结局：明天照常营业】店员替你开门。第一缕晨光照进来，你走出了循环。"
                else:
                    event = "【坏结局：雨中顾客】门外站着另一个你。钟表开始倒转。"
                    s["steps"] = 3
            s["steps"] += 1
            # 解谜需要四步；获得两条记忆后可争取店员额外一分钟。
            budget = (
                4 if "loopclue_receipt" in memory and "loopclue_radio" in memory else 3
            )
            if s["steps"] >= budget and not s["won"]:
                s.update(
                    loop=s["loop"] + 1, steps=0, milk=False, power=True, trusted=False
                )
                event += (
                    "\n午夜归零，物品消失；发现的秘密保存在 PowerContext，进入下一轮。"
                )
        after = recall(s["scope"])
        content = after.get("content") or ""
        notes = [text for key, text in CLUES.values() if "loopclue_" + key in content]
        budget = 4 if len(notes) == 2 else 3
        result = {
            "event": event,
            "state": {k: v for k, v in s.items() if k != "scope"},
            "remaining": max(0, budget - s["steps"]),
            "notebook": notes,
            "powercontext": {
                "scope_id": s["scope"],
                "status": after.get("status"),
                "content": content,
            },
            "actions": ACTIONS,
            "won": s["won"],
        }
        result["display"] = (
            event
            + "\n\n第 "
            + str(s["loop"])
            + " 轮 · 剩余行动 "
            + str(result["remaining"])
            + "\n跨轮笔记："
            + ("；".join(notes) or "暂无")
            + "\n\n可选："
            + " / ".join(ACTIONS)
            + " / 状态 / 重来"
        )
        body = json.dumps(result, ensure_ascii=False)
        db.execute(
            "INSERT OR REPLACE INTO players VALUES (?,?)", (player, json.dumps(s))
        )
        db.execute(
            "INSERT INTO replies VALUES (?,?,?,?)", (player, request_id, action, body)
        )
        return result


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"status": "ok"})
        else:
            self.reply(404, {"error": "not found"})

    def reply(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/turn":
            return self.reply(404, {"error": "not found"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8192:
                return self.reply(413, {"error": "请求体应为 1–8192 bytes"})
            data = json.loads(self.rfile.read(size))
            result = turn(data["player"], data["action"], data["request_id"])
            self.reply(200, result)
        except (ValueError, KeyError) as exc:
            self.reply(400, {"error": str(exc)})
        except Exception:
            self.reply(
                503,
                {
                    "error": "记忆服务暂不可用，未确认本次行动。请使用相同 request_id 重试。"
                },
            )


if __name__ == "__main__":
    HTTPServer(
        (
            os.environ.get("GAME_HOST", "127.0.0.1"),
            int(os.environ.get("GAME_PORT", "18766")),
        ),
        Handler,
    ).serve_forever()
