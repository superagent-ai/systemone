"""Provision the server-only fallback secret without printing credentials or arguments.

Requires explicit operator approval. No deployment, key synchronization or secret overwrite.
The source file contains no credential values. Credentials stay in memory and Modal Secrets.
"""

import argparse
import asyncio
import base64
import json
import subprocess
from urllib.parse import urlsplit

import httpx
import modal
from dotenv import dotenv_values


def management_token():
    result = subprocess.run(
        ["security", "find-generic-password", "-s", "Supabase CLI", "-a", "supabase", "-w"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise RuntimeError("Supabase CLI credential unavailable")
    token = result.stdout.strip()
    if token.startswith("go-keyring-base64:"):
        token = base64.b64decode(token.partition(":")[2]).decode()
    return token


async def provision(env_file: str | None):
    if env_file:
        values = dotenv_values(env_file)
        url = values.get("NEXT_PUBLIC_SUPABASE_URL", "")
        credential = values.get("SUPABASE_SERVICE_ROLE_KEY", "")
    else:
        url = "https://yayfulqubfybgxgrjtwx.supabase.co"
        async with httpx.AsyncClient(
            base_url="https://api.supabase.com/v1/", timeout=10, trust_env=False,
            headers={"Authorization": "Bearer " + management_token()},
        ) as client:
            response = await client.get("projects/yayfulqubfybgxgrjtwx/api-keys")
            if response.status_code != 200:
                raise RuntimeError("Unable to obtain server credential")
            keys = [key["api_key"] for key in response.json()
                    if key.get("name") == "service_role" and not key.get("disabled")]
            if len(keys) != 1:
                raise RuntimeError("Expected one active server credential")
            credential = keys[0]
    target = urlsplit(url)
    if (
        target.scheme != "https"
        or target.netloc != "yayfulqubfybgxgrjtwx.supabase.co"
        or target.path not in {"", "/"}
        or target.query or target.fragment
        or not credential
    ):
        raise RuntimeError("Expected Superagent project and server credential are required")
    url = url.rstrip("/")
    # Verify the live RPC exists and works before storing the credential in Modal.
    async with httpx.AsyncClient(
        base_url=url + "/rest/v1/", timeout=5, trust_env=False,
        headers={"apikey": credential, "Authorization": "Bearer " + credential},
    ) as client:
        response = await client.post(
            "rpc/systemone_api_key_lookup", json={"p_key_hash": "0" * 64},
        )
        if response.status_code != 200 or response.json() != []:
            raise RuntimeError("Lookup RPC verification failed")
    await modal.Secret.objects.create.aio("systemone-customer-auth", {
        "SYSTEMONE_CUSTOMER_KEY_SUPABASE_URL": url,
        "SYSTEMONE_CUSTOMER_KEY_SUPABASE_SERVICE_KEY": credential,
    })
    print(json.dumps({"secret_created": "systemone-customer-auth", "rpc_verified": True,
                      "credential_scope": "broad service_role; server-side only"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", help="Optional matching project environment file")
    args = parser.parse_args()
    try:
        asyncio.run(provision(args.env_file))
    except Exception as exc:
        print(json.dumps({"failed": type(exc).__name__}))
        raise SystemExit(1) from None
