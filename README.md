# SystemOne API

Production API for the Security-One deterministic structured-classification model. Its public wire contract is compatible with OpenJev's `POST /v1/systemone`: one shared state, any mix of `noul`, `choice`, and `score` questions, and answers returned under the caller's question IDs.

The production deployment serves the verified AutoJev Security V2.3 release as `security-one`:

- frozen Qwen3.8-27B BF16 checkpoint with an exact 255-way AutoJev readout export;
- zero class flips and zero logit drift in the 64-example export gate;
- fixed probability calibration temperature `0.14527332485151376`;
- SGLang selected-token log probabilities, with one-token deterministic answer labels;
- shared-state prefix reuse for parallel questions;
- a 65,536-token branch context and no silent truncation.

Modal endpoint after the paused service is redeployed: `https://superagentai--systemone-api-web.modal.run`

API reference after redeployment: `https://superagentai--systemone-api-web.modal.run/`

## API

```http
POST /v1/systemone
Authorization: Bearer <key>
Content-Type: application/json
```

```bash
curl "$SYSTEMONE_URL/v1/systemone" \
  -H "Authorization: Bearer $SYSTEMONE_API_KEY" \
  -H "Content-Type: application/json" \
  --data @examples/request.json
```

`state` may be a string, object, or array. Every question sees the same state and is evaluated in parallel.

- `noul` is binary and returns the probability of `true` as `noul`.
- `choice` returns the highest-probability option, the full distribution, and normalized-entropy confidence.
- `score` returns the expected zero-based level, a legend, the full distribution, and confidence.

The aliases `security-one-latest`, `systemone`, `systemone-latest`, `openjev`, and `jev-latest` all select the same loaded release. If `model` is omitted, it defaults to `security-one`.

Additional endpoints:

- `GET /models` — public OpenRouter provider document (schema 2.4)
- `GET /v1/models`
- `GET /v1/limits`
- `GET /health` for inference readiness
- `GET /health/live` for process liveness
- `GET /docs`, `/openapi.json`, and `/` for API reference

## Local API development

The API process expects a running SGLang server with the selected-token logprob endpoint enabled.

```bash
uv sync --extra dev
cp .env.example .env
uv run systemone serve
```

Set `SYSTEMONE_MODEL_PATH` to the local tokenizer snapshot and `SYSTEMONE_BACKEND_URL` to SGLang. Local auth is disabled only when `SYSTEMONE_API_KEYS` is empty; the Modal deployment refuses to start without at least one key.

Run the checks with:

```bash
uv run --extra dev pytest
uv run --extra dev ruff check .
```

## Production on Modal

The deployment is pinned to the verified `autojev-security-v2-3-sglang-export-20260925a` artifacts in the private `openjev-rlcd-artifacts-v1` volume. It starts one SGLang server and the API in the same B200 container, so the backend is never exposed publicly.

Create the production secret once:

```bash
modal secret create systemone-production \
  SYSTEMONE_API_KEYS="$(openssl rand -hex 32)"
```

Multiple early-user keys can be supplied as a comma-separated value. Then deploy:

```bash
uv run --extra modal modal deploy deployment/modal_app.py
```

The initial early-access deployment keeps exactly one warm B200 container and caps scaling at one to
bound spend. Raise `max_containers` only after load testing; lower `min_containers` only when cold
starts are acceptable.

Verify the live endpoint, including all three answer types:

```bash
SYSTEMONE_API_KEY="<customer-key>" uv run systemone smoke https://YOUR-ENDPOINT.modal.run
```

## Operational behavior

- API keys are compared in constant time and are never logged.
- State, questions, and prompts are never written to application logs.
- Request bodies, question counts, option counts, per-branch context, total tokens, concurrency, and deadlines are bounded before or during admission.
- Overload, timeout, and backend failures return `503` with `Retry-After: 1`.
- Each response includes `x-systemone-request-id`, `x-systemone-model`, cache diagnostics, and `Server-Timing` without exposing customer data.
- `usage.output_tokens` reports the actual internal warm-up plus one-token decisions. Billing can still price output at zero; the usage record is not falsified.

## Release checklist

1. Run the unit and contract tests.
2. Build the Modal image; its fail-closed source patches must apply exactly once.
3. Smoke-test all three question types against the deployed URL.
4. Run the frozen quality canary before moving customer traffic.
5. Issue one API key per customer so individual keys can be revoked.
6. Put the endpoint behind the production domain/rate limiter before broader access.

## Research results

- [SystemOne v4 multi-objective continuation](research/systemone-v4/RESULTS.md)
- [SystemOne v3 general-reasoning continuation](research/systemone-v3/RESULTS.md)
- [SystemOne v2 general-classifier experiment](research/systemone-v2/RESULTS.md)

The v4 package is the latest research evaluation, not the currently deployed production release.
It contains aggregate results and reproducibility metadata only; training rows, teacher outputs,
model weights, credentials, and customer data are not published.
