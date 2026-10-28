"""Lossless visible Pi v3 branch history and durable incremental capture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from powercontext.sources import AdapterSourceDefinition, TextEvidence
from powercontext.sources.connectors import ConnectorRunCompletion, ConnectorRunSession, ConnectorRunStatus
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


class PiSessionInput(BaseModel):
    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]


class PiEventSource(Source):
    event: PiEventInput


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _archive(content: bytes, leaf_id: str | None):
    try:
        records = [json.loads(line) for line in content.decode("utf-8-sig").splitlines() if line.strip()]
    except (UnicodeError, ValueError) as exc:
        raise ValueError("invalid Pi JSONL") from exc  # noqa: TRY003
    if (
        not records
        or not isinstance(records[0], dict)
        or records[0].get("type") != "session"
        or type(records[0].get("version")) is not int
        or records[0]["version"] != 3
        or not isinstance(records[0].get("id"), str)
        or not records[0]["id"].strip()
    ):
        raise ValueError("Pi archive requires a version 3 session header")  # noqa: TRY003
    nodes: dict[str, dict[str, Any]] = {}
    for record in records[1:]:
        if not isinstance(record, dict):
            raise ValueError("Pi nodes must be objects")  # noqa: TRY003, TRY004
        identity = record.get("id")
        parent = record.get("parentId")
        if (
            not isinstance(identity, str)
            or not identity.strip()
            or identity in nodes
            or "parentId" not in record
            or (parent is not None and (not isinstance(parent, str) or parent not in nodes))
        ):
            raise ValueError("invalid Pi node identity or parent")  # noqa: TRY003
        nodes[identity] = record
    leaf = leaf_id if leaf_id is not None else (next(reversed(nodes)) if nodes else None)
    if leaf is not None and leaf not in nodes:
        raise ValueError("unknown Pi leaf")  # noqa: TRY003
    path = []
    while leaf is not None:
        path.append(nodes[leaf])
        leaf = nodes[leaf]["parentId"]
    return records[0]["id"], nodes, tuple(reversed(path))


def _text_blocks(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts = []
    for block in value:
        block = cast(Any, block)
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif block.get("type") == "toolCall":
            parts.append(
                f"[tool_call {block.get('name', '')} {block.get('id', '')}] " + _canonical(block.get("arguments", {}))
            )
    return "\n".join(parts)


def _visible(record: dict[str, Any]) -> tuple[str, str]:
    kind = record.get("type")
    if kind == "message":
        message = record.get("message", {})
        if not isinstance(message, dict):
            raise ValueError("Pi message must be an object")  # noqa: TRY003
        role = message.get("role", "")
        if not isinstance(role, str):
            raise ValueError("Pi role must be a string")  # noqa: TRY003
        body = _text_blocks(message.get("content"))
        if role == "toolResult" and body:
            body = f"[tool_result {message.get('toolName', '')} {message.get('toolCallId', '')}] {body}"
        elif role == "bashExecution":
            command, output = message.get("command", ""), message.get("output", "")
            body = f"$ {command}\n{output}" if command or output else ""
        return role, body
    if kind in ("compaction", "branch_summary"):
        summary = record.get("summary", "")
        return kind, summary if isinstance(summary, str) else ""
    if kind == "custom_message":
        return "custom", _text_blocks(record.get("content"))
    return "", ""


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    session_id, _, path = _archive(value.content, value.leaf_id)
    events = []
    for record in path:
        role, body = _visible(record)
        if body.strip():
            events.append(
                PiEventInput(
                    session_id=session_id,
                    event_id=record["id"],
                    parent_id=record["parentId"],
                    event_type=record["type"],
                    role=role,
                    content=f"{role}: {body}",
                    record=record,
                )
            )
    return tuple(events)


def _identity(event: PiEventInput) -> str:
    return "pi:" + hashlib.sha256(_canonical([event.session_id, event.event_id]).encode()).hexdigest()


class _PiAdapter:
    name = "pi-event"
    input_class = PiEventInput
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        return PiEventSource(name=_identity(value), materialization=SourceMaterialization.CAPTURED, event=value)

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return source.event


class _PiProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        event = source.event
        return TextEvidence(
            source_type="pi-event",
            source_id=source.name,
            content=event.content,
            metadata={
                key: getattr(event, key) for key in ("session_id", "event_id", "parent_id", "event_type", "role")
            },
        )


PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(_PiAdapter(), projections=(_PiProjection(),))


class PiSessionConnector:
    name = "pi-session-history"
    version = "1"
    source_definitions = frozenset({"pi-event"})

    def __init__(self, path: str | Path, leaf_id: str | None = None):
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        content = self.path.read_bytes()
        session_id, nodes, _ = _archive(content, self.leaf_id)
        events = parse_pi_session(PiSessionInput(content=content, leaf_id=self.leaf_id))
        checkpoint = session.checkpoint or {}
        if not isinstance(checkpoint, dict):
            raise ValueError("invalid Pi checkpoint")  # noqa: TRY003, TRY004
        imported = dict(checkpoint.get("imported", {}))
        # Validate even previously captured events outside the selected branch.
        for saved in imported.values():
            if saved["session_id"] == session_id:
                record = nodes.get(saved["event_id"])
                if record is None or hashlib.sha256(_canonical(record).encode()).hexdigest() != saved["sha256"]:
                    raise ValueError("previously captured Pi history changed")  # noqa: TRY003
        for event in events:
            identity = _identity(event)
            if identity in imported:
                continue
            await session.submit(identity, "pi-event", event)
            imported[identity] = {
                "session_id": session_id,
                "event_id": event.event_id,
                "sha256": hashlib.sha256(_canonical(event.record).encode()).hexdigest(),
            }
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint={"imported": imported})


__all__ = ["PI_EVENT_SOURCE_DEFINITION", "PiEventInput", "PiSessionConnector", "PiSessionInput", "parse_pi_session"]
