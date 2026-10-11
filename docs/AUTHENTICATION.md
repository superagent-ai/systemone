# Hosted organization-key authentication

Release status: operator-approved production setup on 2026-09-28. The service-only lookup RPC
and helper-function permission tightening are applied, and `systemone-customer-auth` is created.
Hosted Modal v5 is deployed and customer/static keys plus immediate revocation are verified.
Measurements, failed attempts, credential limitations, and rollout details are recorded in
[the rollout report](ROLLOUT_20260928.md). Landing docs PR #680 is release-gate verified but
has not been merged/published by this rollout.

## Request behavior

`RequestGuard` authenticates before reading POST/PUT/PATCH bodies or invoking inference:

1. Compare the bearer token with `SYSTEMONE_API_KEYS` and `SYSTEMONE_API_KEYS_SECONDARY`
   in constant time. Existing internal/testing secrets remain valid.
2. Otherwise require `sk_live_` followed by exactly 32 ASCII hex characters. SHA-256 hash the
   exact, case-sensitive token; never send the plaintext key to the database.
3. Execute the parameterized query `SELECT id, organization_id FROM public.api_keys
   WHERE key_hash = $1 LIMIT 2`, using the existing `key_hash` index.
   The production fallback calls the service-only `systemone_api_key_lookup` RPC over HTTPS;
   its SECURITY INVOKER SQL function executes the same lookup. Only the hash is sent in a
   POST body, keeping it out of URL/access logs. The incoming request body is still unread.
   Zero rows means invalid/revoked; duplicate rows or corrupt identity data fail closed with 503.
4. Store an `AuthenticatedKey` in `request.state.authentication`. Organization requests carry
   `source="organization"`, `key_id`, and `organization_id` for future rate limiting/usage
   attribution. Static/development requests have their respective source and no fabricated IDs.
   This context is neither returned nor logged. Billing, organization rate limits, and
   `last_used_at` writes are not part of this release.

There is **no authentication cache**. Every customer-key request queries the authoritative DB.
Landing revokes keys by deleting their `api_keys` rows. The next lookup after a deletion commits
returns 401; requests already authenticated can finish. Created keys work after insertion commits.
Use the writer/primary DB, not a replica with revocation lag. A future cache would delay revocation
by up to its TTL, plus already admitted requests; require measurements and a security decision
before adding one.

Missing/malformed/unknown/revoked keys retain HTTP 401 and
`{"error":{"message":"Missing or invalid API key"}}`, with `WWW-Authenticate: Bearer`.
Connection/query/pool timeouts, database failures, or absent validation at request time return
HTTP 503 and `{"error":{"message":"Authentication temporarily unavailable"}}`, with
`Retry-After: 1`. No inference occurs. Driver exception details are never exposed or logged.
Static keys and public routes continue working during a runtime DB outage.

The exact public paths remain `/`, `/docs`, `/openapi.json`, `/models`, `/health`, and
`/health/live`. Every other path, including nonexistent and future routes, passes through the
guard. Public health checks describe inference/process health, not database health. Use a valid
organization key against `/v1/limits` as the auth-path canary.

## Connection reuse and configuration

One client/pool per FastAPI application lifespan; never a new client per request. TLS verifies
CA certificates and hostname. `min_size=0` defers connections so DB outages do not block static
requests. `statement_cache_size=0` supports Supavisor transaction pooling. Shutdown cleanup is
bounded to two seconds for PostgreSQL. The HTTPS fallback reuses one httpx.AsyncClient with
bounded connection/keepalive limits and timeouts, disallows redirects and environment proxies,
and applies the same one-second total authentication budget.

| Server-only setting | Default | Meaning |
| --- | --- | --- |
| `SYSTEMONE_CUSTOMER_KEY_DATABASE_URL` | empty | Read-only role's PostgreSQL DSN |
| `SYSTEMONE_CUSTOMER_KEY_SUPABASE_URL` | empty | HTTPS project URL, fallback only |
| `SYSTEMONE_CUSTOMER_KEY_SUPABASE_SERVICE_KEY` | empty | Broad server-only credential, fallback only |
| `SYSTEMONE_CUSTOMER_AUTH_POOL_SIZE` | 8 | DB/HTTP connections per API process (1–32) |
| `SYSTEMONE_CUSTOMER_AUTH_TIMEOUT_SECONDS` | 1 | Whole lookup, including pool queueing |
| `SYSTEMONE_CUSTOMER_AUTH_CONNECT_SECONDS` | 1 | Connection establishment deadline |
| `SYSTEMONE_CUSTOMER_AUTH_QUERY_SECONDS` | 0.5 | Individual query/command deadline |
| `SYSTEMONE_ENVIRONMENT` | development | Production requires a complete lookup configuration |

Modal explicitly constructs production settings before launching inference. A missing lookup
DSN and absent/incomplete HTTPS fallback prevent startup even with static keys. A missing Secret prevents a usable
deployment. Other hosting methods must set production mode explicitly. Local development stays
unauthenticated only when both static-key settings and all lookup configuration are empty. Static-only
local development still works. Configuring either lookup requires auth even without static keys.
Tests inject fake validators; they need no GPU or Supabase connection.

## Narrow database credential (approval required)

Use a dedicated LOGIN role with SELECT access to only the three required columns. Supabase
supports custom PostgreSQL roles. Its authenticated-user RLS policy does not authorize this
role, so a database owner must review/apply this once (adjust the DB name if not `postgres`):

```sql
CREATE ROLE systemone_key_reader LOGIN
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
GRANT CONNECT ON DATABASE postgres TO systemone_key_reader;
GRANT USAGE ON SCHEMA public TO systemone_key_reader;
GRANT SELECT (id, organization_id, key_hash)
  ON public.api_keys TO systemone_key_reader;
CREATE POLICY systemone_key_lookup ON public.api_keys
  FOR SELECT TO systemone_key_reader USING (true);
ALTER ROLE systemone_key_reader SET default_transaction_read_only = on;
ALTER ROLE systemone_key_reader SET statement_timeout = '500ms';
```

This is a manual setup recipe, not an executed migration. Set a generated password securely
using psql's interactive `\password systemone_key_reader` or an approved administration channel;
do not put it in committed SQL, logs, or shell history. Do not grant table ownership, BYPASSRLS,
or an `anon`/`PUBLIC` policy. This policy allows this server role to read identity/hash metadata
across organizations, not ordinary clients. Column grants prevent other key-metadata reads and
writes. Read-only defaults are defense-in-depth, not a substitute for grants. Audit inherited
PUBLIC privileges, particularly SECURITY DEFINER functions, and restrictive RLS policies before
claiming complete isolation. Verify lookup access, denied writes, and denied unrelated table
reads. Do not broadly revoke PUBLIC privileges in production without checking other services.

Get connection details for the **primary** DB/Supavisor from Supabase's dashboard. A transaction
pooler DSN typically uses username `systemone_key_reader.<project-ref>` and port `6543`; obtain
the actual host/region, URL-encode credentials, and verify custom-role support/TLS in staging.
A direct connection uses username `systemone_key_reader` if reachable from Modal. Budget
connections across processes/containers and the Supabase tier. Never weaken TLS verification.

### Current production fallback and residual risk

The preferred scoped PostgreSQL setup was not provisioned: Supabase's internal `supabase_admin`
owns the `net` HTTP queue/response tables and schema, and project-level `postgres` cannot revoke
their PUBLIC grants or assume that internal role. A direct login role would inherit those
permissions. Available Management API access could not issue a custom scoped JWT without
access to the signing secret; no project-wide signing-key rotation was performed.

Production therefore uses the original requirement's permitted service-role fallback, stored
only in the server-side Modal Secret. **This credential bypasses RLS and has broad project
access, including write capability. The RPC is read-only; the credential itself is not.**
It is never returned to clients, printed, logged, checked in, or stored in `NEXT_PUBLIC_*`.
The SGLang subprocess explicitly excludes front-door/customer-validation credentials from
its environment. The setup tool keeps credentials in memory and refuses secret overwrites.
No customer API keys are synchronized into Modal.

The three public organization helper functions no longer grant EXECUTE to PUBLIC; explicit
anon/authenticated/service_role permissions are preserved. The new lookup RPC uses
SECURITY INVOKER, an empty search_path, and EXECUTE only for service_role (plus its owner).
Unknown/deleted keys yield an empty result, not an upstream authentication error. Supabase
401/403 responses indicate a service-credential failure and become customer-facing 503.
Managed HTTP-queue PUBLIC grants remain unchanged and require Supabase-admin assistance for
direct-DB isolation. Prefer switching to the scoped role after that is resolved. Re-audit
grants on extension upgrades; keep the broad credential's access and rotation under review.

References: [Supabase roles](https://supabase.com/docs/guides/database/postgres/roles),
[RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), and
[asyncpg pooling/TLS/timeouts](https://magicstack.github.io/asyncpg/current/api/index.html).

## Modal Secret and coordinated rollout (approval required)

1. Run tests. Prefer a reviewed read-only DB role when inherited privileges can be isolated.
   If using the documented fallback, apply the service-only RPC and verify its grants/index.
2. After approval, create the server-side Modal Secret `systemone-customer-auth`, containing
   either `SYSTEMONE_CUSTOMER_KEY_DATABASE_URL` or both fallback settings from the table above. Optionally include
   the four pool/timeout settings above. Use an approved secret UI or protected secret-file
   workflow, never checked-in credentials. Keep `systemone-production` (`SYSTEMONE_API_KEYS`)
   and `systemone-testing-key` (`SYSTEMONE_API_KEYS_SECONDARY`) unchanged. Do not synchronize
   customer keys into them.
3. Obtain deployment approval, then deploy `deployment/modal_app.py` through the normal Modal
   workflow. Its new secret reference and asyncpg dependency are declared. Rollback requires
   restoring the previous code; removing the new secret alone makes this release fail closed.
   The previous release will not accept organization keys.
4. Smoke-test customer/static keys, missing/malformed/unknown keys, public routes, and immediate
   deletion revocation. Test a controlled DB outage in staging (customer 503; static works),
   not by disrupting the shared production DB. Use harmless payloads.
5. Benchmark lookup-only requests directly on Modal and inference requests on both Modal and
   `https://api.superagent.sh` at realistic concurrency; inspect p50/p95 and errors.
   Then release landing's `content/docs/models-api.md` and `public/llms.txt`
   update together. Remove its existing claim that organization keys do not work only after
   verifying hosted support. The existing direct `/v1/systemone` rewrite stays unchanged;
   there is no Next.js authentication hop.

Unit tests do not provision or deploy. The separate setup, verification and deployment commands
are operator-only and were authorized for this rollout. Keep those scripts out of normal CI.

## Measuring lookup and end-to-end latency

`Server-Timing` adds `auth;dur=<ms>` for total guard authentication and
`auth_lookup;dur=<ms>` for the lookup critical path (pool wait, connection establishment if
needed, network, query, release). It is not just PostgreSQL execution time. Static/public
requests have zero lookup duration. `inference` measures the whole evaluation call including
admission wait; existing `prepare`, `prefill`, and `branches` timings remain. Access logs add
`auth_ms`, `auth_lookup_ms`, and `inference_ms` without keys, hashes, IDs, exception text, or
bodies. Log known route templates rather than arbitrary URLs; the CLI disables raw Uvicorn
access logs. Audit platform/proxy logging separately. Avoid per-key metric labels.

Set `SYSTEMONE_API_KEY` securely in the benchmark environment. The command has no plaintext
`--api-key` option and reports aggregate timings/status counts only. After approval/staging:

```bash
# Authenticated GET: measures lookup path without inference.
uv run systemone benchmark-auth https://YOUR-ENDPOINT.modal.run \
  --mode lookup --requests 1000 --concurrency 8 --warmup 20
# Same auth plus a fixed, small classification request.
uv run systemone benchmark-auth https://YOUR-ENDPOINT.modal.run \
  --mode inference --requests 1000 --concurrency 8 --warmup 20
```

Output includes nearest-rank p50/p95 milliseconds, metric sample counts, HTTP/transport errors,
and transport exception class counts (never exception messages),
and excluded warmups. End-to-end timing includes all measured attempts; server timings include
only successful responses, so inspect error counts too. Missing headers produce null values
and zero samples, never fabricated zero latency. Repeat with a static-key baseline at concurrency
1, 8, and expected production peak. Compare both URLs in **inference** mode with fixed payload,
region, deployment, and pool settings. Landing currently forwards `/v1/systemone`, not
`/v1/limits`; use the direct Modal URL for lookup-only mode without adding a new routing hop.
Measure cold-connection behavior separately without warmup. Use representative
sanitized payload sizes for fuller inference benchmarks. Inference mode consumes GPU work;
run in staging or with explicit production approval.

Live results are in [ROLLOUT_20260928.md](ROLLOUT_20260928.md): authoritative lookups add
roughly 125–129 ms median on this deployment. Lookup-only concurrency 8 showed p95 370 ms
among successful requests and one fail-closed 503/100 attempts; public inference concurrency 4
was 100/100 successful at end-to-end p50 428 ms/p95 514 ms. These small warm benchmarks
are not a production SLA; error counts and the wider tail matter. No cache was added.
Fake-validator/transport tests alone are not evidence for production lookup latency.
