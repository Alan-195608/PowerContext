"""Self-contained UTF-8 context packs and checked prefix deltas."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, cast

_PACK = "powercontext.context-pack.v1"
_DELTA = "powercontext.context-pack-delta.v1"


class ContextPackError(ValueError):
    """Invalid context pack, wire payload, or delta base."""


def _encode(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _items(items: tuple[bytes, ...]) -> list[str]:
    if not isinstance(items, tuple):
        raise ContextPackError("items must be a tuple of UTF-8 bytes")  # noqa: TRY003
    try:
        for item in items:
            if not isinstance(item, bytes):
                raise ContextPackError("items must be bytes")  # noqa: TRY003
            item.decode("utf-8")
        return [base64.b64encode(item).decode("ascii") for item in items]
    except UnicodeError as exc:
        raise ContextPackError("items must be valid UTF-8") from exc  # noqa: TRY003


def _decode_items(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ContextPackError("wire items must be an array of Base64 strings")  # noqa: TRY003
    try:
        items = tuple(base64.b64decode(item, validate=True) for item in cast(list[str], value))
        if _items(items) != value:
            raise ContextPackError("Base64 items must use canonical encoding")  # noqa: TRY003
    except (ValueError, binascii.Error) as exc:
        raise ContextPackError("invalid encoded items") from exc  # noqa: TRY003
    return items


def _payload(data: bytes, fields: set[str], schema: str) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ContextPackError("duplicate JSON field")  # noqa: TRY003
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError, AttributeError) as exc:
        raise ContextPackError("invalid UTF-8 JSON") from exc  # noqa: TRY003
    if not isinstance(value, dict) or set(value) != fields or value["schema"] != schema:
        raise ContextPackError("invalid wire fields or schema")  # noqa: TRY003
    return value


def _digest(value: object) -> None:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ContextPackError("invalid SHA-256 digest")  # noqa: TRY003


@dataclass(frozen=True)
class ContextPack:
    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        wire_items = _items(items)
        digest = "sha256:" + hashlib.sha256(_encode({"schema": _PACK, "items": wire_items})).hexdigest()
        count = 0
        while True:
            size = len(_encode({"schema": _PACK, "items": wire_items, "digest": digest, "byte_count": count}))
            if size == count:
                return cls(items, digest, count)
            count = size

    @classmethod
    def from_content(cls, content: str | None, *, chunk_bytes: int = 512) -> ContextPack:
        if type(chunk_bytes) is not int or chunk_bytes < 1 or (content is not None and not isinstance(content, str)):
            raise ContextPackError("invalid content or chunk limit")  # noqa: TRY003
        chunks: list[bytes] = []
        buffer = bytearray()
        for char in content or "":
            try:
                encoded = char.encode("utf-8")
            except UnicodeError as exc:
                raise ContextPackError("invalid UTF-8 content") from exc  # noqa: TRY003
            if len(encoded) > chunk_bytes:
                raise ContextPackError("chunk limit cannot hold a UTF-8 character")  # noqa: TRY003
            if len(buffer) + len(encoded) > chunk_bytes:
                chunks.append(bytes(buffer))
                buffer.clear()
            buffer.extend(encoded)
        if buffer:
            chunks.append(bytes(buffer))
        return cls.build(tuple(chunks))

    def to_bytes(self) -> bytes:
        return _encode({
            "schema": _PACK,
            "items": _items(self.items),
            "digest": self.digest,
            "byte_count": self.byte_count,
        })

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        payload = _payload(data, {"schema", "items", "digest", "byte_count"}, _PACK)
        pack = cls.build(_decode_items(payload["items"]))
        if (
            payload["digest"] != pack.digest
            or type(payload["byte_count"]) is not int
            or payload["byte_count"] != pack.byte_count
        ):
            raise ContextPackError("pack digest or byte count does not match")  # noqa: TRY003
        return pack


@dataclass(frozen=True)
class ContextPackDelta:
    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        _validate_pack(base)
        _validate_pack(target)
        prefix = 0
        for first, second in zip(base.items, target.items, strict=False):
            if first != second:
                break
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    def to_bytes(self) -> bytes:
        self._validate()
        return _encode({
            "schema": _DELTA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _items(self.appended),
        })

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def _validate(self) -> None:
        _digest(self.base_digest)
        _digest(self.target_digest)
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("prefix must be a nonnegative integer")  # noqa: TRY003
        _items(self.appended)

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        payload = _payload(data, {"schema", "base_digest", "target_digest", "prefix_items", "appended"}, _DELTA)
        delta = cls(
            payload["base_digest"],
            payload["target_digest"],
            payload["prefix_items"],
            _decode_items(payload["appended"]),
        )
        delta._validate()
        return delta


def _validate_pack(pack: ContextPack) -> None:
    if not isinstance(pack, ContextPack) or ContextPack.build(pack.items) != pack:
        raise ContextPackError("invalid base or target pack")  # noqa: TRY003


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    _validate_pack(base)
    delta._validate()
    if delta.base_digest != base.digest or delta.prefix_items > len(base.items):
        raise ContextPackError("delta base or prefix does not match")  # noqa: TRY003
    target = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        raise ContextPackError("target digest does not match reconstructed content")  # noqa: TRY003
    return target


__all__ = ["ContextPack", "ContextPackDelta", "ContextPackError", "apply_context_pack_delta"]
