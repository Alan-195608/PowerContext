"""Install the bundled official plugin and configure a real model via Console API.

MODEL_API_KEY is required. No credential is written to this repository.
"""

import json
import os
from pathlib import Path
import time
from console import Console, ROOT

PROVIDER = "langgenius/openai_api_compatible/openai_api_compatible"
IDENTIFIER = "langgenius/openai_api_compatible:0.0.73@4cf123ffaa4556f079bed6c47f3a462cc825504b859b183239e74eb19136a4b5"


def install(console):
    package = ROOT / "plugins/openai_api_compatible-0.0.73.difypkg"
    with package.open("rb") as source:
        uploaded = console.call(
            "POST",
            "/workspaces/current/plugin/upload/pkg",
            files={"pkg": (package.name, source, "application/octet-stream")},
        )
    identifier = uploaded.get("unique_identifier") or IDENTIFIER
    installed = console.call(
        "POST",
        "/workspaces/current/plugin/install/pkg",
        json={"plugin_unique_identifiers": [identifier]},
    )
    print("Plugin package accepted:", identifier, flush=True)
    task_id = installed.get("task_id")
    if task_id:
        last_status = None
        for _ in range(240):
            task = console.call("GET", "/workspaces/current/plugin/tasks/" + task_id)[
                "task"
            ]
            if task.get("status") != last_status:
                print("Plugin installation status:", task.get("status"), flush=True)
                last_status = task.get("status")
            if task.get("status") in ["success", "succeeded"]:
                installed["final_task"] = task
                break
            if task.get("status") in ["failed", "error"]:
                raise RuntimeError(json.dumps(task, ensure_ascii=False))
            time.sleep(3)
        else:
            raise RuntimeError("Plugin installation did not finish within 12 minutes")
    return uploaded, installed


def configure(console):
    key = os.environ["MODEL_API_KEY"]
    model = os.environ.get("MODEL_NAME", "deepseek-flash")
    endpoint = os.environ.get("MODEL_BASE_URL", "https://api.deepseek.com/v1")
    credentials = {
        "api_key": key,
        "endpoint_url": endpoint,
        "mode": "chat",
        "context_size": "32768",
        "max_tokens_to_sample": "4096",
        "vision_support": "no_support",
        "function_calling_type": "no_call",
        "agent_thought_support": "not_supported",
        "compatibility_mode": "extended",
        "stream_function_calling": "not_supported",
    }
    path = "/workspaces/current/model-providers/" + PROVIDER + "/models/credentials"
    current = console.call("GET", path, params={"model": model, "model_type": "llm"})
    payload = {
        "model": model,
        "model_type": "llm",
        "name": "Real model validation",
        "credentials": credentials,
    }
    method = "POST"
    if current.get("current_credential_id"):
        method = "PUT"
        payload["credential_id"] = current["current_credential_id"]
    result = console.call(
        method,
        path,
        json=payload,
    )
    print("Real model configured:", model, flush=True)
    return {
        "provider": PROVIDER,
        "model": model,
        "endpoint": endpoint,
        "result": result,
    }


if __name__ == "__main__":
    c = Console().login()
    uploaded, installed = install(c)
    result = configure(c)
    target = ROOT / "evidence/dify"
    target.mkdir(parents=True, exist_ok=True)
    (target / "model-setup.json").write_text(
        json.dumps(
            {"plugin": IDENTIFIER, "installation": installed, "model": result},
            ensure_ascii=False,
            indent=2,
        )
    )
