import argparse
import asyncio
import json
import logging
import os
import time
from urllib.parse import urlsplit


def benchmark(args) -> None:
    import httpx

    from .benchmark import benchmark_auth

    key = os.environ.get("SYSTEMONE_API_KEY", "")
    if not key:
        raise SystemExit("Set SYSTEMONE_API_KEY securely in the environment")
    target = urlsplit(args.url)
    if (
        target.scheme not in {"http", "https"} or not target.netloc
        or target.username or target.password or target.query or target.fragment
    ):
        raise SystemExit("Use an HTTP(S) base URL without credentials or query parameters")
    if not 1 <= args.requests <= 100_000 or not 1 <= args.concurrency <= 64 or args.warmup < 0:
        raise SystemExit("Use 1..100000 requests, 1..64 concurrency and nonnegative warmup")

    async def run():
        async with httpx.AsyncClient(
            base_url=args.url.rstrip("/"), timeout=httpx.Timeout(130, connect=5),
            limits=httpx.Limits(
                max_connections=args.concurrency, max_keepalive_connections=args.concurrency,
            ),
        ) as client:
            return await benchmark_auth(
                client, key, mode=args.mode, requests=args.requests,
                concurrency=args.concurrency, warmup=args.warmup,
            )

    try:
        result = asyncio.run(run())
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps(result, indent=2))
    if result["status_counts"].get("200", 0) != args.requests:
        raise SystemExit(1)


def serve(args) -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Structured application logs avoid raw URLs/query strings that may contain secrets.
    uvicorn.run(
        "systemone_api.api:app", host=args.host, port=args.port, workers=args.workers,
        access_log=False,
    )


def smoke(args) -> None:
    import httpx

    key = args.api_key or os.environ.get("SYSTEMONE_API_KEY", "")
    if not key:
        raise SystemExit("Pass --api-key or set SYSTEMONE_API_KEY")
    base_url = args.url.rstrip("/")
    started = time.monotonic()
    deadline = started + args.startup_timeout
    with httpx.Client(base_url=base_url, timeout=130) as client:
        while True:
            try:
                response = client.get("/health")
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                raise SystemExit("SystemOne did not become ready before the smoke-test deadline")
            time.sleep(5)
        payload = {
            "model": "security-one",
            "state": "My card was charged twice. Please refund the duplicate today.",
            "questions": {
                "refund": {
                    "type": "noul",
                    "instructions": "Does the customer request a refund?",
                },
                "team": {
                    "type": "choice",
                    "instructions": "Which team should handle this?",
                    "criteria": {
                        "billing": "Payments and refunds",
                        "technical": "Bugs and integrations",
                    },
                },
                "urgency": {
                    "type": "score",
                    "instructions": "How urgent is the request?",
                    "criteria": ["Routine", "Urgent", "Emergency"],
                },
            },
        }
        inference_started = time.monotonic()
        response = client.post(
            "/v1/systemone",
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
        )
        response.raise_for_status()
        body = response.json()
        expected = {"refund": "noul", "team": "choice", "urgency": "score"}
        observed = {
            question_id: answer.get("type")
            for question_id, answer in body.get("answers", {}).items()
        }
        if observed != expected:
            raise SystemExit("SystemOne returned an invalid typed-answer contract")
        print(
            json.dumps(
                {
                    "status": "ok",
                    "startup_wait_seconds": round(inference_started - started, 3),
                    "inference_seconds": round(time.monotonic() - inference_started, 3),
                    "model": body.get("model"),
                    "usage": body.get("usage"),
                    "request_id": response.headers.get("x-systemone-request-id"),
                    "server_timing": response.headers.get("server-timing"),
                },
                indent=2,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="systemone")
    commands = parser.add_subparsers(dest="command", required=True)
    serve_parser = commands.add_parser("serve", help="Run the API process")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--workers", type=int, default=1)
    serve_parser.set_defaults(handler=serve)
    smoke_parser = commands.add_parser("smoke", help="Check a deployed SystemOne API")
    smoke_parser.add_argument("url")
    smoke_parser.add_argument("--api-key")
    smoke_parser.add_argument("--startup-timeout", type=float, default=1_200)
    smoke_parser.set_defaults(handler=smoke)
    benchmark_parser = commands.add_parser(
        "benchmark-auth", help="Measure p50/p95 auth lookup and end-to-end latency",
    )
    benchmark_parser.add_argument("url")
    benchmark_parser.add_argument("--mode", choices=["lookup", "inference"], default="lookup")
    benchmark_parser.add_argument("--requests", type=int, default=200)
    benchmark_parser.add_argument("--concurrency", type=int, default=8)
    benchmark_parser.add_argument("--warmup", type=int, default=10)
    benchmark_parser.set_defaults(handler=benchmark)
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
