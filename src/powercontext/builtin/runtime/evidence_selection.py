"""Query-driven literal sentence selection measured against full wire overhead."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
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
    return [
        word[:-1] if len(word) > 4 and word.endswith("s") else word
        for word in re.findall(r"\w+", text.casefold())
        if word not in _STOP
    ]


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
    scored = []
    for index, (fragment, tokens, original) in enumerate(candidates):
        matches = set(query) & tokens.keys()
        score = sum(
            math.log(1 + len(candidates) / (1 + frequency[token])) * (1 + math.log1p(tokens[token]))
            for token in matches
        )
        score *= 1 + len(matches) / max(1, len(query))
        score /= 1 + 0.001 * len(fragment.text)
        if score > 0:
            scored.append((score, index, fragment, original))
    scored.sort(key=lambda value: (-value[0], value[1]))
    selected = []
    seen = set()
    for _, _, fragment, original in scored:
        key = (
            fragment.address.memory.model_dump_json(),
            fragment.address.entry_id,
            fragment.address.entry_version_id,
            fragment.start,
            fragment.end,
        )
        if key in seen:
            continue
        seen.add(key)
        # Merge neighboring intervals from one entry to avoid charging a second citation.
        trial = list(selected)
        merged = False
        for index, previous in enumerate(trial):
            if previous.address == fragment.address and not (
                fragment.start > previous.end + 2 or previous.start > fragment.end + 2
            ):
                start, end = min(previous.start, fragment.start), max(previous.end, fragment.end)
                trial[index] = replace(previous, start=start, end=end, text=original[start:end])
                merged = True
                break
        if not merged:
            trial.append(fragment)
        if len(_render(trial).encode()) <= request.max_bytes:
            selected = trial
        elif not selected:
            low, high = 1, len(fragment.text)
            fitting = None
            while low <= high:
                middle = (low + high) // 2
                shortened = replace(fragment, end=fragment.start + middle, text=fragment.text[:middle])
                if len(_render([shortened]).encode()) <= request.max_bytes:
                    fitting, low = shortened, middle + 1
                else:
                    high = middle - 1
            if fitting is not None:
                selected = [fitting]
    if not selected:
        return PreparedContextBuild(PreparedContext(status="empty", content=None, content_bytes=0), ())
    content = _render(selected)
    return PreparedContextBuild(
        PreparedContext(status="ready", content=content, content_bytes=len(content.encode())),
        tuple(fragment.address for fragment in selected),
        fragments=tuple(selected),
    )
