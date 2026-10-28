"""Identity-preserving reranking through a bounded HTTP scoring service."""

from __future__ import annotations

import math
from typing import Any

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage


class HTTPMemoryReranker:
    """Score every candidate once, then select by global score and original rank."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(self, query: str, candidates: tuple[MemoryHit, ...], limit: int, /) -> MemoryRerankDecision:
        """Return original one-based ranks without altering candidate identities."""
        if not candidates or type(limit) is not int or not 1 <= limit <= len(candidates):
            raise ValueError("limit must be between one and the nonempty candidate count")  # noqa: TRY003
        scores: dict[int, float] = {}
        requests = 0
        for start in range(0, len(candidates), self._batch_size):
            batch = [
                {"rank": offset + 1, "text": candidates[offset].text}
                for offset in range(start, min(start + self._batch_size, len(candidates)))
            ]
            response = await self._client.post(self._endpoint, json={"query": query, "candidates": batch})
            requests += 1
            response.raise_for_status()
            scores.update(_read_scores(response.json(), set(range(start + 1, start + len(batch) + 1))))
        selected = tuple(sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit])
        return MemoryRerankDecision(selected_ranks=selected, usage=InferenceUsage(requests=requests))


def _read_scores(payload: Any, expected: set[int]) -> dict[int, float]:
    if not isinstance(payload, dict) or set(payload) != {"scores"} or not isinstance(payload["scores"], list):
        raise ValueError("response must contain only a scores array")  # noqa: TRY003
    scores: dict[int, float] = {}
    for item in payload["scores"]:
        if not isinstance(item, dict) or set(item) != {"rank", "score"}:
            raise ValueError("score records must contain only rank and score")  # noqa: TRY003
        rank, score = item["rank"], item["score"]
        if type(rank) is not int or rank not in expected or rank in scores:
            raise ValueError("response ranks must cover the requested batch exactly once")  # noqa: TRY003
        if type(score) not in (int, float):
            raise ValueError("score must be a finite number")  # noqa: TRY003
        try:
            value = float(score)
        except OverflowError as exc:
            raise ValueError("score must be finite") from exc  # noqa: TRY003
        if not math.isfinite(value):
            raise ValueError("score must be finite")  # noqa: TRY003
        scores[rank] = value
    if scores.keys() != expected:
        raise ValueError("response is missing requested ranks")  # noqa: TRY003
    return scores


__all__ = ["HTTPMemoryReranker"]
