"""Small client for the real Dify Console HTTP API (local validation only)."""

import base64
import json
import os
from pathlib import Path
import secrets
import httpx

ROOT = Path(__file__).resolve().parents[1]


class Console:
    def __init__(self):
        self.url = os.environ.get("DIFY_URL", "http://localhost:18770").rstrip("/")
        self.client = httpx.Client(base_url=self.url, timeout=180, trust_env=False)

    def call(self, method, path, **kwargs):
        response = self.client.request(method, "/console/api" + path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(
                f"{method} {path}: HTTP {response.status_code}: {response.text[:1500]}"
            )
        return response.json() if response.content else None

    def login(self):
        account_file = ROOT / ".runtime" / "console-account.json"
        if not account_file.exists():
            account_file.write_text(
                json.dumps(
                    {
                        "email": "dify-eval@example.com",
                        "name": "Dify Evaluator",
                        "password": secrets.token_urlsafe(18) + "A1",
                        "language": "zh-Hans",
                    }
                )
            )
            account_file.chmod(0o600)
        account = json.loads(account_file.read_text())
        state = self.call("GET", "/setup")
        if state["step"] == "not_started":
            self.call("POST", "/setup", json=account)
        self.call(
            "POST",
            "/login",
            json={
                "email": account["email"],
                "password": base64.b64encode(account["password"].encode()).decode(),
                "remember_me": True,
            },
        )
        csrf = self.client.cookies.get("csrf_token")
        if csrf:
            self.client.headers["X-CSRF-Token"] = csrf
        return self

    def import_app(self, path):
        result = self.call(
            "POST",
            "/apps/imports",
            json={"mode": "yaml-content", "yaml_content": Path(path).read_text()},
        )
        if result.get("status") == "pending":
            result = self.call("POST", "/apps/imports/" + result["id"] + "/confirm")
        if not result.get("app_id"):
            raise RuntimeError("No app ID: " + json.dumps(result, ensure_ascii=False))
        return result

    def run(self, app_id, query, player, conversation_id=None):
        payload = {"inputs": {"player": player}, "query": query, "files": []}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        events = []
        route = "/console/api/apps/" + app_id + "/advanced-chat/workflows/draft/run"
        with self.client.stream("POST", route, json=payload) as response:
            if response.status_code != 200:
                response.read()
                raise RuntimeError(
                    f"Run failed HTTP {response.status_code}: {response.text[:1200]}"
                )
            for line in response.iter_lines():
                if line.startswith("data:"):
                    value = line[5:].strip()
                    if value and value != "[DONE]":
                        events.append(json.loads(value))
        return events


if __name__ == "__main__":
    client = Console().login()
    print("Dify Console login succeeded")
