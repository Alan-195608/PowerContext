from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def now():
    return datetime.now(timezone.utc).isoformat()


def audit(directory, event, **data):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "events.jsonl").open("a") as stream:
        stream.write(
            json.dumps(
                {"time": now(), "pid": os.getpid(), "event": event, **data},
                ensure_ascii=False,
            )
            + "\n"
        )
