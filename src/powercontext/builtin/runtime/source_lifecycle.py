"""Durable source dependency graphs and retryable native state propagation."""

from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.builtin.sources.journal import validate_scope_id
from powercontext.sources import SourceRef


class SourceLifecycleError(ValueError):
    """Invalid source lifecycle operation."""


class SourceLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    node_id: str
    reason: str
    revision: int = Field(gt=0)
    sequence: int = Field(gt=0)
    available: bool

    @field_validator("node_id", "reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("event text must be nonblank")  # noqa: TRY003
        return value


class LifecycleApplication:
    def __init__(self, runtime):
        self.runtime, self.locks = runtime, {}
        self.initialized = False
        self.schema_lock = asyncio.Lock()

    def for_scope(self, scope_id):
        return ScopedSourceLifecycle(self, validate_scope_id(scope_id))

    async def load(self, scope):
        database = self.runtime._records()._database
        async with self.schema_lock:
            if not self.initialized:
                async with database.transaction() as connection:
                    await connection.execute(
                        text(
                            "CREATE TABLE IF NOT EXISTS pc_source_lifecycle (scope_id VARCHAR(256) PRIMARY KEY, payload TEXT NOT NULL)"
                        )
                    )
                self.initialized = True
        async with database.connection() as connection:
            result = await connection.execute(
                text("SELECT payload FROM pc_source_lifecycle WHERE scope_id=:scope"), {"scope": scope}
            )
            row = result.first()
        return json.loads(row[0]) if row else {"nodes": {}, "events": {}}

    async def save(self, scope, state):
        async with self.runtime._records()._database.transaction() as connection:
            await connection.execute(text("DELETE FROM pc_source_lifecycle WHERE scope_id=:scope"), {"scope": scope})
            await connection.execute(
                text("INSERT INTO pc_source_lifecycle(scope_id,payload) VALUES (:scope,:payload)"),
                {"scope": scope, "payload": json.dumps(state, ensure_ascii=False)},
            )


class ScopedSourceLifecycle:
    def __init__(self, application, scope):
        self.application, self.runtime, self.scope = application, application.runtime, scope
        self.lock = application.locks.setdefault(scope, asyncio.Lock())

    async def register_source(self, node_id, source_ref, *, revision):
        if type(revision) is not int or revision < 1:
            raise SourceLifecycleError("revision must be positive integer")  # noqa: TRY003
        await self.runtime.records.for_scope(self.scope).get_source(source_ref.source_type, source_ref.source_id)
        await self._register(node_id, "source", source_ref, (), "all", revision)

    async def register_memory(self, node_id, citation, *, parents, policy):
        await self.runtime.memory.for_scope(self.scope).get(GetMemoryEntryRequest(citation=citation))
        await self._register(node_id, "memory", citation, parents, policy)

    async def register_topic(self, node_id, artifact_ref, *, parents, policy):
        if artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("invalid Topic Memory family")  # noqa: TRY003
        await self.runtime.records.for_scope(self.scope).get_artifact_revision(
            "topic-memory", artifact_ref.artifact_id, artifact_ref.revision
        )
        await self._register(node_id, "topic", artifact_ref, parents, policy)

    async def _register(self, identity, kind, reference, parents, policy, revision=None):
        if not isinstance(identity, str) or not identity.strip():
            raise SourceLifecycleError("node ID must be nonblank")  # noqa: TRY003
        parents = tuple(parents)
        if policy not in ("all", "any") or len(set(parents)) != len(parents):
            raise SourceLifecycleError("invalid dependency policy")  # noqa: TRY003
        async with self.lock:
            state = await self.application.load(self.scope)
            nodes = state["nodes"]
            binding = {
                "kind": kind,
                "reference": reference.model_dump(mode="json"),
                "parents": list(parents),
                "policy": policy,
                "revision": revision,
            }
            if identity in nodes:
                if nodes[identity] != binding:
                    raise SourceLifecycleError("conflicting node registration")  # noqa: TRY003
            else:
                if kind != "source" and (not parents or identity in parents or any(p not in nodes for p in parents)):
                    raise SourceLifecycleError("dependencies must be registered first")  # noqa: TRY003
                nodes[identity] = binding
                await self.application.save(self.scope, state)
            await self._reconcile(state)

    @staticmethod
    def _active(state):
        active = set()
        for identity, node in state["nodes"].items():
            if node["kind"] == "source":
                supported = state["events"].get(identity, {}).get("available", True)
            else:
                values = [p in active for p in node["parents"]]
                supported = all(values) if node["policy"] == "all" else any(values)
            if supported:
                active.add(identity)
        return active

    async def _reconcile(self, state):
        active = self._active(state)
        if not any(node["kind"] == "memory" for node in state["nodes"].values()):
            return
        async with self.runtime._context(self.scope) as context, self.runtime._locked(self.scope):
            memory = context.artifacts.memory
            head = await memory.head(context.artifacts.memory_artifact_id)
            entries = {entry.entry_id: entry for entry in await memory.entries(head)}
            states = {entry.entry_id: entry.state for entry in head.content.manifest.entries}
            for identity, node in state["nodes"].items():
                if node["kind"] != "memory":
                    continue
                reference = MemoryCitation.model_validate(node["reference"])
                entry = entries[reference.entry_id]
                if entry.entry_version_id != reference.entry_version_id:
                    raise SourceLifecycleError("registered Memory body changed")  # noqa: TRY003
                desired = "active" if identity in active else "inactive"
                if states[entry.entry_id] != desired:
                    method = memory.reactivate if desired == "active" else memory.forget
                    head = await method(head, entries=(entry,), reason="source lifecycle")
                    states[entry.entry_id] = desired

    async def apply(self, event):
        if not isinstance(event, SourceLifecycleEvent):
            event = SourceLifecycleEvent.model_validate(event)
        async with self.lock:
            state = await self.application.load(self.scope)
            node = state["nodes"].get(event.node_id)
            if node is None or node["kind"] != "source" or node["revision"] != event.revision:
                raise SourceLifecycleError("unknown Source or revision")  # noqa: TRY003
            old, encoded = state["events"].get(event.node_id), event.model_dump(mode="json")
            if old is not None and (
                event.sequence < old["sequence"] or (event.sequence == old["sequence"] and old != encoded)
            ):
                raise SourceLifecycleError("invalid event sequence or conflicting replay")  # noqa: TRY003
            # Persist intent before native writes; replays reconcile only missing transitions.
            state["events"][event.node_id] = encoded
            await self.application.save(self.scope, state)
            await self._reconcile(state)
            return sorted(self._active(state))

    async def resolve(self, node_id, *, purpose):
        async with self.lock:
            state = await self.application.load(self.scope)
            node = state["nodes"].get(node_id)
            if node is None or purpose not in ("generation", "audit"):
                raise SourceLifecycleError("unknown node or purpose")  # noqa: TRY003
            if purpose == "generation" and node_id not in self._active(state):
                raise SourceLifecycleError("evidence unavailable for generation")  # noqa: TRY003
            model = {"source": SourceRef, "memory": MemoryCitation, "topic": ArtifactRef}[node["kind"]]
            return model.model_validate(node["reference"])

    async def filter_topics(self, hits):
        if not hits:
            return ()
        state = await self.application.load(self.scope)
        active = self._active(state)
        unavailable = {
            node["reference"]["artifact_id"]
            for identity, node in state["nodes"].items()
            if node["kind"] == "topic" and identity not in active
        }
        return tuple(hit for hit in hits if hit.artifact_ref.artifact_id not in unavailable)


__all__ = ["LifecycleApplication", "SourceLifecycleError", "SourceLifecycleEvent"]
