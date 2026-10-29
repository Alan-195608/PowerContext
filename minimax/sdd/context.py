from __future__ import annotations

from .common import audit, digest
from .state import state
from .store import retrieve


def build(directory, task):
    documents = retrieve(directory, task["query"])
    restored = state(directory, task["id"])
    progress = restored["value"] or {
        "completed": [],
        "todo": [task["description"]],
        "verification": [],
    }
    by_path = {doc["path"]: doc for doc in documents}
    missing = sorted(set(task.get("required_sources", [])) - by_path.keys())
    if missing:
        raise ValueError(f"Required evidence was not retrieved: {missing}")
    result = {
        "task": task,
        "specifications": [d for d in documents if d["kind"] == "spec"],
        "code": [d for d in documents if d["kind"] == "code"],
        "tests": [d for d in documents if d["kind"] == "test"],
        "progress": progress,
        "powercontext_address": restored["address"],
        "next_action": progress["todo"][0]
        if progress["todo"]
        else "Review completed verification; no pending code work.",
        "snapshot_hash": digest("\n".join(d["path"] + d["sha256"] for d in documents)),
    }
    audit(
        directory,
        "context.build",
        snapshot_hash=result["snapshot_hash"],
        sources=sorted(by_path),
        state_reused=restored["value"] is not None,
    )
    return result
