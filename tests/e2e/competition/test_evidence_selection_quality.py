"""Real Memory regressions for late evidence coverage and duplicate-free packing.

SciFact claims are CC BY 4.0; S2ORC abstracts are ODC-By 1.0.
The small fixture records source attribution and original document IDs.
"""

from __future__ import annotations

import json
from pathlib import Path

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

# A SciFact abstract whose supporting sentence sits at the very end of the
# document. The early sentences repeat query words without stating the claim.
_LATE_EVIDENCE_DOCUMENTS = tuple(
    document["text"]
    for document in json.loads(
        (Path(__file__).parent / "fixtures/scifact_evidence_regression.json").read_text(encoding="utf-8")
    )["documents"]
)

_LATE_EVIDENCE_QUERY = (
    "Autologous transplantation of mesenchymal stem cells causes a higher rate of opportunistic infections "
    "than induction therapy with anti-interleukin-2 receptor antibodies."
)

_EVIDENCE_MARKER = "combined analysis of MSC-treated groups revealed significantly decreased risk"

# An entry that restates the query topic in its opening and repeats the same
# statement as its closing finding. Both sentences match the same query terms,
# so only their depth in the entry separates them.
_TOPIC_SENTENCE = "The cobalt sensor records reactor pressure."
_FINDING_SENTENCE = "The cobalt sensor records reactor pressure at 37 degrees."
_TOPIC_ENTRY = (
    "Logbook entry for the plant. "
    + _TOPIC_SENTENCE
    + " "
    + "Administrative notes were filed for the shift log. " * 24
    + _FINDING_SENTENCE
)


async def _select(runtime, scope_id, documents, query, max_bytes=1400):
    memory = runtime.memory.for_scope(scope_id)
    await memory.remember(
        RememberMemoryRequest(entries=tuple(MemoryEntryInput(kind="document", text=text) for text in documents))
    )
    page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=16))
    result = PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query=query, max_bytes=max_bytes, evidence_selection=True),
        current_scope_id=scope_id,
        memory_candidates=(PreparedMemoryCandidates(scope_id=scope_id, memory_ref=page.memory_ref, hits=page.hits),),
    )
    originals = {hit.entry_id: hit.text for hit in page.hits}
    return result, originals


@pytest.mark.asyncio
async def test_late_evidence_sentence_is_not_displaced_by_an_earlier_title_match():
    """The supporting sentence near the end of a document must survive selection.

    The shipped selector divided every sentence score by its token count and
    then divided the contiguous-window score by the window length again, so
    length was charged twice. A short earlier sentence that repeated two query
    words then outranked the complete evidence sentence and the answer was
    lost even though it fitted the budget.
    """
    async with open_builtin_runtime(BuiltinConfig()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(title="Late evidence", summary="Evidence at the end", idempotency_key="late-evidence")
        )
        result, originals = await _select(
            runtime,
            scope.scope_id,
            _LATE_EVIDENCE_DOCUMENTS,
            _LATE_EVIDENCE_QUERY,
        )
        assert result.fragments
        assert any(_EVIDENCE_MARKER in fragment.text for fragment in result.fragments), [
            fragment.text[:160] for fragment in result.fragments
        ]
        assert all(
            fragment.text == originals[fragment.address.entry_id][fragment.start : fragment.end]
            for fragment in result.fragments
        )
        assert result.context.content is not None
        assert result.context.content_bytes == len(result.context.content.encode()) <= 1400


@pytest.mark.asyncio
async def test_one_covered_range_is_delivered_once():
    """Overlapping fragments of one entry must not be delivered twice.

    The shipped selector expanded a selected fragment across a neighbouring
    sentence without checking the other selected fragments, so the same
    characters were rendered twice and paid for twice in the byte budget.
    """
    async with open_builtin_runtime(BuiltinConfig()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(title="No duplicates", summary="One range once", idempotency_key="no-duplicates")
        )
        text = "The cobalt sensor was calibrated at 37 degrees. The amber valve opens at 19 degrees."
        result, originals = await _select(
            runtime,
            scope.scope_id,
            [text],
            "cobalt sensor calibrated amber valve opens",
        )
        assert result.fragments
        ranges = [(fragment.address.entry_id, fragment.start, fragment.end) for fragment in result.fragments]
        assert len(ranges) == len(set(ranges)), ranges
        for index, (entry_id, start, end) in enumerate(ranges):
            for other_entry, other_start, other_end in ranges[index + 1 :]:
                if other_entry == entry_id:
                    assert not (start < other_end and other_start < end), ranges
        assert all(
            fragment.text == originals[fragment.address.entry_id][fragment.start : fragment.end]
            for fragment in result.fragments
        )
        assert result.context.content is not None
        assert result.context.content_bytes == len(result.context.content.encode()) <= 1400


@pytest.mark.asyncio
async def test_equal_coverage_prefers_later_finding_over_the_opening_restatement():
    """A budget that admits one region must not spend it on the entry's opening.

    The shipped selector ranked two ranges that matched the same query terms
    identically and broke the tie towards the earlier one, so a budget too small
    for both returned the topic restatement at the top of the entry and dropped
    the closing finding entirely. Depth inside the entry now counts as evidence
    of value, which is the middle-and-later-body loss the challenge names.
    """
    async with open_builtin_runtime(BuiltinConfig()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(
                title="Depth tie",
                summary="Later finding wins an equal-coverage tie",
                idempotency_key="depth-tie",
            )
        )
        result, originals = await _select(
            runtime,
            scope.scope_id,
            [_TOPIC_ENTRY],
            "cobalt sensor records reactor pressure",
            max_bytes=1000,
        )
        assert result.fragments
        assert any(_FINDING_SENTENCE in fragment.text for fragment in result.fragments), [
            (fragment.start, fragment.end) for fragment in result.fragments
        ]
        assert not any(_TOPIC_SENTENCE in fragment.text for fragment in result.fragments)
        assert all(
            fragment.text == originals[fragment.address.entry_id][fragment.start : fragment.end]
            for fragment in result.fragments
        )
        assert result.context.content is not None
        assert result.context.content_bytes == len(result.context.content.encode()) <= 1000
