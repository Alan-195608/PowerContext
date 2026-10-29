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


def test_pdf_company_identity_prevents_cross_issuer_statement_matches():
    ref = ArtifactRef(family="memory", artifact_id="issuer-regression", revision=1)
    texts = [
        "BETA_2022_10K\nConsolidated Statement of Income\nOperating income gross margin revenue " * 20
        for _ in range(30)
    ] + [
        "ALPHACORPORATION_2022_10K\nConsolidated Statement of Income\nRevenue 500. Operating income 100.",
        "ALPHACORPORATION_2022_10K\nConsolidated Statement of Cash Flows\nDepreciation 20. Capital expenditures 30.",
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
        for name in ("Alpha Corporation", "ALCO"):
            citations = await search_pdf_pages(Memory(), f"What was {name}'s operating margin in 2022?", 2)
            assert {c.entry_id for c in citations} == {"30", "31"}

    asyncio.run(check())


def test_query_word_forms_find_late_literal_evidence():
    async def check():
        async with open_builtin_runtime(BuiltinConfig()) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(
                ScopeDraft(title="Inflections", summary="Literal selection", idempotency_key="inflections")
            )
            memory = runtime.memory.for_scope(scope.scope_id)
            text = "The enzyme was used for routine laboratory preparation. " * 30
            text += "Results showed that the enzyme phosphorylated the target after activation."
            await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(kind="document", text=text),)))
            page = await memory.search(SearchMemoryRequest(query="enzyme", mode="fts", limit=10))
            result = PreparedContextBuilder().build_scopes_result(
                request=PrepareContextRequest(
                    query="enzyme phosphorylation activates target", max_bytes=1200, evidence_selection=True
                ),
                current_scope_id=scope.scope_id,
                memory_candidates=(
                    PreparedMemoryCandidates(scope_id=scope.scope_id, memory_ref=page.memory_ref, hits=page.hits),
                ),
            )
            assert result.fragments and any("phosphorylated the target" in f.text for f in result.fragments)
            assert all(f.text == text[f.start : f.end] for f in result.fragments)
            assert result.context.content is not None
            assert result.context.content_bytes == len(result.context.content.encode()) <= 1200

    asyncio.run(check())


def test_oversized_sentence_keeps_late_evidence_despite_an_early_common_query_word():
    async def check():
        for with_distractor in (False, True):
            async with open_builtin_runtime(BuiltinConfig()) as runtime:
                assert runtime.scopes is not None
                scope = await runtime.scopes.create(
                    ScopeDraft(
                        title="Long literal evidence",
                        summary="Late evidence in one sentence",
                        idempotency_key="long-evidence",
                    )
                )
                memory = runtime.memory.for_scope(scope.scope_id)
                text = "sensor records " + "routine " * 350 + "cobalt sensor calibrated at 37 degrees"
                entries = [MemoryEntryInput(kind="document", text=text)]
                if with_distractor:
                    entries.append(
                        MemoryEntryInput(kind="document", text="The sensor was calibrated for an old experiment.")
                    )
                await memory.remember(RememberMemoryRequest(entries=tuple(entries)))
                page = await memory.search(SearchMemoryRequest(query="cobalt sensor calibrated", mode="fts", limit=10))
                result = PreparedContextBuilder().build_scopes_result(
                    request=PrepareContextRequest(
                        query="cobalt sensor calibrated", max_bytes=1200, evidence_selection=True
                    ),
                    current_scope_id=scope.scope_id,
                    memory_candidates=(
                        PreparedMemoryCandidates(scope_id=scope.scope_id, memory_ref=page.memory_ref, hits=page.hits),
                    ),
                )
                assert any("cobalt sensor calibrated at 37 degrees" in f.text for f in result.fragments), (
                    with_distractor,
                    [f.text[-120:] for f in result.fragments],
                )
                assert result.context.content is not None
                assert result.context.content_bytes == len(result.context.content.encode()) <= 1200
                originals = {h.entry_id: h.text for h in page.hits}
                assert all(f.text == originals[f.address.entry_id][f.start : f.end] for f in result.fragments)

    asyncio.run(check())


def test_scientific_symbol_matches_its_name_without_rewriting_evidence():
    async def check():
        async with open_builtin_runtime(BuiltinConfig()) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(
                ScopeDraft(title="Symbols", summary="Literal scientific notation", idempotency_key="symbols")
            )
            memory = runtime.memory.for_scope(scope.scope_id)
            text = "Administrative background. " * 60 + "The β marker increased after treatment."
            await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(kind="document", text=text),)))
            page = await memory.search(SearchMemoryRequest(query="marker", mode="fts", limit=10))
            result = PreparedContextBuilder().build_scopes_result(
                request=PrepareContextRequest(query="beta", max_bytes=1200, evidence_selection=True),
                current_scope_id=scope.scope_id,
                memory_candidates=(
                    PreparedMemoryCandidates(scope_id=scope.scope_id, memory_ref=page.memory_ref, hits=page.hits),
                ),
            )
            assert any("The β marker increased after treatment." in f.text for f in result.fragments)
            assert all(f.text == text[f.start : f.end] for f in result.fragments)
            assert result.context.content is not None
            assert result.context.content_bytes == len(result.context.content.encode()) <= 1200

    asyncio.run(check())
