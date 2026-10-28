"""Complete PDF physical-page capture and offline evidence-page retrieval."""

from __future__ import annotations

import hashlib
import io
import math
import re
from collections import Counter

from pydantic import BaseModel, Field, field_validator

from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.sources import AdapterSourceDefinition, TextEvidence
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


class PDFDocumentInput(BaseModel):
    document_id: str
    content: bytes

    @field_validator("document_id")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id must be nonblank")  # noqa: TRY003
        return value


class PDFPageInput(BaseModel):
    document_id: str
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(strict=True, ge=1)
    text: str


class PDFPageSource(Source):
    page: PDFPageInput


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a password")  # noqa: TRY003, TRY301
        digest = hashlib.sha256(value.content).hexdigest()
        pages = tuple(
            PDFPageInput(
                document_id=value.document_id, document_sha256=digest, page_number=index, text=page.extract_text() or ""
            )
            for index, page in enumerate(reader.pages, 1)
        )
        if not pages:
            raise ValueError("PDF must contain physical pages")  # noqa: TRY003, TRY301
    except Exception as exc:
        raise ValueError("unable to parse the complete PDF") from exc  # noqa: TRY003
    return pages


class _PDFAdapter:
    name = "pdf-page"
    input_class = PDFPageInput
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        if not value.document_id.strip():
            raise ValueError("document_id must be nonblank")  # noqa: TRY003
        identity = "pdf:" + hashlib.sha256(value.document_id.encode()).hexdigest() + ":" + value.document_sha256
        return PDFPageSource(
            name=f"{identity}:{value.page_number}", materialization=SourceMaterialization.CAPTURED, page=value
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return source.page


class _PDFProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        page = source.page
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{page.document_id}\n{page.text}",
            metadata={
                "document_id": page.document_id,
                "document_sha256": page.document_sha256,
                "page_number": page.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(_PDFAdapter(), projections=(_PDFProjection(),))

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
    "what",
    "which",
    "how",
    "why",
    "when",
    "where",
    "do",
    "does",
    "did",
    "can",
    "could",
    "should",
    "would",
    "it",
    "its",
    "for",
    "please",
    "calculate",
    "report",
    "reported",
    "company",
    "year",
    "fiscal",
    "much",
    "many",
    "have",
    "has",
    "had",
    "during",
    "based",
    "according",
])


def _terms(text: str) -> list[str]:
    words = re.findall(r"[a-z]+|\d+", text.lower())
    return [word[:-1] if len(word) > 4 and word.endswith("s") else word for word in words if word not in _STOP]


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Rank actual current Memory records, preserving exact source-page identity."""
    from powercontext.builtin.runtime.models import SearchMemoryRequest

    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be positive")  # noqa: TRY003
    if not question.strip():
        return ()
    # The public search provides indexed candidates; the public list supplies the
    # collection statistics and broader recall needed for multi-term financial questions.
    searched = await memory.search(SearchMemoryRequest(query=question, mode="fts", limit=min(100, max(limit, 50))))
    page = await memory.list()
    records = [record for record in page.entries if any(ref.source_type == "pdf-page" for ref in record.entry.sources)]
    if not records:
        return ()
    documents = [Counter(_terms(record.entry.text)) for record in records]
    query = Counter(_terms(question))
    document_frequency = Counter(term for document in documents for term in document)
    average = sum(sum(document.values()) for document in documents) / len(documents) or 1
    search_order = {hit.entry_version_id: index for index, hit in enumerate(searched.hits)}
    scores = []
    for index, document in enumerate(documents):
        length = sum(document.values())
        score = 0.0
        for term, weight in query.items():
            frequency = document[term]
            if frequency:
                idf = math.log(1 + (len(documents) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                score += weight * idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * length / average))
        scores.append((score, search_order.get(records[index].citation.entry_version_id, len(records)), index))
    scores.sort(key=lambda item: (-item[0], item[1], item[2]))
    result, seen = [], set()
    for _, _, index in scores:
        record = records[index]
        identity = tuple(
            (ref.source_type, ref.source_id) for ref in record.entry.sources if ref.source_type == "pdf-page"
        )
        if identity in seen:
            continue
        seen.add(identity)
        result.append(record.citation)
        if len(result) == limit:
            break
    return tuple(result)


__all__ = ["PDF_PAGE_SOURCE_DEFINITION", "PDFDocumentInput", "PDFPageInput", "parse_pdf_document", "search_pdf_pages"]
