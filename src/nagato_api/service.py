import asyncio
import time
from dataclasses import dataclass

from .backend import Generation, SGLangBackend
from .config import Settings
from .models import (
    ChoiceQuestion,
    NoulQuestion,
    ScoreQuestion,
    SystemOneRequest,
    SystemOneResponse,
    Usage,
)
from .prompts import Branch, PromptCompiler
from .scoring import choice_answer, noul_answer, score_answer


class RequestRejected(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Evaluation:
    response: SystemOneResponse
    prefix_tokens: int
    cached_tokens: int | None
    prepare_ms: float
    prefill_ms: float
    branches_ms: float


class EvaluationService:
    def __init__(self, settings: Settings, compiler: PromptCompiler, backend: SGLangBackend):
        self.settings = settings
        self.compiler = compiler
        self.backend = backend
        self.active_requests = 0

    async def evaluate(self, request: SystemOneRequest) -> Evaluation:
        if request.model not in self.settings.accepted_models:
            raise RequestRejected(f"Unknown model: {request.model}")
        if self.active_requests >= self.settings.max_concurrent_requests:
            raise RequestRejected("Server is at capacity; retry shortly", 503)
        self.active_requests += 1
        try:
            async with asyncio.timeout(self.settings.request_timeout_seconds):
                return await self._evaluate(request)
        except TimeoutError as exc:
            raise RequestRejected("Evaluation deadline exceeded", 503) from exc
        finally:
            self.active_requests -= 1

    async def _evaluate(self, request: SystemOneRequest) -> Evaluation:
        started = time.perf_counter()
        try:
            prepared = await asyncio.to_thread(self.compiler.prepare, request)
        except (TypeError, ValueError) as exc:
            raise RequestRejected(str(exc)) from exc
        if any(
            len(branch.input_ids) + 1 > self.settings.max_input_tokens
            for branch in prepared.branches
        ):
            raise RequestRejected(
                "A question branch exceeds the "
                f"{self.settings.max_input_tokens}-token context limit"
            )
        total_tokens = len(prepared.common_prefix_ids) + sum(
            len(branch.input_ids) for branch in prepared.branches
        )
        if total_tokens > self.settings.max_total_input_tokens:
            raise RequestRejected("Request exceeds the total input-token budget across branches")

        prepared_at = time.perf_counter()
        warmup: Generation | None = None
        if prepared.common_prefix_ids:
            warmup = await self.backend.infer(prepared.common_prefix_ids)
        warmed_at = time.perf_counter()
        tasks = [
            asyncio.create_task(self.backend.infer(branch.input_ids, branch.label_ids))
            for branch in prepared.branches
        ]
        try:
            results = await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        answers = {
            branch.question_id: self._answer(branch, result)
            for branch, result in zip(prepared.branches, results, strict=True)
        }
        generations = ([warmup] if warmup else []) + results
        cached = (
            sum(item.cached_tokens for item in generations if item.cached_tokens is not None)
            if all(item.cached_tokens is not None for item in generations)
            else None
        )
        return Evaluation(
            response=SystemOneResponse(
                model=request.model,
                answers=answers,
                usage=Usage(
                    input_tokens=sum(item.input_tokens for item in generations),
                    output_tokens=sum(item.output_tokens for item in generations),
                ),
            ),
            prefix_tokens=len(prepared.common_prefix_ids),
            cached_tokens=cached,
            prepare_ms=(prepared_at - started) * 1000,
            prefill_ms=(warmed_at - prepared_at) * 1000,
            branches_ms=(time.perf_counter() - warmed_at) * 1000,
        )

    def _answer(self, branch: Branch, result: Generation):
        question = branch.question
        if isinstance(question, NoulQuestion):
            return noul_answer(result.logprobs, self.settings.temperature)
        if isinstance(question, ChoiceQuestion):
            return choice_answer(branch.option_keys, result.logprobs, self.settings.temperature)
        assert isinstance(question, ScoreQuestion)
        return score_answer(question.criteria, result.logprobs, self.settings.temperature)
