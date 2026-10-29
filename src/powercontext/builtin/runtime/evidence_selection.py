"""Query-driven literal sentence selection measured against full wire overhead."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import replace

from powercontext.artifacts import ArtifactAddress
from powercontext.builtin.runtime.models import PreparedContext
from powercontext.builtin.runtime.prepared_context import (
    MemoryEntryAddress,
    PreparedContextBuild,
    PreparedEvidenceFragment,
)
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

_STOP = frozenset([
    "we",
    "our",
    "their",
    "has",
    "have",
    "had",
    "can",
    "could",
    "may",
    "might",
    "also",
    "than",
    "which",
    "but",
    "does",
    "did",
    "do",
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "at",
    "by",
    "from",
    "with",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "that",
    "this",
    "these",
    "those",
    "it",
    "its",
    "for",
])


def _tokens(text):
    words = [word for word in re.findall(r"\w+", text.casefold()) if word not in _STOP]
    if not words:
        return []
    with closing(sqlite3.connect(":memory:")) as database:
        database.execute("CREATE VIRTUAL TABLE words USING fts5(text, tokenize='porter unicode61')")
        database.execute("CREATE VIRTUAL TABLE vocabulary USING fts5vocab(words, instance)")
        database.execute("INSERT INTO words VALUES (?)", (" ".join(words),))
        return [row[0] for row in database.execute("SELECT term FROM vocabulary ORDER BY offset")]


def _render(fragments):
    items = [
        {
            "citation": {
                "scope_id": item.address.memory.scope_id,
                "memory_ref": item.address.memory.artifact.model_dump(mode="json"),
                "entry_id": item.address.entry_id,
                "entry_version_id": item.address.entry_version_id,
            },
            "content": item.text,
            "start": item.start,
            "end": item.end,
        }
        for item in fragments
    ]
    return (
        TRUST_POLICY
        + "\nBEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n"
        + json.dumps({"trust": "untrusted_history", "items": items}, ensure_ascii=False, separators=(",", ":"))
        + "\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1"
    )


def select_evidence(request, groups):  # noqa: C901 - bounded literal selection and packing
    query = Counter(_tokens(request.query))
    identifiers = re.findall(r"\b(?:[A-Z]{2,}[0-9]*|[a-zA-Z]+[0-9]+[a-zA-Z0-9]*)\b", request.query)
    for term in _tokens(" ".join(identifiers)):
        query[term] = max(query[term], 3)
    candidates = []
    for group in groups:
        for hit in group.hits:
            address = MemoryEntryAddress(
                ArtifactAddress(scope_id=group.scope_id, artifact=hit.memory_ref), hit.entry_id, hit.entry_version_id
            )
            for match in re.finditer(r"\S[\s\S]*?(?:[.!?](?=\s|$)|\n|$)", hit.text):
                start, end = match.span()
                if start < end:
                    candidates.append((
                        PreparedEvidenceFragment(address, start, end, hit.text[start:end]),
                        Counter(_tokens(hit.text[start:end])),
                        hit.text,
                    ))
    frequency = Counter(token for _, tokens, _ in candidates for token in tokens)

    def identity(fragment):
        return (fragment.address.memory.model_dump_json(), fragment.address.entry_id, fragment.address.entry_version_id)

    document_tokens = {}
    for fragment, tokens, _ in candidates:
        document_tokens.setdefault(identity(fragment), Counter()).update(tokens)
    document_frequency = Counter(t for tokens in document_tokens.values() for t in tokens)
    average_length = sum(sum(tokens.values()) for tokens in document_tokens.values()) / max(1, len(document_tokens))
    document_scores = {
        address: sum(
            math.log(1 + (len(document_tokens) - document_frequency[t] + 0.5) / (document_frequency[t] + 0.5))
            * tokens[t]
            * query[t]
            * 2.2
            / (tokens[t] + 1.2 * (0.25 + 0.75 * sum(tokens.values()) / average_length))
            for t in query
            if tokens[t]
        )
        for address, tokens in document_tokens.items()
    }
    for fragment, _, original in candidates:
        if fragment.start == 0:
            title = set(_tokens(original[:200]))
            document_scores[identity(fragment)] *= 1 + 4 * len(title & query.keys()) / max(1, len(query))
    maximum = max(document_scores.values(), default=1) or 1
    scores = []
    for fragment, tokens, _ in candidates:
        matches = set(query) & tokens.keys()
        score = sum(math.log(1 + len(candidates) / (1 + frequency[t])) * query[t] for t in matches)
        score *= 1 + len(matches) / max(1, len(query))
        score *= (document_scores[identity(fragment)] / maximum) ** 1.0
        score /= max(1, sum(tokens.values())) ** 0.35
        lower = fragment.text.lower()
        if re.search(r"\b(results?|conclusions?|found|showed|demonstrat|indicat|suggest)", lower):
            score *= 1.5
        if fragment.start == 0:
            score *= 0.3
        scores.append(score)
    # Evaluate contiguous windows: one citation can then pay for several useful
    # sentences, including connecting evidence with few literal query words.
    windows = []
    for left, (first, _, original) in enumerate(candidates):
        total = 0.0
        for right in range(left, len(candidates)):
            last = candidates[right][0]
            if last.address != first.address:
                break
            total += scores[right]
            fragment = replace(first, end=last.end, text=original[first.start : last.end])
            size = len(_render([fragment]).encode())
            if size > request.max_bytes:
                break
            if total:
                windows.append((total / max(1, len(fragment.text)) ** 0.35, left, fragment))
    windows.sort(key=lambda value: (-value[0], value[1]))
    selected = []
    for _, _, fragment in windows:
        if any(f.address == fragment.address and f.start < fragment.end and fragment.start < f.end for f in selected):
            continue
        if len(_render([*selected, fragment]).encode()) <= request.max_bytes:
            selected.append(fragment)
    # Spend the remaining bytes on adjacent literal context rather than leaving
    # room stranded below the cost of another citation.
    originals = {identity(fragment): original for fragment, _, original in candidates}
    for index, fragment in enumerate(selected):
        original = originals[identity(fragment)]
        neighbors = [
            other
            for other, _, _ in candidates
            if other.address == fragment.address and (other.start >= fragment.end or other.end <= fragment.start)
        ]
        neighbors.sort(
            key=lambda other: (
                min(abs(other.start - fragment.end), abs(fragment.start - other.end)),
                other.start < fragment.start,
            )
        )
        for other in neighbors:
            start, end = min(fragment.start, other.start), max(fragment.end, other.end)
            trial = list(selected)
            trial[index] = replace(fragment, start=start, end=end, text=original[start:end])
            if len(_render(trial).encode()) <= request.max_bytes:
                selected, fragment = trial, trial[index]
            else:
                low, high = 1, (fragment.start - start) + (end - fragment.end)
                while low <= high:
                    length = (low + high) // 2
                    partial_start = fragment.start - length if start < fragment.start else fragment.start
                    partial_end = fragment.end + length if end > fragment.end else fragment.end
                    trial[index] = replace(
                        fragment, start=partial_start, end=partial_end, text=original[partial_start:partial_end]
                    )
                    if len(_render(trial).encode()) <= request.max_bytes:
                        selected, low = list(trial), length + 1
                    else:
                        high = length - 1
                break
    if not selected and candidates and max(scores, default=0) > 0:
        best = max(range(len(scores)), key=scores.__getitem__)
        fragment, _, _ = candidates[best]
        # A sentence can itself exceed the wire budget. Center a literal window
        # on a matching word instead of dropping all evidence or clipping its tail.
        anchor = next(
            (m.start() for m in re.finditer(r"\w+", fragment.text) if set(_tokens(m.group())) & query.keys()), 0
        )
        start = fragment.start + max(0, anchor - 80)
        low, high = 1, fragment.end - start
        original = candidates[best][2]
        while low <= high:
            length = (low + high) // 2
            shortened = replace(fragment, start=start, end=start + length, text=original[start : start + length])
            if len(_render([shortened]).encode()) <= request.max_bytes:
                selected, low = [shortened], length + 1
            else:
                high = length - 1
    if not selected:
        return PreparedContextBuild(PreparedContext(status="empty", content=None, content_bytes=0), ())
    content = _render(selected)
    return PreparedContextBuild(
        PreparedContext(status="ready", content=content, content_bytes=len(content.encode())),
        tuple(fragment.address for fragment in selected),
        fragments=tuple(selected),
    )
