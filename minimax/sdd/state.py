"""Task content lives in PowerContext; local JSON contains only exact addresses."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft

from .common import audit, write_json


async def operate(directory, task_id, value=None):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    pointer_path = directory / "state-address.json"
    config = BuiltinConfig(
        database=SQLiteConfig(
            url=f"sqlite+aiosqlite:///{directory / 'powercontext.db'}"
        )
    )
    async with open_builtin_runtime(
        config, scheduler_path=directory / "scheduler.db"
    ) as runtime:
        scope = await runtime.scopes.create(
            ScopeDraft(
                title="SDD " + task_id,
                summary="Durable development task progress and verification evidence",
                idempotency_key="minimax-sdd:" + task_id,
            )
        )
        memory = runtime.memory.for_scope(scope.scope_id)
        pointers = json.loads(pointer_path.read_text()) if pointer_path.exists() else {}
        if value is not None:
            if not isinstance(value.get("completed"), list) or not isinstance(
                value.get("todo"), list
            ):
                raise ValueError("State requires completed and todo arrays")
            saved = await memory.remember(
                RememberMemoryRequest(
                    entries=(
                        MemoryEntryInput(
                            kind="outcome",
                            text=json.dumps(value, ensure_ascii=False, sort_keys=True),
                        ),
                    )
                )
            )
            entry = saved.entry
            if entry is None:
                page = await memory.list()
                entry = next(
                    (
                        item
                        for item in page.entries
                        if item.entry.text
                        == json.dumps(value, ensure_ascii=False, sort_keys=True)
                    ),
                    None,
                )
            if entry is None:
                raise RuntimeError("PowerContext did not return a readable entry")
            citation = entry.citation
            pointers[task_id] = {
                "scope_id": scope.scope_id,
                "citation": citation.model_dump(mode="json"),
            }
            write_json(pointer_path, pointers)
            audit(
                directory,
                "powercontext.save",
                task_id=task_id,
                address=pointers[task_id],
                value=value,
            )
        if task_id not in pointers:
            return {"value": None, "pid": os.getpid(), "address": None}
        address = pointers[task_id]
        if address["scope_id"] != scope.scope_id:
            raise ValueError("Task scope address mismatch")
        record = await memory.get(
            GetMemoryEntryRequest(
                citation=MemoryCitation.model_validate(address["citation"])
            )
        )
        restored = json.loads(record.entry.text)
        audit(
            directory,
            "powercontext.read",
            task_id=task_id,
            address=address,
            value=restored,
        )
        return {"value": restored, "pid": os.getpid(), "address": address}


def state(directory, task_id, value=None):
    return asyncio.run(operate(directory, task_id, value))
