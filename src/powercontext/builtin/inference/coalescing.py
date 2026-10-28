"""Coalesce concurrent embedding work and reuse successful vectors."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from dataclasses import dataclass

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel


@dataclass(eq=False, frozen=True)
class _BatchUsage:
    usage: InferenceUsage


class CoalescingEmbeddingModel:
    """Share in-flight texts without letting one caller cancel shared work."""

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache_size must be a nonnegative integer")  # noqa: TRY003
        if type(coalesce_ms) not in (float, int) or not math.isfinite(coalesce_ms) or coalesce_ms < 0:
            raise ValueError("coalesce_ms must be finite and nonnegative")  # noqa: TRY003
        self.profile = model.profile
        self._model = model
        self._max_batch_size = max_batch_size
        self._delay = coalesce_ms / 1000
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[tuple[EmbeddingVector, _BatchUsage]]] = {}
        self._pending: list[str] = []
        self._scheduled = False
        self._tasks: set[asyncio.Task[None]] = set()

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Restore original positions and charge each awaited batch once."""
        cached: dict[str, EmbeddingVector] = {}
        waiting: dict[str, asyncio.Future[tuple[EmbeddingVector, _BatchUsage]]] = {}
        for text in dict.fromkeys(texts):
            if text in self._cache:
                self._cache.move_to_end(text)
                cached[text] = self._cache[text]
                continue
            future = self._inflight.get(text)
            if future is None:
                future = asyncio.get_running_loop().create_future()
                # A caller may disappear before a failed batch finishes.
                future.add_done_callback(_observe_failure)
                self._inflight[text] = future
                self._pending.append(text)
            waiting[text] = future
        if self._pending and not self._scheduled:
            self._scheduled = True
            self._start(self._dispatch())
        values = await asyncio.gather(*(asyncio.shield(future) for future in waiting.values()))
        batches: set[_BatchUsage] = set()
        for text, (vector, batch) in zip(waiting, values, strict=True):
            cached[text] = vector
            batches.add(batch)
        usages = [batch.usage for batch in batches]
        return EmbeddingResult(
            vectors=tuple(cached[text] for text in texts),
            usage=InferenceUsage(
                requests=sum(usage.requests for usage in usages),
                input_tokens=_sum_tokens([usage.input_tokens for usage in usages]),
                output_tokens=_sum_tokens([usage.output_tokens for usage in usages]),
            ),
        )

    def _start(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _dispatch(self) -> None:
        await asyncio.sleep(self._delay)
        pending, self._pending = self._pending, []
        self._scheduled = False
        for start in range(0, len(pending), self._max_batch_size):
            self._start(self._run_batch(tuple(pending[start : start + self._max_batch_size])))

    async def _run_batch(self, texts: tuple[str, ...]) -> None:
        try:
            result = await self._model.embed(texts)
            if len(result.vectors) != len(texts):
                raise ValueError("embedding vector count differs from input count")  # noqa: TRY003, TRY301
        except (Exception, asyncio.CancelledError) as exc:
            for text in texts:
                future = self._inflight.pop(text)
                if isinstance(exc, asyncio.CancelledError):
                    future.cancel()
                else:
                    future.set_exception(exc)
            return
        batch = _BatchUsage(result.usage)
        for text, vector in zip(texts, result.vectors, strict=True):
            if self._cache_size:
                self._cache[text] = vector
                self._cache.move_to_end(text)
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            self._inflight.pop(text).set_result((vector, batch))


def _observe_failure(future: asyncio.Future[tuple[EmbeddingVector, _BatchUsage]]) -> None:
    if not future.cancelled():
        future.exception()


def _sum_tokens(values: list[int | None]) -> int | None:
    return sum(value for value in values if value is not None) if any(value is not None for value in values) else None


__all__ = ["CoalescingEmbeddingModel"]
