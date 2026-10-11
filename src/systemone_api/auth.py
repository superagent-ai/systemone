"""Authoritative customer-key lookups. No plaintext keys, result cache, or writes."""
import asyncio
import ssl
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

import asyncpg
import httpx

from .config import Settings

LOOKUP_SQL = "SELECT id, organization_id FROM public.api_keys WHERE key_hash = $1 LIMIT 2"


@dataclass(frozen=True)
class AuthenticatedKey:
    source: Literal["static", "organization", "development"]
    key_id: str | None = None
    organization_id: str | None = None


class AuthenticationUnavailable(Exception):
    """Sanitized lookup failure; must never be confused with an unknown key."""


class CustomerKeyValidator(Protocol):
    async def validate_hash(self, key_hash: str) -> AuthenticatedKey | None: ...


def identity_from_rows(rows) -> AuthenticatedKey | None:
    if not isinstance(rows, list):
        raise AuthenticationUnavailable("Authentication temporarily unavailable")
    if not rows:
        return None
    if len(rows) != 1:
        raise AuthenticationUnavailable("Authentication temporarily unavailable")
    return AuthenticatedKey(
        source="organization",
        key_id=str(UUID(str(rows[0]["id"]))),
        organization_id=str(UUID(str(rows[0]["organization_id"]))),
    )


class SupabaseKeyValidator:
    """RPC keeps the hash out of URLs/access logs; only the hash is sent, never the key."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client = client
        self.settings = settings

    async def validate_hash(self, key_hash: str) -> AuthenticatedKey | None:
        try:
            async with asyncio.timeout(self.settings.customer_auth_timeout_seconds):
                response = await self.client.post(
                    "rpc/systemone_api_key_lookup", json={"p_key_hash": key_hash},
                )
                response.raise_for_status()
                return identity_from_rows(response.json())
        except (httpx.HTTPError, OSError, TimeoutError, ValueError, KeyError, TypeError):
            # Includes upstream 401/403: credential/service failures are not customer 401s.
            raise AuthenticationUnavailable("Authentication temporarily unavailable") from None


class PostgresKeyValidator:
    def __init__(self, pool, settings: Settings):
        self.pool = pool
        self.settings = settings

    async def validate_hash(self, key_hash: str) -> AuthenticatedKey | None:
        try:
            async with asyncio.timeout(self.settings.customer_auth_timeout_seconds):
                async with self.pool.acquire(
                    timeout=self.settings.customer_auth_timeout_seconds
                ) as connection:
                    rows = await connection.fetch(
                        LOOKUP_SQL, key_hash, timeout=self.settings.customer_auth_query_seconds
                    )
            return identity_from_rows(rows)
        except (asyncpg.PostgresError, OSError, TimeoutError, ValueError, KeyError, TypeError):
            # Driver errors can contain DSNs/query parameters. Never propagate or log them.
            raise AuthenticationUnavailable("Authentication temporarily unavailable") from None


@asynccontextmanager
async def customer_key_validator(settings: Settings):
    if not settings.customer_key_database_url.get_secret_value():
        credential = settings.customer_key_supabase_service_key.get_secret_value()
        limits = httpx.Limits(
            max_connections=settings.customer_auth_pool_size,
            max_keepalive_connections=settings.customer_auth_pool_size,
        )
        deadline = httpx.Timeout(
            settings.customer_auth_query_seconds,
            connect=settings.customer_auth_connect_seconds,
            pool=settings.customer_auth_timeout_seconds,
        )
        async with httpx.AsyncClient(
            base_url=settings.customer_key_supabase_url.rstrip("/") + "/rest/v1/",
            headers={"apikey": credential, "Authorization": "Bearer " + credential},
            limits=limits, timeout=deadline, follow_redirects=False, trust_env=False,
        ) as client:
            yield SupabaseKeyValidator(client, settings)
        return
    # min_size=0 makes startup independent of DB availability: customer requests
    # fail closed on an outage, while public/static routes remain available.
    pool = await asyncpg.create_pool(
        dsn=settings.customer_key_database_url.get_secret_value(),
        min_size=0,
        max_size=settings.customer_auth_pool_size,
        timeout=settings.customer_auth_connect_seconds,
        command_timeout=settings.customer_auth_query_seconds,
        statement_cache_size=0,  # Supavisor transaction-pooler compatible.
        ssl=ssl.create_default_context(),  # TLS with certificate/hostname verification.
    )
    try:
        yield PostgresKeyValidator(pool, settings)
    finally:
        try:
            await asyncio.wait_for(pool.close(), timeout=2)
        except Exception:
            # Even cleanup driver failures must not leak credential-bearing error text.
            pool.terminate()
