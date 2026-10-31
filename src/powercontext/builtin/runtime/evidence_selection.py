"""Query-driven literal sentence selection measured against full wire overhead."""

from __future__ import annotations

import math
import re
import sqlite3
from bisect import bisect_left, bisect_right
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
from powercontext.builtin.runtime.prepared_envelope import encode_envelope
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
    folded = text.casefold().translate(
        str.maketrans({
            "α": "alpha",  # noqa: RUF001 - scientific Greek letter normalization
            "β": "beta",
            "γ": "gamma",  # noqa: RUF001 - scientific Greek letter normalization
            "δ": "delta",
            "κ": "kappa",
            "μ": "mu",
        })
    )
    compounds = re.findall(r"\b[a-z0-9]+(?:[-‐‑–][a-z0-9]+)+\b", folded)  # noqa: RUF001 - normalize hyphens
    compounds += re.findall(r"\b[a-z]{1,8}\s+[0-9]+[a-z]*\b", folded)
    extra = [re.sub(r"[^a-z0-9]", "", value) for value in compounds]
    words = [word for word in [*re.findall(r"\w+", folded), *extra] if word not in _STOP]
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
        + encode_envelope({"trust": "untrusted_history", "items": items})
        + "\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1"
    )


def _fit_query_fragment(fragment, original, query, budget):  # noqa: C901 - two monotone byte fits and literal scoring
    """Fit an oversized sentence around matching concepts, not its first matching word."""
    if len(_render([fragment]).encode()) <= budget:
        return fragment
    words = list(re.finditer(r"\w+", fragment.text))
    analyzed = {}
    occurrences = []
    frequencies = Counter()
    for word in words:
        value = word.group().casefold()
        if value not in analyzed:
            analyzed[value] = set(_tokens(value)) & query.keys()
        matches = analyzed[value]
        if matches:
            occurrences.append((fragment.start + word.start(), fragment.start + word.end(), matches))
            frequencies.update(matches)
    if not occurrences:
        return None
    weights = {term: query[term] * math.log1p(len(words) / count) for term, count in frequencies.items()}
    # Rare matching concepts seed the bounded search before repeated generic words.
    anchors = sorted(occurrences, key=lambda item: -sum(weights[t] for t in item[2]))[:128]
    starts = [fragment.start + word.start() for word in words]
    ends = [fragment.start + word.end() for word in words]
    attempts = set()
    fitting = []
    for left, right, _ in anchors:
        desired = max(fragment.start, left - 120)
        start = starts[bisect_left(starts, desired)]
        end = min(fragment.end, right + 120)
        for forward in (True, False):
            fixed = start if forward else end
            key = (forward, fixed)
            if key in attempts:
                continue
            attempts.add(key)
            low, high = (start + 1, fragment.end) if forward else (fragment.start, end - 1)
            best = None
            while low <= high:
                middle = (low + high) // 2
                a, b = (start, middle) if forward else (middle, end)
                candidate = replace(fragment, start=a, end=b, text=original[a:b])
                if len(_render([candidate]).encode()) <= budget:
                    best = candidate
                    if forward:
                        low = middle + 1
                    else:
                        high = middle - 1
                elif forward:
                    high = middle - 1
                else:
                    low = middle + 1
            if best is None:
                continue
            start_index = bisect_left(starts, best.start)
            if start_index == len(starts):
                continue
            a = starts[start_index]
            boundary = bisect_right(ends, best.end) - 1
            if boundary < 0 or a >= ends[boundary]:
                continue
            b = ends[boundary]
            candidate = replace(fragment, start=a, end=b, text=original[a:b])
            matched = set().union(*(terms for x, y, terms in occurrences if a <= x and y <= b))
            utility = sum(weights[t] for t in matched)
            # Equal concept coverage should keep the focused window: padding a
            # long sentence with boilerplate must not dilute its ranking later.
            fitting.append((utility, len(matched), a - b, -a, candidate))
    return max(fitting, key=lambda value: value[:4])[-1] if fitting else None


def _compound_aliases(text):
    """The synthetic alias term of every hyphenated compound in ``text``.

    ``_tokens`` adds one alias per hyphenated compound, so "AMP-activated"
    yields the words ``amp`` and ``activ`` *and* the alias ``ampactivated``.
    The alias is a real matchable term - a document that spells the compound
    the same way produces it too - but it repeats what the compound's own
    words already say, so an undiscounted alias counts the compound twice.
    """
    folded = text.casefold()
    aliases = set()
    for compound in re.findall(r"\b[a-z0-9]+(?:[-‐‑–][a-z0-9]+)+\b", folded):  # noqa: RUF001 - normalize hyphens
        aliases.update(_tokens(re.sub(r"[^a-z0-9]", "", compound)))
    return aliases


# A hyphenated compound's alias term repeats the compound's own words, so the
# compound would otherwise carry twice the weight of a single word. The alias
# keeps a reduced share of the weight: it still matches the documents that
# spell the compound, but it no longer outweighs the outcome a claim is about.
_COMPOUND_ALIAS_SHARE = 0.2


def select_evidence(request, groups):  # noqa: C901 - bounded literal selection and packing
    query = Counter(_tokens(request.query))
    identifiers = re.findall(r"\b(?:[A-Z]{2,}[0-9]*|[a-zA-Z]+[0-9]+[a-zA-Z0-9]*)\b", request.query)
    for term in _tokens(" ".join(identifiers)):
        query[term] = max(query[term], 3)
    for term in _compound_aliases(request.query):
        if term in query:
            query[term] *= _COMPOUND_ALIAS_SHARE
    candidates = []
    document_tokens = {}
    for group in groups:
        for hit in group.hits:
            address = MemoryEntryAddress(
                ArtifactAddress(scope_id=group.scope_id, artifact=hit.memory_ref), hit.entry_id, hit.entry_version_id
            )
            key = (address.memory.model_dump_json(), address.entry_id, address.entry_version_id)
            document_tokens[key] = Counter(_tokens(hit.text))
            for match in re.finditer(r"\S[\s\S]*?(?:[.!?](?=\s|$)|$)", hit.text):
                start, end = match.span()
                if start < end:
                    fragment = _fit_query_fragment(
                        PreparedEvidenceFragment(address, start, end, hit.text[start:end]),
                        hit.text,
                        query,
                        request.max_bytes,
                    )
                    if fragment is None:
                        continue
                    candidates.append((
                        fragment,
                        Counter(_tokens(fragment.text)),
                        hit.text,
                    ))
    frequency = Counter(token for _, tokens, _ in candidates for token in tokens)

    def identity(fragment):
        return (fragment.address.memory.model_dump_json(), fragment.address.entry_id, fragment.address.entry_version_id)

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
    for fragment, tokens, original in candidates:
        matches = set(query) & tokens.keys()
        score = sum(math.log(1 + len(candidates) / (1 + frequency[t])) * query[t] for t in matches)
        score *= 1 + len(matches) / max(1, len(query))
        score *= (document_scores[identity(fragment)] / maximum) ** 1.0
        # Length is accounted for once, when the contiguous windows are ranked
        # below. Dividing the sentence score as well would charge a long
        # sentence twice and let a short title match that repeats two query
        # words outrank the complete evidence sentence later in the document.
        lower = fragment.text.lower()
        if re.search(r"\b(results?|conclusions?|found|showed|demonstrat|indicat|suggest)", lower):
            score *= 1.5
        # Depth inside the entry is part of the same judgement: an opening
        # restates the topic the query already contains, while the findings that
        # answer the query arrive later, so among ranges with equal concept
        # coverage the later one is the evidence.
        score *= 0.5 + fragment.end / max(1, len(original))
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
            # Merging across a neighbour must not re-deliver bytes another
            # selected fragment already covers: the overlap would be paid for
            # twice while contributing no new evidence.
            if any(
                f.address == fragment.address and f.start < end and start < f.end
                for position, f in enumerate(selected)
                if position != index
            ):
                continue
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
    if not selected:
        return PreparedContextBuild(PreparedContext(status="empty", content=None, content_bytes=0), ())
    # Adjacent fragments of one entry can still touch or overlap after the
    # expansion above. Deliver each covered range once so the budget is not
    # spent on the same characters twice.
    merged = []
    for fragment in sorted(selected, key=lambda f: (identity(f), f.start)):
        previous = merged[-1] if merged else None
        if previous is not None and previous.address == fragment.address and fragment.start <= previous.end:
            end = max(previous.end, fragment.end)
            original = originals[identity(fragment)]
            merged[-1] = replace(previous, end=end, text=original[previous.start : end])
            continue
        merged.append(fragment)
    selected = merged
    content = _render(selected)
    return PreparedContextBuild(
        PreparedContext(status="ready", content=content, content_bytes=len(content.encode())),
        tuple(fragment.address for fragment in selected),
        fragments=tuple(selected),
    )
