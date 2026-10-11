"""Approved live rollout checks. Temporary key is deleted in finally; output is aggregate only."""

import asyncio
import hashlib
import json
import os
import secrets
import time
from uuid import uuid4

import modal

app = modal.App("systemone-auth-rollout-check")
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("httpx==0.28.1")
    .add_local_file("src/systemone_api/benchmark.py", "/app/benchmark.py", copy=True)
    .env({"PYTHONPATH": "/app"})
)


@app.function(
    image=image, cpu=1, timeout=1200, max_containers=1,
    secrets=[modal.Secret.from_name("systemone-customer-auth"),
             modal.Secret.from_name("systemone-testing-key")],
)
async def verify():
    import httpx
    from benchmark import benchmark_auth

    stage = "setup"
    row_id = str(uuid4())
    key = "sk_live_" + secrets.token_hex(16)
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    created = False
    deleted = False
    outcome = {}
    service_key = os.environ["SYSTEMONE_CUSTOMER_KEY_SUPABASE_SERVICE_KEY"]
    url = os.environ["SYSTEMONE_CUSTOMER_KEY_SUPABASE_URL"]
    static = os.environ["SYSTEMONE_API_KEYS_SECONDARY"].split(",")[0].strip()
    headers = {"Authorization": "Bearer " + key}
    rpc = "rpc/systemone_api_key_lookup"
    async with httpx.AsyncClient(
        base_url=url + "/rest/v1/", timeout=10, trust_env=False,
        headers={"apikey": service_key, "Authorization": "Bearer " + service_key},
    ) as db, httpx.AsyncClient(
        base_url="https://superagentai--systemone-api-web.modal.run", timeout=130, trust_env=False,
    ) as direct, httpx.AsyncClient(
        base_url="https://api.superagent.sh", timeout=130, trust_env=False,
    ) as domain:
        try:
            stage = "readiness"
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                try:
                    ready = await direct.get("/health", timeout=15)
                    if ready.status_code == 200 and "auth;dur=" in ready.headers.get(
                        "server-timing", ""
                    ):
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(5)
            else:
                raise RuntimeError("New deployment readiness timeout")
            stage = "public_routes"
            for path in ("/", "/docs", "/openapi.json", "/models", "/health", "/health/live"):
                if (await direct.get(path)).status_code != 200:
                    raise RuntimeError("Public route failed")
            stage = "negative_keys"
            for invalid in (None, "wrong-key", "sk_live_" + "0" * 32):
                auth = {} if invalid is None else {"Authorization": "Bearer " + invalid}
                response = await direct.post("/v1/systemone", content=b"not json", headers=auth)
                if response.status_code != 401 or response.json() != {
                    "error": {"message": "Missing or invalid API key"}
                }:
                    raise RuntimeError("Negative authentication failed")
            stage = "static_fallback"
            if (await direct.get(
                "/v1/limits", headers={"Authorization": "Bearer " + static}
            )).status_code != 200:
                raise RuntimeError("Static fallback failed")
            stage = "temporary_key_creation"
            orgs = await db.get("organizations", params={
                "select": "id", "name": "eq.Superagent", "order": "created_at.asc", "limit": "1",
            })
            orgs.raise_for_status()
            if len(orgs.json()) != 1:
                raise RuntimeError("Internal test organization unavailable")
            org_id = orgs.json()[0]["id"]
            response = await db.post("api_keys", json={
                "id": row_id, "organization_id": org_id, "key_hash": key_hash,
                "key_prefix": key[:16],
            })
            response.raise_for_status()
            created = True
            identity = await db.post(rpc, json={"p_key_hash": key_hash})
            if identity.status_code != 200 or identity.json() != [{
                "id": row_id, "organization_id": org_id,
            }]:
                raise RuntimeError("Lookup identity failed")
            stage = "customer_key"
            response = await direct.get("/v1/limits", headers=headers)
            if response.status_code != 200:
                raise RuntimeError("Customer authentication failed")
            stage = "direct_lookup_latency"
            print(json.dumps({"stage": stage}), flush=True)
            outcome["direct_lookup"] = await benchmark_auth(
                direct, key, requests=100, concurrency=8, warmup=10,
            )
            stage = "direct_inference_latency"
            print(json.dumps({"stage": stage}), flush=True)
            outcome["direct_inference"] = await benchmark_auth(
                direct, key, mode="inference", requests=100, concurrency=4, warmup=10,
            )
            stage = "domain_inference_latency"
            print(json.dumps({"stage": stage}), flush=True)
            outcome["domain_inference"] = await benchmark_auth(
                domain, key, mode="inference", requests=100, concurrency=4, warmup=10,
            )
            stage = "static_inference_latency"
            print(json.dumps({"stage": stage}), flush=True)
            outcome["static_inference"] = await benchmark_auth(
                direct, static, mode="inference", requests=50, concurrency=4, warmup=5,
            )
            # Report every failed attempt, but still verify immediate revocation.
            # A benchmark transport failure must not hide the security checks or
            # earlier measurements; it is not evidence of an authentication outage.
            outcome["benchmark_failed_attempts"] = sum(
                result["requests"] - result["status_counts"].get("200", 0)
                for result in outcome.values()
            )
            stage = "revocation"
            removal = await db.delete("api_keys", params={"id": "eq." + row_id})
            removal.raise_for_status()
            deleted = True
            response = await direct.get("/v1/limits", headers=headers)
            if response.status_code != 401:
                raise RuntimeError("Immediate revocation failed")
            # Also verify revocation reaches the domain rewrite before body parsing.
            response = await domain.post("/v1/systemone", headers=headers, content=b"not json")
            if response.status_code != 401:
                raise RuntimeError("Domain revocation failed")
            outcome["verification"] = {
                "public_routes": 6, "invalid_keys": 3, "static_fallback": True,
                "customer_key": True, "identity": True, "immediate_revocation": True,
                "temporary_key_deleted": True,
            }
        except Exception as exc:
            outcome.update({"failed_stage": stage, "error_type": type(exc).__name__})
        finally:
            if created and not deleted:
                removal = await db.delete("api_keys", params={"id": "eq." + row_id})
                outcome["temporary_key_deleted"] = removal.status_code in {200, 204}
    return outcome


@app.local_entrypoint()
def main():
    result = verify.remote()
    print(json.dumps(result, indent=2))
    if "failed_stage" in result or result.get("benchmark_failed_attempts", 0):
        raise SystemExit(1)
