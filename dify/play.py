"""Local terminal entry point; does not replace Dify acceptance."""

import json
import os
import secrets
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

player = os.environ.get("PLAYER_TICKET") or secrets.token_hex(16)
print("23:57 时间循环便利店\n通行证：" + player + "\n输入 开始；退出输入 quit。")
while True:
    try:
        action = input("行动 > ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if action == "quit":
        break
    req = Request(
        os.environ.get("GAME_URL", "http://127.0.0.1:18766") + "/turn",
        data=json.dumps(
            {"player": player, "action": action, "request_id": uuid.uuid4().hex}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=30) as response:
            print(json.load(response)["display"])
    except HTTPError as error:
        print(error.read().decode())
    except OSError as error:
        print("服务无法连接：" + str(error))
