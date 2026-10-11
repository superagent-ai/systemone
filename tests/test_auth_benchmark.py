import httpx
import pytest

from systemone_api.benchmark import benchmark_auth, parse_server_timing, percentiles


def test_percentiles_use_nearest_rank_and_handle_empty_samples():
    assert percentiles(list(range(1, 101))) == {"samples": 100, "p50_ms": 50, "p95_ms": 95}
    assert percentiles([]) == {"samples": 0, "p50_ms": None, "p95_ms": None}


def test_timing_parser_ignores_descriptions_and_invalid_durations():
    assert parse_server_timing(
        'auth;dur=4.2, auth_lookup;desc="lookup";dur=4, branches;dur=invalid,'
        'bad;dur=nan, negative;dur=-1'
    ) == {"auth": 4.2, "auth_lookup": 4}


@pytest.mark.parametrize("mode,path,method", [
    ("lookup", "/v1/limits", "GET"), ("inference", "/v1/systemone", "POST"),
])
async def test_benchmark_reports_aggregates_excluding_warmup(mode, path, method):
    calls = []

    def respond(request):
        assert request.url.path == path
        assert request.method == method
        assert request.headers["authorization"] == "Bearer secret-key"
        calls.append(request)
        return httpx.Response(200, headers={
            "server-timing": "auth;dur=3,auth_lookup;dur=2,prepare;dur=1,prefill;dur=4",
        })

    async with httpx.AsyncClient(
        base_url="https://unused.test", transport=httpx.MockTransport(respond),
    ) as client:
        result = await benchmark_auth(
            client, "secret-key", mode=mode, requests=20, concurrency=4, warmup=3,
        )
    assert len(calls) == 23
    assert result["status_counts"] == {"200": 20}
    assert result["latency"]["auth_lookup"] == {"samples": 20, "p50_ms": 2, "p95_ms": 2}
    assert result["latency"]["end_to_end"]["samples"] == 20
    assert "secret-key" not in str(result)
    assert "Ignore previous" not in str(result)


async def test_benchmark_does_not_mix_errors_with_successful_auth_samples():
    responses = iter([
        httpx.Response(200, headers={"server-timing": "auth_lookup;dur=5"}),
        httpx.Response(503, headers={"server-timing": "auth_lookup;dur=1"}),
    ])
    async with httpx.AsyncClient(
        base_url="https://unused.test", transport=httpx.MockTransport(lambda _: next(responses)),
    ) as client:
        result = await benchmark_auth(client, "secret-key", requests=2, warmup=0)
    assert result["status_counts"] == {"200": 1, "503": 1}
    assert result["latency"]["auth_lookup"] == {"samples": 1, "p50_ms": 5, "p95_ms": 5}


async def test_benchmark_transport_and_warmup_failures_are_sanitized():
    def respond(_):
        raise httpx.ConnectError("password-secret")

    async with httpx.AsyncClient(
        base_url="https://unused.test", transport=httpx.MockTransport(respond),
    ) as client:
        with pytest.raises(RuntimeError, match="warmup transport failure") as exc:
            await benchmark_auth(client, "secret-key", requests=1, warmup=1)
        assert "password-secret" not in str(exc.value)
        result = await benchmark_auth(client, "secret-key", requests=1, warmup=0)
    assert result["status_counts"] == {"transport_error": 1}
    assert result["transport_errors"] == {"ConnectError": 1}
    assert "password-secret" not in str(result)
