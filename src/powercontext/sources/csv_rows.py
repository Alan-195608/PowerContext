"""Lossless CSV row evidence with document/key identities."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel, model_validator

from powercontext.sources import AdapterSourceDefinition, TextEvidence
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Encode each identity component independently, without trimming keys."""
    if not document_id or document_id != document_id.strip() or not primary_key_value.strip():
        raise ValueError("document and primary key identities must be nonblank")  # noqa: TRY003
    identity = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(identity) > 256:
        raise ValueError("CSV source identity exceeds 256 characters")  # noqa: TRY003
    return identity


class CSVDocumentInput(BaseModel):
    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_row(self) -> CSVRowInput:
        csv_row_source_id(self.document_id, self.primary_key_value)
        if (
            not self.columns
            or any(not column.strip() for column in self.columns)
            or len(set(self.columns)) != len(self.columns)
            or len(self.columns) != len(self.values)
            or self.primary_key not in self.columns
        ):
            raise ValueError("CSV columns, primary key and row width must agree")  # noqa: TRY003
        if self.values[self.columns.index(self.primary_key)] != self.primary_key_value:
            raise ValueError("primary key value must match the original row")  # noqa: TRY003
        return self


class CSVRowSource(Source):
    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Validate the whole document before returning any captured row."""
    if not value.document_id or value.document_id != value.document_id.strip() or not value.primary_key:
        raise ValueError("invalid document identity or primary key")  # noqa: TRY003
    reader = csv.reader(io.StringIO(value.content.decode("utf-8-sig"), newline=""), strict=True)
    try:
        columns = tuple(next(reader, ()))
        if (
            not columns
            or any(not column.strip() for column in columns)
            or len(set(columns)) != len(columns)
            or value.primary_key not in columns
        ):
            raise ValueError("CSV header must contain unique nonblank columns and the primary key")  # noqa: TRY003
        key_index = columns.index(value.primary_key)
        rows: list[CSVRowInput] = []
        keys: set[str] = set()
        for record in reader:
            if not record:
                continue
            if len(record) != len(columns):
                raise ValueError("CSV row width differs from the header")  # noqa: TRY003
            key = record[key_index]
            if key in keys or not key.strip():
                raise ValueError("CSV primary keys must be nonblank and unique")  # noqa: TRY003
            keys.add(key)
            rows.append(
                CSVRowInput(
                    document_id=value.document_id,
                    primary_key=value.primary_key,
                    primary_key_value=key,
                    columns=columns,
                    values=tuple(record),
                )
            )
        return tuple(rows)
    except csv.Error as exc:
        raise ValueError("malformed CSV document") from exc  # noqa: TRY003


class _CSVRowAdapter:
    name = "csv-row"
    input_class = CSVRowInput
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        identity = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=identity, source_id=identity, materialization=SourceMaterialization.CAPTURED, **value.model_dump()
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput.model_validate(source.model_dump())


class _CSVRowProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type="csv-row",
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


CSV_ROW_SOURCE_DEFINITION = AdapterSourceDefinition(_CSVRowAdapter(), projections=(_CSVRowProjection(),))

__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
