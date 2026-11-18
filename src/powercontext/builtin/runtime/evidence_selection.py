# Copyright (c) 2026 OceanBase.
# SPDX-License-Identifier: Apache-2.0
"""Select literal sentence spans within the complete context byte budget."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

from powercontext.artifacts import ArtifactAddress
from powercontext.builtin.runtime.models import PrepareContextRequest, PreparedContext
from powercontext.builtin.runtime.prepared_context import (
    MemoryEntryAddress,
    PreparedContextBuild,
    PreparedContextInvariantError,
    PreparedContextOmissions,
    PreparedContextOrigin,
    PreparedMemoryCandidates,
)
from powercontext.builtin.runtime.prepared_context import PreparedEvidenceFragment as PreparedContextFragment
from powercontext.builtin.runtime.prepared_envelope import encode_envelope
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

_BEGIN_MARKER = "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1"
_END_MARKER = "END_POWERCONTEXT_PREPARED_CONTEXT_V1"


def _pack_sentences(  # noqa: C901 - reference sentence packing with exact byte checks
    request: PrepareContextRequest,
    *,
    current_scope_id: str | None,
    memory_candidates: Sequence[PreparedMemoryCandidates],
) -> tuple[
    str | None, tuple[PreparedContextOrigin, ...], PreparedContextOmissions, tuple[PreparedContextFragment, ...]
]:
    """Select literal query-relevant spans from Memory candidates within one byte budget."""

    query_terms = _query_terms(request.query)
    units: list[_SentenceCandidate] = []
    texts: dict[tuple[int, int], str] = {}
    for group_index, candidates in enumerate(memory_candidates):
        scope_id = candidates.scope_id or current_scope_id or ""
        seen: set[tuple[str, str]] = set()
        for entry_index, hit in enumerate(candidates.hits):
            if hit.memory_ref != candidates.memory_ref:
                raise PreparedContextInvariantError("memory-ref-mismatch")
            identity = (hit.entry_id, hit.entry_version_id)
            if identity in seen:
                continue
            seen.add(identity)
            if not hit.entry_id.strip() or not hit.entry_version_id.strip() or not hit.text.strip():
                continue
            key = (group_index, entry_index)
            texts[key] = hit.text
            address = MemoryEntryAddress(
                memory=ArtifactAddress(scope_id=scope_id, artifact=hit.memory_ref),
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            for unit_index, (start, end) in enumerate(_sentence_spans(hit.text)):
                units.append(
                    _SentenceCandidate(
                        group=group_index,
                        entry_index=entry_index,
                        unit_index=unit_index,
                        address=address,
                        start=start,
                        end=end,
                        matched=len(query_terms.intersection(_query_terms(hit.text[start:end]))),
                    )
                )
    if not units:
        return None, (), PreparedContextOmissions(), ()

    ordered = sorted(
        units,
        key=lambda unit: (-unit.matched, unit.end - unit.start, unit.group, unit.entry_index, unit.unit_index),
    )
    ranks = {(unit.group, unit.entry_index, unit.unit_index): rank for rank, unit in enumerate(ordered)}
    by_index = {(unit.group, unit.entry_index, unit.unit_index): unit for unit in units}
    selected: list[_SentenceCandidate] = []
    dropped = 0
    for unit in ordered:
        if not unit.matched:
            break
        if _evidence_fits((*selected, unit), texts, ranks, request.max_bytes):
            selected.append(unit)
            continue
        trimmed = _trim_evidence(unit, texts, selected, ranks, request.max_bytes)
        if trimmed is None:
            dropped += 1
        else:
            selected.append(trimmed)
    if selected:
        adjacent: list[_SentenceCandidate] = []
        for unit in selected:
            for offset in (-1, 1):
                neighbour = by_index.get((unit.group, unit.entry_index, unit.unit_index + offset))
                if neighbour is not None and neighbour not in selected and neighbour not in adjacent:
                    adjacent.append(neighbour)
        for unit in adjacent:
            if _evidence_fits((*selected, unit), texts, ranks, request.max_bytes):
                selected.append(unit)
            else:
                dropped += 1
    if not selected and units:
        fallback = min(units, key=lambda unit: (unit.group, unit.entry_index, unit.unit_index))
        selected = [trimmed] if (trimmed := _trim_evidence(fallback, texts, (), ranks, request.max_bytes)) else []
    if not selected:
        return None, (), PreparedContextOmissions(dropped_items=dropped), ()

    fragments = _evidence_fragments(selected, texts, ranks)
    content = _render_evidence(fragments)
    if len(content.encode("utf-8")) > request.max_bytes:
        raise PreparedContextInvariantError("output-budget")
    return (
        content,
        tuple(fragment.address for fragment in fragments),
        PreparedContextOmissions(dropped_items=dropped),
        fragments,
    )


@dataclass(frozen=True)
class _SentenceCandidate:
    """One literal sentence-level span of one Memory entry."""

    group: int
    entry_index: int
    unit_index: int
    address: MemoryEntryAddress
    start: int
    end: int
    matched: int


_TERM_PATTERN = re.compile(r"[^\W_]+")
_MIN_EVIDENCE_CHARS = 24
_MAX_EVIDENCE_SENTENCE_CHARS = 800


def _query_terms(text: str) -> set[str]:
    return {match.group().casefold() for match in _TERM_PATTERN.finditer(text)}


def _trim_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _split_span(text: str, start: int, end: int) -> list[tuple[int, int]]:
    if end - start <= _MAX_EVIDENCE_SENTENCE_CHARS:
        return [(start, end)]
    spans: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > _MAX_EVIDENCE_SENTENCE_CHARS:
        limit = cursor + _MAX_EVIDENCE_SENTENCE_CHARS
        split = limit
        while split > cursor and not text[split - 1].isspace():
            split -= 1
        if split <= cursor:
            split = limit
        spans.append((cursor, split))
        cursor = split
        while cursor < end and text[cursor].isspace():
            cursor += 1
    if cursor < end:
        spans.append((cursor, end))
    return spans


def _sentence_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Split literal text into sentence spans that keep their original character offsets."""

    spans: list[tuple[int, int]] = []
    length = len(text)
    start = 0
    index = 0
    while index < length:
        if text[index] in ".!?\n":
            end = index + 1
            while end < length and text[end] in "\"'”’)]}":  # noqa: RUF001 - literal punctuation
                end += 1
            if end < length and not text[end].isspace():
                index += 1
                continue
            span = _trim_span(text, start, end)
            if span is not None:
                spans.extend(_split_span(text, *span))
            while end < length and text[end].isspace():
                end += 1
            start = index = end
            continue
        index += 1
    span = _trim_span(text, start, length)
    if span is not None:
        spans.extend(_split_span(text, *span))
    return tuple(spans)


def _evidence_fragments(
    units: Sequence[_SentenceCandidate],
    texts: dict[tuple[int, int], str],
    ranks: dict[tuple[int, int, int], int],
) -> tuple[PreparedContextFragment, ...]:
    grouped: dict[tuple[int, int], list[_SentenceCandidate]] = {}
    for unit in units:
        grouped.setdefault((unit.group, unit.entry_index), []).append(unit)
    ranked: list[tuple[int, PreparedContextFragment]] = []
    for key, group_units in grouped.items():
        merged: list[tuple[int, int, int, _SentenceCandidate]] = []
        for unit in sorted(group_units, key=lambda unit: unit.start):
            rank = ranks[(unit.group, unit.entry_index, unit.unit_index)]
            if merged and unit.start <= merged[-1][1]:
                begin, finish, best_rank, first = merged[-1]
                merged[-1] = (begin, max(finish, unit.end), min(best_rank, rank), first)
            else:
                merged.append((unit.start, unit.end, rank, unit))
        for begin, finish, rank, unit in merged:
            ranked.append((
                rank,
                PreparedContextFragment(address=unit.address, start=begin, end=finish, text=texts[key][begin:finish]),
            ))
    ranked.sort(key=lambda pair: pair[0])
    return tuple(fragment for _, fragment in ranked)


def _render_evidence(fragments: Sequence[PreparedContextFragment]) -> str:
    items = [
        {
            "citation": {
                "scope_id": fragment.address.memory.scope_id,
                "memory_ref": fragment.address.memory.artifact.model_dump(mode="json"),
                "entry_id": fragment.address.entry_id,
                "entry_version_id": fragment.address.entry_version_id,
            },
            "content": fragment.text,
            "start": fragment.start,
            "end": fragment.end,
        }
        for fragment in fragments
    ]
    envelope = {"trust": "untrusted_history", "items": items}
    encoded = encode_envelope(envelope)
    return "\n\n".join((TRUST_POLICY, f"{_BEGIN_MARKER}\n{encoded}\n{_END_MARKER}"))


def _evidence_fits(
    units: Sequence[_SentenceCandidate],
    texts: dict[tuple[int, int], str],
    ranks: dict[tuple[int, int, int], int],
    max_bytes: int,
) -> bool:
    return len(_render_evidence(_evidence_fragments(units, texts, ranks)).encode("utf-8")) <= max_bytes


def _trim_evidence(
    unit: _SentenceCandidate,
    texts: dict[tuple[int, int], str],
    selected: Sequence[_SentenceCandidate],
    ranks: dict[tuple[int, int, int], int],
    max_bytes: int,
) -> _SentenceCandidate | None:
    """Shorten one span to the longest literal prefix that still fits the byte budget."""

    low = min(unit.end, unit.start + _MIN_EVIDENCE_CHARS)
    high = unit.end - 1
    best: _SentenceCandidate | None = None
    while low <= high:
        middle = (low + high) // 2
        candidate = replace(unit, end=middle)
        if _evidence_fits((*selected, candidate), texts, ranks, max_bytes):
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best


def select_evidence(request, groups, *, current_scope_id=None):
    content, origins, omissions, fragments = _pack_sentences(
        request, current_scope_id=current_scope_id, memory_candidates=groups
    )
    return PreparedContextBuild(
        PreparedContext(
            status="ready" if content else "empty", content=content, content_bytes=len((content or "").encode())
        ),
        origins,
        omissions,
        fragments=fragments,
    )
