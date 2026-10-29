"""Prepare the real Dify 1.13.0 services required by this Chatflow.

Run with Python + PyYAML. No fake model, sandbox or workflow services are used.
"""

from pathlib import Path
from urllib.request import urlopen
import copy
import hashlib
import json
import secrets
import yaml

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".runtime" / "dify-stack"
TARGET.mkdir(parents=True, exist_ok=True)
URL = "https://raw.githubusercontent.com/langgenius/dify/1.13.0/docker/docker-compose.yaml"
source = TARGET / "upstream-compose.yaml"
if not source.exists():
    bundled = ROOT / "deploy" / "upstream-compose.yaml"
    source.write_bytes(
        bundled.read_bytes() if bundled.exists() else urlopen(URL, timeout=60).read()
    )
upstream = yaml.safe_load(source.read_text())
names = [
    "init_permissions",
    "db_postgres",
    "redis",
    "api",
    "worker",
    "sandbox",
    "plugin_daemon",
    "web",
]
services = {name: copy.deepcopy(upstream["services"][name]) for name in names}
for name, service in services.items():
    service.pop("profiles", None)
    service.pop("networks", None)
    if "depends_on" in service:
        service["depends_on"] = {
            k: v for k, v in service["depends_on"].items() if k in services
        }
    if name in ["api", "worker"]:
        service["environment"].update(SSRF_PROXY_HTTP_URL="", SSRF_PROXY_HTTPS_URL="")
    if name == "sandbox":
        service["environment"].update(HTTP_PROXY="", HTTPS_PROXY="")
        # Preserve the configuration shipped in the pinned sandbox image.
        # An empty host directory mounted at /conf would hide config.yaml.
        service["volumes"] = [
            v for v in service.get("volumes", []) if not v.endswith(":/conf")
        ]
    if name == "api":
        service["ports"] = ["127.0.0.1:18770:5001"]
    if name == "web":
        service["ports"] = ["127.0.0.1:18771:3000"]
    if name == "plugin_daemon":
        service["image"] = (
            "${PLUGIN_DAEMON_IMAGE:-langgenius/dify-plugin-daemon:0.5.3-local}"
        )
        service.pop("ports", None)
stack = {"name": "dify-time-loop", "services": services}
(TARGET / "compose.yml").write_text(yaml.safe_dump(stack, sort_keys=False))
env = TARGET / ".env"
if not env.exists():
    env.write_text(
        "\n".join(
            [
                "SECRET_KEY=" + secrets.token_urlsafe(48),
                "DB_PASSWORD=" + secrets.token_hex(24),
                "REDIS_PASSWORD=" + secrets.token_hex(24),
                "CELERY_BROKER_URL=redis://:${REDIS_PASSWORD}@redis:6379/1",
                "PLUGIN_DAEMON_KEY=" + secrets.token_hex(32),
                "PLUGIN_DIFY_INNER_API_KEY=" + secrets.token_hex(32),
                "CONSOLE_API_URL=http://localhost:18770",
                "CONSOLE_WEB_URL=http://localhost:18771",
                "SERVICE_API_URL=http://localhost:18770",
                "APP_API_URL=http://localhost:18770",
                "APP_WEB_URL=http://localhost:18771",
                "SANDBOX_ENABLE_NETWORK=true",
                "SERVER_WORKER_AMOUNT=1",
                "CELERY_WORKER_AMOUNT=1",
                "PLUGIN_PYTHON_ENV_INIT_TIMEOUT=600",
                "PYTHON_ENV_INIT_TIMEOUT=600",
                "PIP_MIRROR_URL=https://pypi.tuna.tsinghua.edu.cn/simple",
                "CHECK_UPDATE_URL=",
                "",
            ]
        )
    )
    env.chmod(0o600)
(TARGET / "source.json").write_text(
    json.dumps(
        {"url": URL, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
        indent=2,
    )
)
print(TARGET)
