"""Additional interruption, scope isolation, and full-evidence regressions."""

import asyncio
import json

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput, MemoryService
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleEvent
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceDefinitionRegistry
from powercontext.sources.pi_session import PI_EVENT_SOURCE_DEFINITION, PiSessionInput, parse_pi_session


def test_large_tool_result_remains_complete_source_evidence():
    content = "line of original tool evidence\n" * 4000
    records = [
        {"type": "session", "version": 3, "id": "large-session"},
        {
            "type": "message",
            "id": "result",
            "parentId": None,
            "message": {
                "role": "toolResult",
                "toolName": "read",
                "toolCallId": "tool",
                "content": [{"type": "text", "text": content}],
            },
        },
    ]
    (event,) = parse_pi_session(PiSessionInput(content="\n".join(map(json.dumps, records)).encode()))
    assert event.content == "toolResult: [tool_result read tool] " + content
    assert event.record == records[1]

    async def check():
        registry = SourceDefinitionRegistry((PI_EVENT_SOURCE_DEFINITION,))
        assert await registry.read(await registry.resolve(event)) == event

    asyncio.run(check())


def test_interrupted_lifecycle_reconciles_after_restart_and_isolates_scopes(tmp_path, monkeypatch):
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'retry.db'}"))
    original = MemoryService.forget
    attempts = 0

    async def interrupted(self, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise RuntimeError("interrupted second native state write")  # noqa: TRY003
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(MemoryService, "forget", interrupted)

    async def check():
        assert config.database is not None
        scopes, references = [], []
        event = SourceLifecycleEvent(node_id="root", revision=1, sequence=1, available=False, reason="withdraw")
        async with open_builtin_runtime(config) as runtime:
            assert runtime.scopes is not None
            for key in ("left", "right"):
                scope = await runtime.scopes.create(ScopeDraft(title=key, summary="Isolation", idempotency_key=key))
                scopes.append(scope.scope_id)
                source = await runtime.sources.for_scope(scope.scope_id).capture(
                    CaptureSource(source_id="root", content="Original source", metadata={})
                )
                lifecycle = runtime.lifecycle.for_scope(scope.scope_id)
                await lifecycle.register_source("root", source.source_ref, revision=1)
                memory = runtime.memory.for_scope(scope.scope_id)
                scope_refs = []
                for index in range(2):
                    result = await memory.remember(
                        RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=f"fact {index}"),))
                    )
                    assert result.entry is not None
                    scope_refs.append(result.entry.citation)
                    await lifecycle.register_memory(
                        f"fact{index}", result.entry.citation, parents=("root",), policy="all"
                    )
                references.append(scope_refs)
            with pytest.raises(RuntimeError, match="interrupted"):
                await runtime.lifecycle.for_scope(scopes[0]).apply(event)
        async with open_builtin_runtime(config) as runtime:
            lifecycle = runtime.lifecycle.for_scope(scopes[0])
            assert await lifecycle.apply(event) == []
            before = (await runtime.memory.for_scope(scopes[0]).list()).memory_ref
            assert await lifecycle.apply(event) == []
            assert (await runtime.memory.for_scope(scopes[0]).list()).memory_ref == before
            assert not (await runtime.memory.for_scope(scopes[0]).list()).entries
            assert len((await runtime.memory.for_scope(scopes[1]).list()).entries) == 2
            for reference in references[0]:
                record = await runtime.memory.for_scope(scopes[0]).get(GetMemoryEntryRequest(citation=reference))
                assert record.entry.entry_version_id == reference.entry_version_id
            await lifecycle.apply(event.model_copy(update={"sequence": 2, "available": True}))
            assert len((await runtime.memory.for_scope(scopes[0]).list()).entries) == 2

    asyncio.run(check())
