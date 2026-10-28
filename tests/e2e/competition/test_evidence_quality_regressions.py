"""Literal context packing and financial page ranking regressions."""

import asyncio
from types import SimpleNamespace

from powercontext.artifacts import ArtifactRef, MemoryCitation
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
from powercontext.sources.pdf_pages import search_pdf_pages


def test_adjacent_evidence_shares_wire_budget_and_long_sentence_remains_literal():
    async def check():
        async with open_builtin_runtime(BuiltinConfig()) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(
                ScopeDraft(title="Packing", summary="Evidence packing", idempotency_key="packing")
            )
            memory = runtime.memory.for_scope(scope.scope_id)
            text = "Background administration. " * 30 + "The cobalt sensor measured pressure. Its reading was 37 units."
            await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(kind="document", text=text),)))
            page = await memory.search(SearchMemoryRequest(query="cobalt sensor pressure", mode="fts", limit=10))
            groups = (PreparedMemoryCandidates(scope_id=scope.scope_id, memory_ref=page.memory_ref, hits=page.hits),)
            result = PreparedContextBuilder().build_scopes_result(
                request=PrepareContextRequest(query="cobalt sensor pressure", max_bytes=1200, evidence_selection=True),
                current_scope_id=scope.scope_id,
                memory_candidates=groups,
            )
            assert any("37 units" in fragment.text for fragment in result.fragments)
            assert result.context.content is not None
            assert result.context.content_bytes == len(result.context.content.encode()) <= 1200
            assert all(fragment.text == text[fragment.start : fragment.end] for fragment in result.fragments)

            long_text = "preface " * 300 + "helium pressure " + "measurement " * 300
            await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(kind="document", text=long_text),)))
            page = await memory.search(SearchMemoryRequest(query="helium", mode="fts", limit=10))
            result = PreparedContextBuilder().build_scopes_result(
                request=PrepareContextRequest(query="helium", max_bytes=1200, evidence_selection=True),
                current_scope_id=scope.scope_id,
                memory_candidates=(
                    PreparedMemoryCandidates(
                        scope_id=scope.scope_id,
                        memory_ref=page.memory_ref,
                        hits=page.hits,
                    ),
                ),
            )
            assert result.fragments and any("helium" in fragment.text for fragment in result.fragments)
            assert all(fragment.text == long_text[fragment.start : fragment.end] for fragment in result.fragments)
            assert result.context.content is not None
            assert result.context.content_bytes == len(result.context.content.encode()) <= 1200

    asyncio.run(check())


def test_financial_query_returns_multiple_statement_pages_and_legal_synonyms():
    ref = ArtifactRef(family="memory", artifact_id="rank-regression", revision=1)
    texts = ["EBITDA unadjusted operating depreciation amortization cash flow analyst " * 30 for _ in range(30)]
    texts += [
        "Consolidated Statement of Income\nNet sales 500. Operating income 100.",
        "Consolidated Statement of Cash Flows\nDepreciation and amortization 20. Capital expenditures 30.",
        "Item 3. Legal Proceedings\nLitigation and contingencies are described below.",
    ]
    records = tuple(
        SimpleNamespace(
            entry=SimpleNamespace(text=text, sources=(SimpleNamespace(source_type="pdf-page", source_id=str(index)),)),
            citation=MemoryCitation(memory_ref=ref, entry_id=str(index), entry_version_id=str(index)),
        )
        for index, text in enumerate(texts)
    )

    class Memory:
        async def search(self, request):
            return SimpleNamespace(hits=())

        async def list(self):
            return SimpleNamespace(entries=records)

    async def check():
        result = await search_pdf_pages(Memory(), "Calculate EBITDA using operating income and D&A from cash flows", 20)
        assert records[30].citation in result and records[31].citation in result
        result = await search_pdf_pages(Memory(), "Are there ongoing legal battles?", 20)
        assert records[32].citation in result[:4]

    asyncio.run(check())
