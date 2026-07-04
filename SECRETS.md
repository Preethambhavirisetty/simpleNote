# Secrets & Secure Deployment

All application secrets are loaded from environment variables (via `require_env`) and are
**never** committed. This document identifies the affected files, how secrets are loaded,
and which credentials must be regenerated before production.

## Current status (verified)

- **No secrets are tracked in git.** No `*.pem` / `*.key`, no `.env` files, and none of the
  known secret values appear in any tracked file.
- **TLS certificates** live under `certs/` (git-ignored) and are mounted read-only by
  `podman-compose.yml`. They are not in version control or git history.
- **No hardcoded secrets in code.** Every secret is `require_env("NAME")` with *no* default,
  so a missing secret fails fast at startup. The only defaulted env vars are non-secret
  tuning values (timeouts, token budgets, queue names, model names, feature flags).
- **`.gitignore`** blocks `.env`, `.env.*`, `certs/`, `*.pem`, `*.key`, `*.crt`. Templates
  named `*.env.example` remain tracked so required keys are discoverable.

## Affected files

| File | Contains | Tracked? |
|------|----------|----------|
| `.env` (root) | `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `GRAFANA_ADMIN_*` | no (git-ignored) |
| `backend/.env` | `SECRET_KEY`, `AGENT_API_KEY`, DB/broker URLs | no (git-ignored) |
| `notelite_agent/.env` | `SECRET_KEY`, `AGENT_API_KEY`, `LLM_API_KEY`, `EMBEDDING_API_KEY`, DB/broker URLs | no (git-ignored) |
| `frontend/.env` | routing only (no secrets — `VITE_AGENT_API_KEY` removed) | no (git-ignored) |
| `certs/notelite.org/privkey.pem`, `fullchain.pem` | TLS key + chain | no (git-ignored, mounted) |

## How secrets are loaded (secure loading)

| Secret | Consumed by | Source |
|--------|-------------|--------|
| `SECRET_KEY` (JWT signing) | backend, agent — `require_env("SECRET_KEY")` | service `.env` |
| `AGENT_API_KEY` (internal service auth) | backend, agent — `require_env("AGENT_API_KEY")` | service `.env` |
| `POSTGRES_PASSWORD` / `POSTGRES_DB_URL` | compose, backend, agent | root `.env` / service `.env` |
| `REDIS_PASSWORD` / broker + result-backend URLs | compose, backend, agent | root `.env` / service `.env` |
| `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` | compose (Grafana) | root `.env` |
| `LLM_API_KEY` | agent — `require_env("LLM_API_KEY")` | `notelite_agent/.env` |
| `EMBEDDING_API_KEY` (optional) | agent | `notelite_agent/.env` |
| TLS `privkey.pem` / `fullchain.pem` | frontend nginx (read-only mount) | `certs/` (outside git) |

## Must be regenerated before production (assume compromised)

Any secret value that has existed in a working `.env`/`certs` during development should be
treated as compromised for production and rotated:

1. **`AGENT_API_KEY`** — was previously bundled into the browser as `VITE_AGENT_API_KEY`.
   Regenerate and set the **same** new value in `backend/.env` and `notelite_agent/.env`.
2. **`SECRET_KEY`** (JWT) — rotate in backend and agent. Rotating invalidates all existing
   sessions/tokens (expected).
3. **`POSTGRES_PASSWORD`** — rotate and update `POSTGRES_DB_URL` in every service.
4. **`REDIS_PASSWORD`** — rotate and update the broker / result-backend URLs.
5. **`GRAFANA_ADMIN_PASSWORD`** — set a strong value (no more `admin`/`admin`).
6. **TLS private key** — reissue the `notelite.org` certificate and treat the old key as
   compromised.
7. **`LLM_API_KEY` / `EMBEDDING_API_KEY`** — rotate if the provider keys were shared.

## Rotation status (2026-07-03)

Items 1–5 were regenerated **locally in the `.env` files** (new random values via
`openssl rand`; `AGENT_API_KEY` kept identical across backend/agent, the two
`SECRET_KEY`s made independent — the agent never verifies backend JWTs). Not yet applied
to any running environment. Still pending, outside this repo's control:

- **TLS certificate reissue** (item 6) — external CA / operator action.
- **`LLM_API_KEY` / `EMBEDDING_API_KEY` / `RERANKER_API_KEY`** (item 7) — provider-side
  (RunPod) credentials; rotating only the local value would break inference/embedding
  auth. Rotate at the provider, then update `notelite_agent/.env`.

### Applying the rotation to an already-running stack

The previous values are preserved in git-ignored `*.env.pre-rotation.bak` files —
**delete them once the steps below are done.** Fresh environments need none of this.

1. **Postgres:** the container only reads `POSTGRES_PASSWORD` when initialising an empty
   volume. For an existing volume, log in with the *old* password and run
   `ALTER USER postgres WITH PASSWORD '<new value from .env>';`
2. **Redis:** `--requirepass` is read at start — `podman-compose up -d redis` (recreate)
   picks up the new password.
3. **Grafana:** the admin password env var only applies on first run. For an existing
   volume: `grafana-cli admin reset-admin-password <new value>` inside the container.
4. **Services:** recreate `backend`, `agent`, `agent-celery` so they
   load the new `SECRET_KEY` / `AGENT_API_KEY` / URLs together (the internal key must
   change on both sides in one step). All user sessions are invalidated (expected).
5. Delete the `*.env.pre-rotation.bak` files.

## Provisioning

- **Dev:** copy `*.env.example` → `.env` for each service and fill in values.
- **Production:** inject secrets via a secrets manager or mounted files; never bake them into
  images or commit them. Mount TLS certs read-only from outside git (as compose already does).

### AWS Secrets Manager (production)

Both `backend` and `agent` can load their secrets from AWS Secrets Manager at startup. Set:

    AWS_SECRETS_MANAGER_SECRET_ID=<secret name or ARN>
    AWS_REGION=<aws-region>            # or AWS_DEFAULT_REGION

The referenced secret's value must be a JSON object of `ENV_KEY: value` pairs, e.g.:

    { "SECRET_KEY": "...", "AGENT_API_KEY": "...", "POSTGRES_DB_URL": "...", "LLM_API_KEY": "..." }

On startup the app fetches the secret and loads each pair into the environment before
config is read (`app/core/config.py` → `_load_aws_secrets`). Existing environment variables
take precedence, so anything set by the orchestrator (or a local `.env`) is never overwritten.
When `AWS_SECRETS_MANAGER_SECRET_ID` is unset the loader is a no-op and the app uses plain
environment variables / `.env` as before. AWS credentials/permissions are supplied by the
runtime (IAM task role, instance profile, or the standard AWS SDK credential chain).
