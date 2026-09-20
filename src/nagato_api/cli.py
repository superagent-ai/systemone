import argparse
import json
import logging
import os
import time


def serve(args) -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    uvicorn.run("nagato_api.api:app", host=args.host, port=args.port, workers=args.workers)


def smoke(args) -> None:
    import httpx

    key = args.api_key or os.environ.get("NAGATO_API_KEY", "")
    if not key:
        raise SystemExit("Pass --api-key or set NAGATO_API_KEY")
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
                raise SystemExit("Nagato did not become ready before the smoke-test deadline")
            time.sleep(5)
        payload = {
            "model": "nagato",
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
            raise SystemExit("Nagato returned an invalid typed-answer contract")
        print(
            json.dumps(
                {
                    "status": "ok",
                    "startup_wait_seconds": round(inference_started - started, 3),
                    "inference_seconds": round(time.monotonic() - inference_started, 3),
                    "model": body.get("model"),
                    "usage": body.get("usage"),
                    "request_id": response.headers.get("x-nagato-request-id"),
                    "server_timing": response.headers.get("server-timing"),
                },
                indent=2,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="nagato")
    commands = parser.add_subparsers(dest="command", required=True)
    serve_parser = commands.add_parser("serve", help="Run the API process")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--workers", type=int, default=1)
    serve_parser.set_defaults(handler=serve)
    smoke_parser = commands.add_parser("smoke", help="Check a deployed Nagato API")
    smoke_parser.add_argument("url")
    smoke_parser.add_argument("--api-key")
    smoke_parser.add_argument("--startup-timeout", type=float, default=1_200)
    smoke_parser.set_defaults(handler=smoke)
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
