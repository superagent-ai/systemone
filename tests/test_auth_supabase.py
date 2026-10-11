import json

import httpx
import pytest
from test_api import FakeService
from test_auth import IDENTITY, KEY, KEY_HASH, settings

from systemone_api.api import create_app
from systemone_api.auth import AuthenticationUnavailable, SupabaseKeyValidator


def rest_settings(**overrides):
    return settings(customer_key_database_url="", customer_key_supabase_url="https://unused.test",
                    customer_key_supabase_service_key="server-secret", **overrides)


async def test_supabase_rpc_has_no_plaintext_key_and_returns_identity():
    def handle(request):
        assert request.url == "https://unused.test/rest/v1/rpc/systemone_api_key_lookup"
        assert json.loads(request.content) == {"p_key_hash": KEY_HASH}
        assert KEY not in str(request.url) + request.content.decode()
        return httpx.Response(200, json=[{
            "id": IDENTITY.key_id, "organization_id": IDENTITY.organization_id,
        }])

    async with httpx.AsyncClient(
        base_url="https://unused.test/rest/v1/", transport=httpx.MockTransport(handle),
    ) as client:
        validator = SupabaseKeyValidator(client, rest_settings())
        assert await validator.validate_hash(KEY_HASH) == IDENTITY


async def test_rest_lookups_are_not_cached_and_deleted_keys_are_invalid():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=[{
            "id": IDENTITY.key_id, "organization_id": IDENTITY.organization_id,
        }] if len(calls) == 1 else [])

    async with httpx.AsyncClient(
        base_url="https://unused.test/rest/v1/", transport=httpx.MockTransport(handle),
    ) as client:
        validator = SupabaseKeyValidator(client, rest_settings())
        assert await validator.validate_hash(KEY_HASH) == IDENTITY
        assert await validator.validate_hash(KEY_HASH) is None
    assert len(calls) == 2


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
async def test_upstream_failures_are_service_errors_not_invalid_keys(status):
    async with httpx.AsyncClient(
        base_url="https://unused.test/rest/v1/",
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="server-secret")),
    ) as client:
        with pytest.raises(AuthenticationUnavailable) as exc:
            await SupabaseKeyValidator(client, rest_settings()).validate_hash(KEY_HASH)
    assert "server-secret" not in str(exc.value)


@pytest.mark.parametrize("data", [{}, [None], [{"id": "bad"}], [{}, {}]])
async def test_bad_rpc_contract_fails_closed(data):
    async with httpx.AsyncClient(
        base_url="https://unused.test/rest/v1/",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data)),
    ) as client:
        with pytest.raises(AuthenticationUnavailable):
            await SupabaseKeyValidator(client, rest_settings()).validate_hash(KEY_HASH)


async def test_transport_timeout_is_sanitized():
    def handle(_):
        raise httpx.ReadTimeout("server-secret")

    async with httpx.AsyncClient(
        base_url="https://unused.test/rest/v1/", transport=httpx.MockTransport(handle),
    ) as client:
        with pytest.raises(AuthenticationUnavailable) as exc:
            await SupabaseKeyValidator(client, rest_settings()).validate_hash(KEY_HASH)
    assert "server-secret" not in str(exc.value)


async def test_one_http_client_reused_across_app_lifespan(monkeypatch):
    clients = []
    real_factory = httpx.AsyncClient

    def factory(**kwargs):
        assert kwargs["headers"]["apikey"] == "server-secret"
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        assert kwargs["timeout"].read == 0.5 and kwargs["timeout"].pool == 1
        kwargs["transport"] = httpx.MockTransport(lambda _: httpx.Response(200, json=[]))
        client = real_factory(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    app = create_app(rest_settings(), service=FakeService())
    async with app.router.lifespan_context(app):
        validator = app.state.customer_key_validator
        assert await validator.validate_hash(KEY_HASH) is None
        assert await validator.validate_hash(KEY_HASH) is None
    assert len(clients) == 1 and clients[0].is_closed


@pytest.mark.parametrize("url,key", [
    ("https://unused.test", ""), ("", "server-secret"), ("http://unused.test", "server-secret"),
])
def test_incomplete_or_insecure_rest_config_rejected(url, key):
    configured = settings(customer_key_database_url="", customer_key_supabase_url=url,
                          customer_key_supabase_service_key=key)
    with pytest.raises(RuntimeError):
        create_app(configured, service=FakeService())


def test_service_key_is_masked_in_settings():
    assert "server-secret" not in rest_settings().model_dump_json()
    assert "server-secret" not in repr(rest_settings())
