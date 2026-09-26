import asyncio
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import orjson
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer
from starlette.types import ASGIApp, Receive, Scope, Send

from .backend import BackendUnavailable, SGLangBackend
from .config import Settings
from .models import ErrorResponse, SystemOneRequest, SystemOneResponse
from .prompts import PromptCompiler
from .runtime import load_tokenizer, wait_until_ready
from .service import EvaluationService, RequestRejected

logger = logging.getLogger("systemone.api")
bearer_auth = HTTPBearer(auto_error=False)


class ORJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return orjson.dumps(content)


class RequestGuard:
    """Authenticate API routes and bound chunked bodies before JSON parsing."""

    PUBLIC_PATHS = {"/", "/docs", "/openapi.json", "/models", "/health", "/health/live"}

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid4().hex
        headers = dict(scope["headers"])
        if scope["path"] not in self.PUBLIC_PATHS and self.settings.accepted_api_keys:
            supplied = headers.get(b"authorization", b"").decode("latin-1")
            prefix = "Bearer "
            token = supplied[len(prefix) :] if supplied.startswith(prefix) else ""
            valid = False
            for expected in self.settings.accepted_api_keys:
                valid = secrets.compare_digest(token, expected) or valid
            if not valid:
                return await self._error(
                    send, receive, scope, 401, "Missing or invalid API key", request_id
                )
        if scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self._with_request_id(scope, receive, send, request_id)
        body = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            body.extend(event.get("body", b""))
            if len(body) > self.settings.max_body_bytes:
                return await self._error(
                    send, receive, scope, 413, "Request body is too large", request_id
                )
            if not event.get("more_body", False):
                break
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self._with_request_id(scope, replay, send, request_id)

    async def _with_request_id(self, scope, receive, send, request_id: str):
        async def add_header(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (b"x-systemone-request-id", request_id.encode())
                )
            await send(message)

        await self.app(scope, receive, add_header)

    async def _error(self, send, receive, scope, status: int, message: str, request_id: str):
        headers = {"x-systemone-request-id": request_id}
        if status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        response = ORJSONResponse(
            {"error": {"message": message}},
            status_code=status,
            headers=headers,
        )
        await response(scope, receive, send)


def create_app(
    settings: Settings | None = None,
    *,
    service: EvaluationService | None = None,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if service is not None:
            app.state.service = service
            app.state.startup_seconds = 0.0
            yield
            return
        started = time.monotonic()
        backend_headers = {}
        backend_key = settings.backend_api_key.get_secret_value()
        if backend_key:
            backend_headers["Authorization"] = f"Bearer {backend_key}"
        limits = httpx.Limits(
            max_connections=settings.max_concurrent_branches + 8,
            max_keepalive_connections=settings.max_concurrent_branches + 8,
        )
        timeout = httpx.Timeout(settings.request_timeout_seconds, connect=5)
        async with httpx.AsyncClient(
            base_url=settings.backend_url,
            headers=backend_headers,
            limits=limits,
            timeout=timeout,
        ) as client:
            backend = SGLangBackend(client, settings.max_concurrent_branches)
            await wait_until_ready(backend, settings.startup_timeout_seconds)
            tokenizer = await asyncio.to_thread(load_tokenizer, settings.model_path)
            app.state.service = EvaluationService(
                settings, PromptCompiler(tokenizer, settings.max_answers), backend
            )
            app.state.startup_seconds = round(time.monotonic() - started, 3)
            yield

    app = FastAPI(
        title="SystemOne API",
        summary="Deterministic structured classification",
        description=(
            "OpenJev-compatible SystemOne API backed by SystemOne. Send shared state and typed "
            "noul, choice, or score questions; receive probability distributions in one call."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        default_response_class=ORJSONResponse,
    )
    app.add_middleware(RequestGuard, settings=settings)

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        logger.info(
            json.dumps(
                {
                    "event": "request",
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
                separators=(",", ":"),
            )
        )
        return response

    @app.exception_handler(RequestRejected)
    async def rejected_handler(_request: Request, exc: RequestRejected):
        return ORJSONResponse(
            {"error": {"message": str(exc)}},
            status_code=exc.status_code,
            headers={"Retry-After": "1"} if exc.status_code == 503 else {},
        )

    @app.exception_handler(BackendUnavailable)
    async def backend_handler(_request: Request, _exc: BackendUnavailable):
        return ORJSONResponse(
            {"error": {"message": "Temporarily unavailable"}},
            status_code=503,
            headers={"Retry-After": "1"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError):
        first = exc.errors()[0]
        location = ".".join(str(item) for item in first.get("loc", [])[1:])
        message = first.get("msg", "Invalid request")
        return ORJSONResponse(
            {"error": {"message": f"{location}: {message}" if location else message}},
            status_code=422,
        )

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    async def reference():
        return HTMLResponse(
            """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SystemOne API</title>
</head><body><div id="app"></div>
<script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
<script>Scalar.createApiReference('#app',{url:'/openapi.json',theme:'saturn'});</script>
</body></html>"""
        )

    @app.post(
        "/v1/systemone",
        response_model=SystemOneResponse,
        responses={
            401: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
        tags=["SystemOne"],
        dependencies=[Depends(bearer_auth)],
    )
    async def systemone(payload: SystemOneRequest, request: Request):
        evaluation = await request.app.state.service.evaluate(payload)
        headers = {
            "x-systemone-model": settings.served_model,
            "x-systemone-prefix-tokens": str(evaluation.prefix_tokens),
            "Server-Timing": (
                f"prepare;dur={evaluation.prepare_ms:.2f},"
                f"prefill;dur={evaluation.prefill_ms:.2f},"
                f"branches;dur={evaluation.branches_ms:.2f}"
            ),
        }
        if evaluation.cached_tokens is not None:
            headers["x-systemone-cached-tokens"] = str(evaluation.cached_tokens)
        return ORJSONResponse(evaluation.response.model_dump(by_alias=True), headers=headers)

    @app.get("/v1/models", tags=["Models"], dependencies=[Depends(bearer_auth)])
    async def models():
        return {
            "object": "list",
            "data": [
                {"id": name, "object": "model", "owned_by": "systemone"}
                for name in settings.accepted_models
            ],
            "models": [
                {
                    "name": name,
                    "description": f"SystemOne classification using {settings.served_model}",
                    "release_date": settings.release_date,
                }
                for name in settings.accepted_models
            ],
        }

    @app.get("/models", tags=["Models"])
    async def provider_models():
        """OpenRouter provider model document (schema 2.4)."""
        return {
            "data": [
                {
                    "schema_version": "2.4",
                    "id": settings.served_model,
                    "name": "Superagent: Security-One 27B",
                    "hugging_face_id": "superagent-ai/security-one-27b",
                    "created": 1790294400,
                    "quantization": "bf16",
                    "description": (
                        "A calibrated 27B decision model for always-on security triage "
                        "across applications, agents, code, and infrastructure."
                    ),
                    "input_modalities": [
                        {
                            "type": "text",
                            "supported_inputs": {
                                "max_context_length": {
                                    "value": settings.max_input_tokens,
                                    "unit": "token",
                                }
                            },
                            "pricing": [
                                {
                                    "type": "prompt",
                                    "unit": "token",
                                    "cost_usd": "0.00000005",
                                }
                            ],
                        }
                    ],
                    "output_modalities": [
                        {
                            "type": "text",
                            "max_length": {"value": 65, "unit": "token"},
                            "streaming": False,
                            "supported_parameters": {},
                            "pricing": [
                                {
                                    "type": "completion",
                                    "unit": "token",
                                    "cost_usd": "0",
                                }
                            ],
                            "capacity": [
                                {
                                    "type": "concurrency",
                                    "unit": "request",
                                    "value": settings.max_concurrent_requests,
                                }
                            ],
                        }
                    ],
                    "is_ready": True,
                    "is_free": False,
                }
            ]
        }

    @app.get("/v1/limits", tags=["Limits"], dependencies=[Depends(bearer_auth)])
    async def limits():
        return {
            "max_answers_per_question": settings.max_answers,
            "max_questions": settings.max_questions,
            "max_body_bytes": settings.max_body_bytes,
            "max_input_tokens": settings.max_input_tokens,
            "max_total_input_tokens": settings.max_total_input_tokens,
            "max_concurrent_requests": settings.max_concurrent_requests,
        }

    @app.get("/health", tags=["Health"])
    async def health(request: Request):
        healthy = await request.app.state.service.backend.healthy()
        return ORJSONResponse(
            {
                "status": "ok" if healthy else "unavailable",
                "startup_seconds": getattr(request.app.state, "startup_seconds", None),
            },
            status_code=200 if healthy else 503,
        )

    @app.get("/health/live", tags=["Health"])
    async def live():
        return {"status": "ok"}

    return app


app = create_app()
