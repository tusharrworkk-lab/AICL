# ACIL — Agent Context Intelligence Layer

ACIL is an agent-agnostic execution-memory and context-intelligence layer for
coding agents and other tool-using AI systems. It records observable execution
events, groups recurring failures, evaluates recovery strategies, and exposes
validated operational knowledge to later agent runs.

ACIL is not another autonomous agent. It does not infer private model reasoning,
execute arbitrary commands from traces, or automatically trust LLM suggestions.
It sits alongside agents such as Codex and Claude Code and operates on observable
events, explicit evaluation evidence, and tenant-scoped authorization.

## Research hypothesis

> Validated operational knowledge extracted from one agent's execution history
> can improve the reliability of later executions, including executions by a
> different compatible agent.

ACIL is designed to make that hypothesis measurable while also tracking negative
transfer: a strategy that helps one task but harms another must not become a
universal rule.

## What is implemented

- FastAPI modular monolith
- SQLAlchemy 2.0 models and Alembic migrations
- PostgreSQL support with a SQLite development mode
- Tenant-scoped API-key authentication
- Projects, agents, sessions, and append-only execution events
- Batched and idempotent event ingestion
- Generic, Codex, and Claude Code observable-event adapters
- Out-of-order trace reconstruction
- Secret-shaped attribute redaction and payload limits
- Safe API-target normalization and fingerprinting
- Deterministic failure fingerprints and recurrence tracking
- Opt-in, de-identified cross-tenant recurrence aggregation
- Deterministic evaluation definitions and runs
- Versioned strategy candidates and activation lifecycle
- Context compilation for active applicable strategies
- Pre-execution action-risk checks
- MCP server for agent integrations
- Amazon Bedrock judge adapters for Kimi K3 and Converse-compatible models
- Asynchronous Bedrock judge queue with persisted run state
- Optional isolated Docker evaluation runner
- Tenant-private judge findings and negative-case analysis
- Minimal authenticated operations console
- Automated tests that do not require paid model credentials

Current database migration head:

```text
0009_api_target_fingerprints
```

## Core learning loop

```text
AGENT EXECUTION
      ↓
OBSERVABLE EVENT COLLECTION
      ↓
CANONICAL NORMALIZATION
      ↓
FAILURE FINGERPRINTING
      ↓
RECURRENCE DISCOVERY
      ↓
EVALUATION DEFINITION
      ↓
CANDIDATE RECOVERY STRATEGY
      ↓
AUTHORIZED RECOVERY EXECUTION
      ↓
DETERMINISTIC VALIDATION + OPTIONAL LLM ANALYSIS
      ↓
EXPLICIT ACTIVATION
      ↓
ACTIVE OPERATIONAL KNOWLEDGE
      ↓
FUTURE AGENT CONTEXT / PREFLIGHT RISK
```

Bedrock analysis is never sufficient by itself to validate or activate a
strategy. A strategy requires successful observable execution evidence and a
deterministic evaluation pass before it can become validated knowledge.

## Architecture

ACIL is intentionally a modular monolith:

```text
┌─────────────────────────────────────────────────────────┐
│                    FastAPI application                  │
├──────────────┬──────────────┬──────────────┬────────────┤
│ Tenant/Auth  │ Trace Engine │ Failure Intel│ Evaluations│
├──────────────┼──────────────┼──────────────┼────────────┤
│ Strategies   │ Context      │ Risk Engine  │ MCP Server │
├──────────────┴──────────────┴──────────────┴────────────┤
│ SQLAlchemy / Alembic / PostgreSQL or development SQLite│
├─────────────────────────────────────────────────────────┤
│ Optional Bedrock judge and isolated Docker runner       │
└─────────────────────────────────────────────────────────┘
```

No frontend framework, Redis, Celery, vector database, Kubernetes cluster, or
microservice fleet is required for the current vertical slice.

## Repository layout

```text
acil/
  adapters.py              Provider event normalization
  api_targets.py           Safe API URL normalization/fingerprinting
  auth.py                  API-key authentication and tenant context
  background_judge.py      Asynchronous Bedrock judge worker
  config.py                Environment-driven settings
  context.py               Context compilation and Markdown rendering
  db.py                    SQLAlchemy engine/session setup
  evaluations.py           Project evaluation and strategy validation
  failures.py              Failure fingerprints and recurrence records
  global_evaluations.py    Cross-tenant evaluation logic
  global_learning.py       De-identified global recurrence aggregation
  judge.py                 Deterministic, Bedrock, Kimi, and Gemini adapters
  main.py                  FastAPI routes and event persistence
  mcp_server.py            Agent-facing MCP tools
  models.py                SQLAlchemy models
  risk.py                  Pre-execution recurrence/risk checks
  runner.py                Optional isolated Docker evaluation runner
  schemas.py               Pydantic v2 request/response models
  static/                  Minimal operations console
migrations/                Alembic migrations
tests/                     Automated tests
AGENTS.md                  Shared Codex operating contract
docker-compose.yml         PostgreSQL and API development services
pyproject.toml             Project and optional dependency groups
uv.lock                    Reproducible dependency lock
```

## Prerequisites

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)
- Docker and Docker Compose for PostgreSQL or isolated evaluations
- AWS credentials and Bedrock model access only when using the LLM judge
- Codex CLI only when testing the MCP integration with Codex

All Python dependency installation and Python commands in this project use
`uv`.

## Quick start with SQLite

SQLite is useful for local development and the fast automated test suite.
PostgreSQL is the intended deployment database.

```bash
git clone https://github.com/tusharrworkk-lab/AICL.git
cd AICL

uv sync --extra dev --extra bedrock
cp .env.example .env
```

Set the local database in `.env`:

```dotenv
ACIL_DATABASE_URL=sqlite:///./acil.db
ACIL_API_KEY=replace-with-a-local-development-key
ACIL_LOG_LEVEL=INFO
```

Apply migrations and create the development tenant:

```bash
uv run alembic upgrade head
uv run python -m acil.bootstrap
```

Start the API:

```bash
uv run uvicorn acil.main:app --host 127.0.0.1 --port 8000 --reload
```

Verify it:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok","service":"acil"}
```

Open:

- Operations console: `http://127.0.0.1:8000/console`
- OpenAPI documentation: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

The default `acil-dev-key` exists only for local development. Set a different
`ACIL_API_KEY` before bootstrapping a new environment.

## PostgreSQL setup

Start PostgreSQL:

```bash
docker compose up -d postgres
```

Configure `.env`:

```dotenv
ACIL_DATABASE_URL=postgresql+psycopg://acil:acil@localhost:5432/acil
ACIL_API_KEY=replace-with-a-local-development-key
```

Apply migrations, bootstrap the development tenant, and start ACIL:

```bash
uv run alembic upgrade head
uv run python -m acil.bootstrap
uv run uvicorn acil.main:app --host 127.0.0.1 --port 8000
```

Check migration state:

```bash
uv run alembic current
uv run alembic heads
```

Both commands should report the same migration revision.

### PostgreSQL limitation

Application-level tenant authorization is implemented and tested. PostgreSQL
row-level security policies and transaction-scoped tenant settings are not yet
implemented. Treat RLS as required production hardening, not as a completed
security property.

## Environment configuration

Start from `.env.example`. Never commit `.env`, cloud credentials, model API
keys, or service-account files.

### Core service

| Variable | Purpose | Typical value |
|---|---|---|
| `ACIL_DATABASE_URL` | SQLAlchemy database URL | `sqlite:///./acil.db` or PostgreSQL URL |
| `ACIL_API_KEY` | Development bootstrap key / MCP default key | Secret value |
| `ACIL_LOG_LEVEL` | Application logging level | `INFO` |
| `ACIL_EVALUATION_RUNNER_ENABLED` | Enables isolated Docker execution | `false` |
| `ACIL_EVALUATION_DOCKER_IMAGE` | Pre-reviewed evaluation image | Image name |
| `ACIL_EVALUATION_TIMEOUT_SECONDS` | Runner timeout | `120` |

### Project routing for Codex workspaces

Each repository monitored by ACIL can contain non-secret routing values:

```dotenv
ACIL_MCP_SERVER=acil
ACIL_TENANT_ID=<tenant-uuid>
ACIL_PROJECT_ID=<project-uuid>
ACIL_BASE_URL=http://127.0.0.1:8000
```

The tenant API key belongs in the Codex MCP registration, not in `AGENTS.md` or
agent prompts. Keep the project `.env` ignored by Git.

## Authentication and tenancy

HTTP endpoints use Bearer authentication:

```bash
curl \
  -H 'Authorization: Bearer <tenant-api-key>' \
  http://127.0.0.1:8000/v1/projects
```

ACIL stores SHA-256 hashes of API keys rather than raw keys. Authentication
resolves an API key to a tenant context. Project, session, event, failure,
evaluation, strategy, context, and judge-run queries then enforce that tenant.

Cross-tenant project access returns `404` rather than revealing whether another
tenant's resource exists.

Global learning is disabled by default. Enable it per tenant:

```bash
curl -X POST http://127.0.0.1:8000/v1/tenant/learning \
  -H 'Authorization: Bearer <tenant-api-key>' \
  -H 'Content-Type: application/json' \
  -d '{"enabled":true}'
```

Opted-in global learning stores de-identified recurrence fields. It does not
return another tenant's raw trace, project ID, command output, source code, or
private judge report.

## Create and inspect a project

Create a project:

```bash
curl -X POST http://127.0.0.1:8000/v1/projects \
  -H 'Authorization: Bearer <tenant-api-key>' \
  -H 'Content-Type: application/json' \
  -d '{
    "name":"Example Project",
    "slug":"example-project",
    "description":"ACIL integration test"
  }'
```

Copy the returned project UUID into that repository's `.env` as
`ACIL_PROJECT_ID`.

List projects:

```bash
curl \
  -H 'Authorization: Bearer <tenant-api-key>' \
  http://127.0.0.1:8000/v1/projects
```

## Canonical event ingestion

The canonical event is the stable boundary between ACIL and provider-specific
agents:

```json
{
  "event_id": "event-001",
  "project_id": "project-uuid",
  "session_id": "session-uuid",
  "trace_id": "trace-001",
  "span_id": "span-001",
  "parent_span_id": null,
  "agent_type": "codex",
  "event_type": "tool.failed",
  "canonical_action": "CALL_EXTERNAL_API",
  "native_tool_name": "python",
  "status": "failed",
  "timestamp": "2026-10-27T10:30:00Z",
  "duration_ms": 1200,
  "error_type": "dns_resolution_failure",
  "api_url": "https://api.example.com/v1/items/123?token=never-store-this",
  "attributes": {
    "environment_fingerprint": "python-3.12",
    "tool_capabilities": ["network"]
  }
}
```

Submit it:

```bash
curl -X POST http://127.0.0.1:8000/v1/events \
  -H 'Authorization: Bearer <tenant-api-key>' \
  -H 'Content-Type: application/json' \
  -d @event.json
```

ACIL supports batches of up to 1,000 events at `POST /v1/events/batch`.
`event_id` is idempotent within a tenant. Repeating the same tenant/event ID
returns the existing event rather than creating duplicate evidence.

## API target normalization

ACIL accepts an API target as top-level `api_url`, as `attributes.api_url`, or
as a literal HTTP(S) URL in observable command/input/output/error/request/
response text.

Before persistence it:

- removes query parameters and fragments;
- excludes URL credentials;
- lowercases the host;
- replaces numeric path segments with `{id}`;
- replaces UUID path segments with `{uuid}`;
- stores a stable SHA-256 target fingerprint;
- discards the raw URL and raw command/output fields used for extraction.

These calls therefore share an API-target fingerprint:

```text
https://api.example.com/v1/items/123?token=a
https://api.example.com/v1/items/456?token=b
```

Normalized target:

```text
https://api.example.com/v1/items/{id}
```

Failure grouping additionally considers canonical action, error type, native
tool, environment fingerprint, and tool capabilities. The same endpoint with
HTTP 404 and authentication failure remains two distinct failure patterns.

## Pre-execution risk checks

Agents can ask ACIL before repeating an API call:

```bash
curl -X POST http://127.0.0.1:8000/v1/risk/evaluate \
  -H 'Authorization: Bearer <tenant-api-key>' \
  -H 'Content-Type: application/json' \
  -d '{
    "project_id":"project-uuid",
    "canonical_action":"CALL_EXTERNAL_API",
    "error_type":"dns_resolution_failure",
    "environment_fingerprint":"python-3.12",
    "api_url":"https://api.example.com/v1/items/999"
  }'
```

Decisions:

- `ALLOW`: no matching opted-in recurrence evidence
- `WARN`: relevant failure evidence exists
- `REQUIRE_CONFIRMATION`: recurrence crosses the confirmation threshold

A risk result is advisory operational context, not higher-priority authority.

## Failure, evaluation, and knowledge lifecycle

```text
CANDIDATE
  → authorized recovery execution
  → deterministic evaluation pass
  → VALIDATED
  → explicit activation
  → ACTIVE
  → DEPRECATED (future lifecycle operation)
```

Important rules:

- A failure creates evidence and may create candidates; it does not create truth.
- A Bedrock judgment can explain blockers and propose measurable improvements.
- Bedrock cannot validate a claim merely by expressing confidence.
- A failed journey cannot validate its own recovery strategy.
- Only successful observable recovery evidence can pass the deterministic gate.
- Activation remains explicit and separate from validation.
- Only active applicable strategies are returned as operational context.

The current predefined recovery template originated with the Python test-
dependency demonstration. It must not be treated as a valid API/DNS recovery
strategy. The operations console suppresses incompatible test templates for API
failures. Failure-specific recovery generation remains an active product area.

## Asynchronous Bedrock judge

`report_failure_for_review` persists the event first and then queues the LLM
judgment. Codex receives an immediate response:

```json
{
  "bedrock_judgment": {
    "requested": true,
    "status": "queued",
    "run_id": "judge-run-uuid",
    "message": "Bedrock judgment is running asynchronously; Codex does not need to wait."
  }
}
```

The persisted lifecycle is:

```text
QUEUED → RUNNING → PASSED | FAILED | ERROR
```

Retrieve status through MCP `get_judge_run_status` or HTTP:

```bash
curl \
  -H 'Authorization: Bearer <tenant-api-key>' \
  http://127.0.0.1:8000/v1/judge/runs/<run-id>
```

List recent tenant-private runs:

```bash
curl \
  -H 'Authorization: Bearer <tenant-api-key>' \
  http://127.0.0.1:8000/v1/judge/runs
```

The current queue uses an in-process thread pool. Database state is persisted
before submission, and a new MCP process resumes `QUEUED`/`RUNNING` records.
An abrupt termination during a provider request can result in a repeated,
billable request after restart. A dedicated durable worker and idempotent
provider-request key are production-hardening items.

## Configure Amazon Bedrock

Install the optional dependency:

```bash
uv sync --extra dev --extra bedrock
```

### IAM or AWS SSO

```dotenv
BEDROCK_REGION=ap-south-1
BEDROCK_MODEL=in.moonshotai.kimi-k3
BEDROCK_AUTH_MODE=iam
AWS_PROFILE=bedrock-mumbai
KIMI_CHAT_MAX_OUTPUT_TOKENS=2048
BEDROCK_MAX_OUTPUT_TOKENS=512
BEDROCK_REASONING_EFFORT=low
BEDROCK_TEMPERATURE=0.2
```

Authenticate outside ACIL:

```bash
aws sso login --profile bedrock-mumbai
aws sts get-caller-identity --profile bedrock-mumbai
```

Kimi K3 uses Bedrock's OpenAI-compatible Chat Completions endpoint with SigV4
IAM authentication and JSON-schema-constrained final output. Private reasoning
content is not stored or returned.

### Bedrock API key

```dotenv
BEDROCK_AUTH_MODE=api_key
BEDROCK_API_KEY=<secret>
BEDROCK_REGION=ap-south-1
BEDROCK_MODEL=google.gemma-3-4b-it
BEDROCK_MAX_OUTPUT_TOKENS=512
```

The adapter maps `BEDROCK_API_KEY` to the AWS Bedrock bearer-token environment
expected by the SDK. Keep it in a secret manager or ignored `.env`, never in
Git, prompts, traces, or `AGENTS.md`.

For structured judge output, keep output tokens at 256 or higher. Kimi K3
normally needs the larger `KIMI_CHAT_MAX_OUTPUT_TOKENS` setting.

Check non-secret readiness:

```bash
curl \
  -H 'Authorization: Bearer <tenant-api-key>' \
  http://127.0.0.1:8000/v1/judge/status
```

This readiness endpoint does not make a billable model call.

## MCP integration

Run the MCP server directly for development:

```bash
uv run python -m acil.mcp_server
```

Add Tenant A to Codex:

```bash
codex mcp add acil \
  --env ACIL_DATABASE_URL='sqlite:////absolute/path/to/acil.db' \
  --env ACIL_API_KEY='<tenant-a-api-key>' \
  -- uv --directory /absolute/path/to/AICL run python -m acil.mcp_server
```

For concurrent cross-tenant testing, add a separately credentialed server:

```bash
codex mcp add acil-tenant-b \
  --env ACIL_DATABASE_URL='sqlite:////absolute/path/to/acil.db' \
  --env ACIL_API_KEY='<tenant-b-api-key>' \
  -- uv --directory /absolute/path/to/AICL run python -m acil.mcp_server
```

Inspect registrations:

```bash
codex mcp list
codex mcp get acil
codex mcp get acil-tenant-b
```

Restart Codex after adding, removing, or changing an MCP server. Existing Codex
sessions retain the MCP process and instruction context they started with.

Available MCP tools:

- `evaluate_action_risk`
- `get_execution_context`
- `get_known_failures`
- `get_validated_strategies`
- `report_execution_outcome`
- `report_failure_for_review`
- `get_judge_run_status`

## Codex workspace instructions

Copy `AGENTS.md` into the root of each repository used by Codex:

```bash
cp /absolute/path/to/AICL/AGENTS.md /absolute/path/to/target-project/AGENTS.md
```

The filename must be uppercase: `AGENTS.md`. A lowercase `agents.md` will not
reliably provide project instructions.

The shared contract instructs Codex to:

1. Read project routing from `.env`.
2. Use the tenant-matching MCP server.
3. Run `evaluate_action_risk` before external API calls.
4. Report observable outcomes.
5. Queue Bedrock review for failures.
6. Continue without waiting for the asynchronous judge.
7. Never treat judge analysis as validated knowledge.
8. Keep validation and activation evidence-driven and explicit.

## Agent adapter boundary

Provider adapters are available through `acil.adapters` and
`POST /v1/events/normalized`:

- `generic`
- `codex`
- `claude_code`

They translate observable provider events into the canonical model. They do not
capture hidden reasoning. Provider event formats may evolve, so the canonical
event remains the stable persistence and evaluation boundary.

MCP context retrieval and native execution tracing are separate concerns. An
agent can retrieve context through MCP without automatically sending every tool
event; the integration must report observable outcomes explicitly.

## Operations console

Open `http://127.0.0.1:8000/console` and enter the API base URL and tenant API
key.

The sanitized console shows:

- tenant-authorized projects;
- recent observable execution events;
- deterministic failure patterns and recurrence counts;
- validated/active compatible knowledge only;
- Bedrock configuration readiness without secrets;
- asynchronous judge run states;
- tenant-private negative-case analysis and blockers.

It intentionally does not expose:

- candidate strategies as recommendations;
- hard-coded controlled-validation buttons;
- simulated demo injection;
- compiled agent context previews;
- raw API URLs, query credentials, or another tenant's evidence.

The API key is kept in browser `sessionStorage`, not persistent
`localStorage`, and is removed when the browser session ends.

## HTTP API summary

### Public

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Service health |
| `GET` | `/console` | Operations console |

### Tenant and projects

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/tenant/learning` | Enable/disable shared learning |
| `POST` | `/v1/projects` | Create project |
| `GET` | `/v1/projects` | List tenant projects |
| `GET` | `/v1/projects/{id}` | Get authorized project |

### Events and failures

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/events` | Ingest canonical event |
| `POST` | `/v1/events/batch` | Ingest up to 1,000 events |
| `POST` | `/v1/events/normalized` | Ingest provider-native event |
| `GET` | `/v1/sessions/{id}/trace` | Ordered session trace |
| `GET` | `/v1/projects/{id}/events` | Recent project events |
| `GET` | `/v1/failures` | List failure patterns |
| `GET` | `/v1/failures/{id}` | Failure with occurrences |

### Evaluations and strategies

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/evaluations` | Project evaluation definitions |
| `POST` | `/v1/evaluations/{id}/run` | Submit deterministic evidence |
| `GET` | `/v1/strategies` | Project strategy versions |
| `POST` | `/v1/strategies/{id}/activate` | Activate validated strategy |
| `GET` | `/v1/global/evaluations` | Global definitions |
| `POST` | `/v1/global/evaluations/{id}/run` | Evaluate supplied journey |
| `POST` | `/v1/global/evaluations/{id}/execute` | Run authorized isolated target |
| `GET` | `/v1/global/strategies` | Validated/active global strategies |
| `POST` | `/v1/global/strategies/{id}/activate` | Activate validated global strategy |

### Risk, context, and judge

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/risk/evaluate` | Pre-execution recurrence assessment |
| `POST` | `/v1/context/compile` | Structured/Markdown agent context |
| `GET` | `/v1/judge/status` | Non-secret provider readiness |
| `GET` | `/v1/judge/runs` | Tenant-private async runs |
| `GET` | `/v1/judge/runs/{id}` | Async run status/result |
| `GET` | `/v1/negative-cases` | Completed negative-case findings |

## Isolated evaluation runner

The runner is disabled by default. When enabled, it executes only ACIL's fixed,
reviewed action templates inside a server-selected Docker image. Model output,
untrusted trace commands, and arbitrary caller commands never control the
Docker command line.

Security controls include:

- network disabled;
- no host source mounts;
- read-only root filesystem;
- dropped Linux capabilities;
- non-root UID;
- process, CPU, and memory limits;
- execution timeout;
- raw container output not persisted.

Build the controlled example image from the target repository:

```bash
docker build -f evaluation-target.Dockerfile -t acil-evaluation-target:local .
```

Configure ACIL:

```dotenv
ACIL_EVALUATION_RUNNER_ENABLED=true
ACIL_EVALUATION_DOCKER_IMAGE=acil-evaluation-target:local
ACIL_EVALUATION_TIMEOUT_SECONDS=120
```

Then invoke:

```text
POST /v1/global/evaluations/{evaluation-id}/execute
```

with:

```json
{"judge_provider":"bedrock"}
```

## Testing

Install development dependencies:

```bash
uv sync --extra dev --extra bedrock
```

Run everything:

```bash
uv run ruff check acil tests
uv run pytest -q
```

Run focused areas:

```bash
uv run pytest -q tests/test_api.py
uv run pytest -q tests/test_mcp.py
uv run pytest -q tests/test_judge.py
uv run pytest -q tests/test_runner.py
```

The core suite mocks provider responses and requires no paid credentials.

Current test coverage prioritizes:

- tenant authorization boundaries;
- event idempotency;
- ordered trace reconstruction;
- secret redaction;
- API-target normalization;
- failure fingerprint stability;
- recurrence grouping;
- deterministic evaluation correctness;
- strategy validation and activation;
- risk matching;
- MCP authorization;
- asynchronous judge queuing;
- provider-output parsing;
- isolated-runner safety flags.

## Security and trust boundaries

- Raw API keys are not stored in database rows.
- Secret-shaped event attributes are redacted.
- Event attributes are capped at 32 KiB.
- Raw API URL queries, fragments, and credentials are discarded.
- Event evidence is append-only at the application API.
- Cross-tenant raw evidence sharing is disabled.
- Global learning requires explicit tenant opt-in.
- LLM judge output is advisory and lower trust than reproducible evidence.
- Private chain-of-thought is neither requested nor stored.
- Arbitrary commands from traces or LLM responses are never executed.
- Isolated evaluation requires explicit server configuration.

## Troubleshooting

### `401 Invalid API key`

- Use `Authorization: Bearer <tenant-api-key>`.
- Verify the key belongs to the intended tenant.
- Restart Codex after changing an MCP registration.
- Do not confuse a project routing `.env` with MCP credential configuration.

### `Project not found`

- Confirm the exact project UUID with `GET /v1/projects` using the same key.
- Confirm the selected MCP server uses that tenant's key.
- Check UUID transcription carefully.
- Verify the project has uppercase `AGENTS.md` and a current `.env`.
- Start a fresh Codex session; resumed sessions can retain stale MCP context.

### MCP tools do not update

MCP stdio processes do not hot-reload inside an existing Codex session. Exit
Codex completely and start a new session from the project directory.

### Bedrock run remains `QUEUED`

- Ensure the originating MCP process is still running.
- Restart the MCP process to resume queued records.
- Verify AWS credentials, region, and model access.
- Check `GET /v1/judge/runs/{id}` for `ERROR` and its bounded error message.

### Invalid structured judge output

- Set `BEDROCK_MAX_OUTPUT_TOKENS` to at least `256`.
- Use a larger `KIMI_CHAT_MAX_OUTPUT_TOKENS`, such as `2048`.
- Confirm the configured model supports the selected adapter path.

### DNS failures while testing agents

Distinguish a script's exit code from individual API outcomes. A script that
catches exceptions can exit zero while every network request failed. Report
each observable API call separately to ACIL.

### Empty validated-knowledge panel

This is expected when no compatible strategy has both passed deterministic
validation and been activated. Candidates and incompatible prototype templates
are intentionally hidden from the product-facing console.

## Current limitations

- PostgreSQL RLS is not yet implemented.
- The automated suite primarily uses SQLite; a real PostgreSQL integration suite
  is still required for production confidence.
- The asynchronous judge uses an in-process worker rather than a dedicated
  durable queue service.
- Provider-native tracing is best-effort and depends on observable integration
  surfaces; ACIL does not access proprietary internal reasoning.
- Strategy generation still includes an early Python dependency-recovery
  template and needs failure-specific API/network/authentication templates.
- Strategy contradiction detection and negative-transfer scoring remain limited.
- There is no administrative tenant-management API or production key-rotation
  workflow yet.
- The operations console is intentionally minimal and not a full dashboard.

## Non-goals

ACIL is not:

- a replacement for Codex, Claude Code, or another agent;
- a general autonomous command runner;
- a model-training or fine-tuning pipeline;
- a cross-tenant raw-data exchange;
- an unrestricted shell execution service;
- a vector-memory platform;
- a frontend/dashboard product;
- a distributed workflow system.

## Development commands

```bash
# Install/update locked dependencies
uv sync --extra dev --extra bedrock

# Apply schema migrations
uv run alembic upgrade head

# Show migration state
uv run alembic current

# Bootstrap local development tenant
uv run python -m acil.bootstrap

# Run API
uv run uvicorn acil.main:app --reload

# Run MCP server
uv run python -m acil.mcp_server

# Lint and test
uv run ruff check acil tests
uv run pytest -q
```

## License and contribution status

This repository is currently a research-oriented hackathon prototype. Before
production use, add an explicit license, production tenant provisioning,
PostgreSQL RLS, secret-manager integration, durable background processing,
audit retention policy, and live PostgreSQL security tests.
