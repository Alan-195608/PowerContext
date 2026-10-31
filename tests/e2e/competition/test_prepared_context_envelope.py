"""Prepared-context envelope must stay parseable when source text holds Unicode separators.

A source document may legally contain U+2028 LINE SEPARATOR, U+2029 PARAGRAPH
SEPARATOR or U+0085 NEXT LINE. The prepared context embeds the literal text in
a JSON envelope, and Python's ``str.splitlines`` treats all three as line
breaks even though JSON allows them literally inside a string. A consumer that
reads the envelope line by line therefore received unparsable JSON, and the
whole request failed instead of returning its evidence.

The fix escapes exactly those characters in the serialised envelope. The
decoded content, the fragment offsets and the byte accounting are unchanged:
the decoded payload still carries the original characters, and the escaped
output is what the byte budget measures.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.runtime import (
    BuiltinConfig,
    PrepareContextRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.prepared_context import PreparedContextBuilder, PreparedMemoryCandidates
from powercontext.builtin.scope import ScopeDraft

# The three characters that break a line for Python but not for JSON.
_LINE_BREAKING_SEPARATORS = ("\u2028", "\u2029", "\u0085")

# Characters that JSON already escapes, kept as a control group.
_ALREADY_ESCAPED = ("\u000b", "\u000c", "\u001c", "\u001d", "\u001e")


def _envelope_items(content: str) -> list[dict[str, Any]]:
    """Parse the envelope the way a line-oriented consumer reads it."""
    assert content is not None
    lines = content.splitlines()
    marker = lines.index("BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1")
    payload = lines[marker + 1]
    return json.loads(payload)["items"]


async def _prepare(runtime, scope_id, text, query="target protocol", max_bytes=1800, selection=True):
    memory = runtime.memory.for_scope(scope_id)
    await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(kind="document", text=text),)))
    page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=16))
    return PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query=query, max_bytes=max_bytes, evidence_selection=selection),
        current_scope_id=scope_id,
        memory_candidates=(PreparedMemoryCandidates(scope_id=scope_id, memory_ref=page.memory_ref, hits=page.hits),),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("separator", _LINE_BREAKING_SEPARATORS)
async def test_evidence_envelope_survives_unicode_line_separators(separator):
    """A separator inside the source text must not make the envelope unparsable."""
    text = "Target protocol requires a literal evidence range." + separator + "The sensor remains active."
    async with open_builtin_runtime(BuiltinConfig()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(title="Separators", summary="Unicode separators", idempotency_key=f"sep-{ord(separator):x}")
        )
        result = await _prepare(runtime, scope.scope_id, text)
        assert result.context.content is not None
        items = _envelope_items(result.context.content)
        assert items, "the evidence envelope carried no item"
        # The decoded content is the original text, separators included.
        assert items[0]["content"] == text
        # The fragment is still an exact slice of the original entry.
        assert text[items[0]["start"] : items[0]["end"]] == items[0]["content"]
        assert result.context.content_bytes == len(result.context.content.encode()) <= 1800


@pytest.mark.asyncio
@pytest.mark.parametrize("separator", _ALREADY_ESCAPED)
async def test_evidence_envelope_survives_already_escaped_control_characters(separator):
    """Control characters JSON already escapes must keep working."""
    text = "Target protocol requires a literal evidence range." + separator + "The sensor remains active."
    async with open_builtin_runtime(BuiltinConfig()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(title="Controls", summary="Control characters", idempotency_key=f"ctl-{ord(separator):x}")
        )
        result = await _prepare(runtime, scope.scope_id, text)
        assert result.context.content is not None
        items = _envelope_items(result.context.content)
        assert items
        assert items[0]["content"] == text


@pytest.mark.asyncio
async def test_default_prepare_envelope_survives_unicode_line_separators():
    """The ordinary prepare path shares the envelope and must survive too."""
    text = "Target protocol requires a literal evidence range.\u2028The sensor remains active."
    async with open_builtin_runtime(BuiltinConfig()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(title="Default path", summary="Default prepare", idempotency_key="default-sep")
        )
        result = await _prepare(runtime, scope.scope_id, text, selection=False)
        assert result.context.content is not None
        items = _envelope_items(result.context.content)
        assert items
        assert items[0]["content"] == text
        assert result.context.content_bytes == len(result.context.content.encode()) <= 1800


@pytest.mark.asyncio
async def test_literal_backslash_u_sequence_stays_literal_after_round_trip():
    """Source text that already spells a backslash-u escape must not be decoded."""
    text = "Target protocol reports \\u2028 as a literal sequence."
    async with open_builtin_runtime(BuiltinConfig()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(title="Literal escape", summary="Literal backslash-u", idempotency_key="literal-escape")
        )
        result = await _prepare(runtime, scope.scope_id, text)
        assert result.context.content is not None
        items = _envelope_items(result.context.content)
        assert items
        assert items[0]["content"] == text
        assert "\\u2028" in items[0]["content"]
        assert "\u2028" not in items[0]["content"]
