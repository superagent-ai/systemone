import asyncio
import hashlib
import logging
import ssl
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import asyncpg
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from test_api import FakeService, payload

from systemone_api.api import RequestGuard, create_app
from systemone_api.auth import (
    LOOKUP_SQL,
    AuthenticatedKey,
    AuthenticationUnavailable,
    PostgresKeyValidator,
    customer_key_validator,
)
from systemone_api.config import Settings

KEY = "sk_live_" + "0123456789abcdef" * 2
KEY_HASH = hashlib.sha256(KEY.encode()).hexdigest()
IDENTITY = AuthenticatedKey(
    source="organization",
    key_id="12345678-1234-1234-1234-123456789abc",
    organization_id="87654321-4321-4321-4321-cba987654321",
)


class FakeValidator:
    def __init__(self):
        self.rows = {KEY_HASH: IDENTITY}
        self.calls = []
        self.error = None
        self.delay = 0

    async def validate_hash(self, key_hash):
        self.calls.append(key_hash)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.rows.get(key_hash)


def settings(**overrides):
    values = dict(
        _env_file=None,
        environment="production",
        customer_key_database_url="postgresql://unused.test/unused",
        api_keys="internal-key",
        api_keys_secondary="testing-key",
        model_path="unused",
    )
    values.update(overrides)
    return Settings(**values)


def api_client(validator, **overrides):
    return TestClient(
        create_app(settings(**overrides), service=FakeService(), key_validator=validator)
    )


def bearer(key=KEY):
    return {"Authorization": f"Bearer {key}"}


def test_valid_customer_key_carries_identity_without_exposing_it(caplog):
    validator = FakeValidator()
    app = create_app(settings(), service=FakeService(), key_validator=validator)

    @app.get("/test-context")
    async def context(request: Request):
        assert request.state.authentication == IDENTITY
        return {"ok": True}

    with caplog.at_level(logging.INFO), TestClient(app) as api:
        context_response = api.get("/test-context", headers=bearer())
        response = api.post("/v1/systemone", json=payload(), headers=bearer())
    assert context_response.status_code == response.status_code == 200
    assert validator.calls == [KEY_HASH, KEY_HASH]
    timing = response.headers["server-timing"]
    for metric in (
        "auth;dur=", "auth_lookup;dur=", "inference;dur=", "prepare;dur=",
        "prefill;dur=", "branches;dur=",
    ):
        assert metric in timing
    serialized = response.text + str(response.headers) + caplog.text
    for secret in (KEY, KEY_HASH, IDENTITY.key_id, IDENTITY.organization_id, "Suspicious input"):
        assert secret not in serialized
    assert '"auth_ms":' in caplog.text and '"auth_lookup_ms":' in caplog.text
    assert '"inference_ms":' in caplog.text


def test_arbitrary_paths_and_queries_are_not_logged(caplog):
    with caplog.at_level(logging.INFO, logger="systemone.api"), api_client(FakeValidator()) as api:
        assert api.get("/" + KEY + "?body=content-secret").status_code == 401
    logs = "\n".join(record.message for record in caplog.records if record.name == "systemone.api")
    assert KEY not in logs and "content-secret" not in logs
    assert '"path":"<guarded>"' in logs


@pytest.mark.parametrize("key", ["sk_live_" + "0" * 32, "sk_live_" + "F" * 32])
def test_unknown_well_formed_key_is_401(key):
    validator = FakeValidator()
    with api_client(validator) as api:
        response = api.post("/v1/systemone", content=b"not json", headers=bearer(key))
    assert response.status_code == 401
    assert response.json() == {"error": {"message": "Missing or invalid API key"}}
    assert response.headers["www-authenticate"] == "Bearer"
    assert validator.calls == [hashlib.sha256(key.encode()).hexdigest()]


@pytest.mark.parametrize("authorization", [
    None, "", "Basic " + KEY, "Bearer", "Bearer ", "Bearer wrong-key",
    "Bearer sk_live_" + "a" * 31, "Bearer sk_live_" + "a" * 33,
    "Bearer sk_live_" + "g" * 32, "Bearer " + KEY + " ", "Bearer  " + KEY,
])
def test_missing_or_malformed_keys_do_not_lookup(authorization):
    validator = FakeValidator()
    headers = {} if authorization is None else {"Authorization": authorization}
    with api_client(validator) as api:
        response = api.post("/v1/systemone", content=b"not json", headers=headers)
    assert response.status_code == 401
    assert validator.calls == []


def test_duplicate_authorization_headers_are_rejected():
    validator = FakeValidator()
    with api_client(validator) as api:
        response = api.get("/v1/limits", headers=[
            ("Authorization", "Bearer " + KEY), ("Authorization", "Bearer internal-key"),
        ])
    assert response.status_code == 401
    assert validator.calls == []


def test_creation_and_revocation_are_visible_on_next_request():
    validator = FakeValidator()
    validator.rows.clear()
    with api_client(validator) as api:
        assert api.get("/v1/limits", headers=bearer()).status_code == 401
        validator.rows[KEY_HASH] = IDENTITY
        assert api.get("/v1/limits", headers=bearer()).status_code == 200
        del validator.rows[KEY_HASH]
        assert api.get("/v1/limits", headers=bearer()).status_code == 401
    assert validator.calls == [KEY_HASH] * 3


@pytest.mark.parametrize("key", ["internal-key", "testing-key", KEY])
def test_static_keys_work_during_database_outage_without_lookup(key):
    validator = FakeValidator()
    validator.error = RuntimeError("database unavailable")
    with api_client(validator, api_keys="internal-key," + KEY) as api:
        response = api.post("/v1/systemone", json=payload(), headers=bearer(key))
    assert response.status_code == 200
    assert "auth_lookup;dur=0.00" in response.headers["server-timing"]
    assert validator.calls == []


@pytest.mark.parametrize("timeout", [False, True])
def test_lookup_outage_is_sanitized_503_not_401(timeout, caplog):
    validator = FakeValidator()
    if timeout:
        validator.delay = 1
    else:
        validator.error = RuntimeError(f"DSN password and key: {KEY}")
    with caplog.at_level(logging.INFO), api_client(
        validator, customer_auth_timeout_seconds=0.01
    ) as api:
        response = api.post("/v1/systemone", content=b"body-secret", headers=bearer())
    assert response.status_code == 503
    assert response.json() == {"error": {"message": "Authentication temporarily unavailable"}}
    assert response.headers["retry-after"] == "1"
    assert "www-authenticate" not in response.headers
    assert "auth_lookup;dur=" in response.headers["server-timing"]
    assert KEY not in response.text + caplog.text
    assert "body-secret" not in caplog.text


@pytest.mark.parametrize("static_keys", ["", "internal-key"])
def test_missing_production_configuration_fails_startup_even_with_static_keys(static_keys):
    with pytest.raises(RuntimeError, match="SYSTEMONE_CUSTOMER_KEY_DATABASE_URL"):
        create_app(
            settings(customer_key_database_url="", api_keys=static_keys),
            service=FakeService(), key_validator=FakeValidator(),
        )


def test_local_development_without_keys_remains_unauthenticated():
    with api_client(
        None, environment="development", api_keys="", api_keys_secondary="",
        customer_key_database_url="",
    ) as api:
        assert api.post("/v1/systemone", json=payload()).status_code == 200


def test_local_static_only_and_missing_customer_validator():
    with api_client(None, environment="development", customer_key_database_url="") as api:
        assert api.get("/v1/limits").status_code == 401
        assert api.get("/v1/limits", headers=bearer("internal-key")).status_code == 200
        assert api.get("/v1/limits", headers=bearer()).status_code == 503


def test_customer_only_configuration_requires_auth():
    validator = FakeValidator()
    with api_client(validator, api_keys="", api_keys_secondary="") as api:
        assert api.get("/v1/limits").status_code == 401
        assert api.get("/v1/limits", headers=bearer()).status_code == 200


@pytest.mark.parametrize("path", sorted(RequestGuard.PUBLIC_PATHS))
def test_all_existing_public_routes_remain_public_during_lookup_outage(path):
    validator = FakeValidator()
    validator.error = RuntimeError("unavailable")
    with api_client(validator) as api:
        assert api.get(path, headers=bearer("malformed")).status_code == 200
    assert validator.calls == []


@pytest.mark.parametrize("path", ["/v1/models", "/v1/limits", "/unknown", "/docs/"])
def test_all_other_routes_are_guarded(path):
    with api_client(FakeValidator()) as api:
        assert api.get(path).status_code == 401


@pytest.mark.parametrize("outage", [False, True])
async def test_guard_rejects_before_reading_body_or_invoking_downstream(outage):
    validator = FakeValidator()
    validator.error = RuntimeError("unavailable") if outage else None
    downstream = AsyncMock()
    receive = AsyncMock(side_effect=AssertionError("request body must not be read"))
    messages = []

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http", "method": "POST", "path": "/v1/systemone",
        "headers": [(b"authorization", ("Bearer " + KEY).encode())] if outage else [],
        "app": SimpleNamespace(state=SimpleNamespace(customer_key_validator=validator)),
    }
    await RequestGuard(downstream, settings())(scope, receive, send)
    assert messages[0]["status"] == (503 if outage else 401)
    receive.assert_not_called()
    downstream.assert_not_called()


async def test_non_ascii_key_is_invalid_not_server_error():
    validator = FakeValidator()
    messages = []

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http", "method": "POST", "path": "/v1/systemone",
        "headers": [(b"authorization", b"Bearer sk_live_\xff")],
        "app": SimpleNamespace(state=SimpleNamespace(customer_key_validator=validator)),
    }
    await RequestGuard(AsyncMock(), settings())(scope, AsyncMock(), send)
    assert messages[0]["status"] == 401
    assert validator.calls == []


class FakePool:
    def __init__(self, connection):
        self.connection = connection
        self.timeouts = []
        self.close = AsyncMock()
        self.terminate = Mock()

    @asynccontextmanager
    async def acquire(self, *, timeout):  # noqa: ASYNC109 - Mirrors asyncpg's API.
        self.timeouts.append(timeout)
        yield self.connection


async def test_postgres_lookup_is_parameterized_read_only_and_not_cached():
    row = {"id": IDENTITY.key_id, "organization_id": IDENTITY.organization_id}
    connection = SimpleNamespace(fetch=AsyncMock(side_effect=[[row], []]))
    pool = FakePool(connection)
    validator = PostgresKeyValidator(pool, settings())
    assert await validator.validate_hash(KEY_HASH) == IDENTITY
    assert await validator.validate_hash(KEY_HASH) is None
    assert pool.timeouts == [1, 1]
    for call in connection.fetch.call_args_list:
        assert call.args == (LOOKUP_SQL, KEY_HASH)
        assert call.kwargs == {"timeout": 0.5}


@pytest.mark.parametrize("rows", [
    [{"id": IDENTITY.key_id, "organization_id": IDENTITY.organization_id}] * 2,
    [{"id": "bad", "organization_id": IDENTITY.organization_id}],
    [{"id": IDENTITY.key_id}],
])
async def test_ambiguous_or_corrupt_lookup_fails_closed(rows):
    validator = PostgresKeyValidator(FakePool(SimpleNamespace(fetch=AsyncMock(return_value=rows))),
                                    settings())
    with pytest.raises(AuthenticationUnavailable):
        await validator.validate_hash(KEY_HASH)


@pytest.mark.parametrize("error", [asyncpg.PostgresError(KEY), OSError(KEY), TimeoutError(KEY)])
async def test_driver_errors_are_sanitized(error):
    connection = SimpleNamespace(fetch=AsyncMock(side_effect=error))
    with pytest.raises(AuthenticationUnavailable) as exc:
        await PostgresKeyValidator(FakePool(connection), settings()).validate_hash(KEY_HASH)
    assert KEY not in str(exc.value)


async def test_one_tls_pool_reused_for_entire_app_lifespan(monkeypatch):
    pool = FakePool(SimpleNamespace(fetch=AsyncMock(return_value=[])))
    factory = AsyncMock(return_value=pool)
    monkeypatch.setattr(asyncpg, "create_pool", factory)
    app = create_app(settings(), service=FakeService())
    async with app.router.lifespan_context(app):
        validator = app.state.customer_key_validator
        assert await validator.validate_hash(KEY_HASH) is None
        assert await validator.validate_hash(KEY_HASH) is None
        assert app.state.customer_key_validator is validator
    factory.assert_awaited_once()
    options = factory.call_args.kwargs
    assert options["min_size"] == 0 and options["max_size"] == 8
    assert options["statement_cache_size"] == 0
    assert options["timeout"] == 1 and options["command_timeout"] == 0.5
    assert options["ssl"].check_hostname is True
    assert options["ssl"].verify_mode == ssl.CERT_REQUIRED
    pool.close.assert_awaited_once()


def test_configuration_does_not_serialize_credentials():
    configured = settings(customer_key_database_url="postgresql://user:password-secret@host/db")
    assert "password-secret" not in configured.model_dump_json()
    assert "password-secret" not in repr(configured)


@pytest.mark.parametrize("error", [TimeoutError(), OSError("password-secret")])
async def test_pool_shutdown_is_bounded_and_sanitized(monkeypatch, error):
    pool = FakePool(SimpleNamespace(fetch=AsyncMock()))
    pool.close.side_effect = error
    monkeypatch.setattr(asyncpg, "create_pool", AsyncMock(return_value=pool))
    async with customer_key_validator(settings()):
        pass
    pool.terminate.assert_called_once()


@pytest.mark.parametrize("identity", [
    AuthenticatedKey(source="static"),
    AuthenticatedKey(source="organization", key_id="id"),
])
def test_incomplete_validator_identity_does_not_authenticate(identity):
    validator = FakeValidator()
    validator.rows[KEY_HASH] = identity
    with api_client(validator) as api:
        assert api.get("/v1/limits", headers=bearer()).status_code == 503
