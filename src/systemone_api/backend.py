import asyncio
import math
from dataclasses import dataclass
from uuid import uuid4

import httpx


class BackendUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Generation:
    logprobs: list[float]
    input_tokens: int
    output_tokens: int
    cached_tokens: int | None


class SGLangBackend:
    def __init__(self, client: httpx.AsyncClient, max_parallel_branches: int):
        self.client = client
        self.capacity = asyncio.Semaphore(max_parallel_branches)

    async def healthy(self) -> bool:
        try:
            response = await self.client.get("/health", timeout=5)
            return response.is_success
        except httpx.HTTPError:
            return False

    async def infer(self, input_ids: list[int], label_ids: list[int] | None = None) -> Generation:
        request_id = f"systemone-{uuid4().hex}"
        selected = label_ids or [0]
        payload = {
            "rid": request_id,
            "input_ids": input_ids,
            "sampling_params": {
                "max_new_tokens": 1,
                "temperature": 1.0,
                "top_p": 1.0,
                "top_k": -1,
                "ignore_eos": True,
            },
            "stream": False,
            "return_logprob": True,
            "token_ids_logprob": selected,
            "logprob_start_len": -1,
            "top_logprobs_num": 0,
            "return_text_in_logprobs": False,
        }
        try:
            async with self.capacity:
                response = await self.client.post("/generate", json=payload)
        except asyncio.CancelledError:
            await self._abort(request_id)
            raise
        except httpx.TimeoutException as exc:
            await self._abort(request_id)
            raise BackendUnavailable("inference backend timed out") from exc
        except httpx.HTTPError as exc:
            raise BackendUnavailable("inference backend is unavailable") from exc
        if not response.is_success:
            raise BackendUnavailable(f"inference backend returned HTTP {response.status_code}")
        try:
            return parse_generation(response.json(), label_ids or [])
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise BackendUnavailable(
                "inference backend returned an invalid probability result"
            ) from exc

    async def _abort(self, request_id: str) -> None:
        try:
            await self.client.post("/abort_request", json={"rid": request_id}, timeout=2)
        except httpx.HTTPError:
            return


def parse_generation(payload: dict, label_ids: list[int]) -> Generation:
    metadata = payload["meta_info"]
    if int(metadata["completion_tokens"]) != 1:
        raise ValueError("expected exactly one generated token")
    logprobs: list[float] = []
    if label_ids:
        positions = metadata["output_token_ids_logprobs"]
        if len(positions) != 1:
            raise ValueError("expected exactly one selected-logprob position")
        by_id: dict[int, float] = {}
        for entry in positions[0]:
            value, token_id = entry[:2]
            number = float(value)
            if token_id in by_id or math.isnan(number) or number == math.inf:
                raise ValueError("invalid selected log probability")
            by_id[int(token_id)] = number
        logprobs = [by_id[token_id] for token_id in label_ids]
    return Generation(
        logprobs=logprobs,
        input_tokens=int(metadata["prompt_tokens"]),
        output_tokens=1,
        cached_tokens=(
            int(metadata["cached_tokens"]) if metadata.get("cached_tokens") is not None else None
        ),
    )
